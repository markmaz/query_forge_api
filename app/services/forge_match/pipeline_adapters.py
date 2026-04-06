from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy.exc import SQLAlchemyError

from app.exceptions.forge_error import ForgeError
from app.services.forge_match.confidence import ForgeMatchConfidenceScorer
from app.services.forge_match.field_extractor import SourceFieldRecord
from app.services.forge_match.llm_ranker import ForgeMatchLLMRanker
from app.services.forge_match.session_pipeline_artifacts import (
    ForgeMatchSessionExecutionArtifact,
    ForgeMatchSessionResultArtifact,
    ForgeMatchSessionWorkArtifact,
)
from app.services.shared_ai.adapters.candidates import candidate_from_column_row, candidate_to_dict
from app.services.shared_ai.artifacts import (
    CandidateSetArtifact,
    ConfidenceArtifact,
    LLMDecisionArtifact,
    MatchOutcomeArtifact,
    PersistenceArtifact,
)
from app.services.shared_ai.context import PipelineContext

logger = logging.getLogger(__name__)

PERSISTENCE_SOURCE_ID_ERRORS = (TypeError, ValueError)
ROW_PIPELINE_FALLBACK_ERRORS = (ForgeError, OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError)
JSON_PARSE_FALLBACK_ERRORS = (TypeError, ValueError, json.JSONDecodeError)


class ForgeMatchLLMDecisionAdapter:
    def __init__(self, *, ranker: ForgeMatchLLMRanker) -> None:
        self._ranker = ranker

    def rank(self, *, context: PipelineContext, candidates: CandidateSetArtifact) -> LLMDecisionArtifact:
        source_record = context.request.get("source_record")
        if not isinstance(source_record, SourceFieldRecord):
            raise TypeError("ForgeMatchLLMDecisionAdapter requires SourceFieldRecord in request['source_record'].")

        rows = [candidate_to_dict(candidate) for candidate in list(candidates.candidates or [])]
        llm_id = context.request.get("llm_id")
        payload = self._ranker.rank(
            workspace_id=str(context.workspace_id or "").strip(),
            source_record=source_record,
            candidates=rows,
            llm_id=int(llm_id) if llm_id is not None else None,
        )
        ranked_candidate_ids = []
        selected_candidate_id = str(payload.get("selected_column_id") or "").strip() or None
        if selected_candidate_id:
            ranked_candidate_ids.append(selected_candidate_id)
        ranked_candidate_ids.extend(
            str(item)
            for item in list(payload.get("alternate_column_ids") or [])
            if str(item).strip() and str(item) not in ranked_candidate_ids
        )
        return LLMDecisionArtifact(
            selected_candidate_id=selected_candidate_id,
            ranked_candidate_ids=ranked_candidate_ids,
            confidence=float(payload.get("llm_confidence") or 0.0),
            explanation=str(payload.get("explanation") or "").strip() or None,
            raw_payload=dict(payload),
        )


class ForgeMatchConfidenceAdapter:
    def __init__(self, *, scorer: ForgeMatchConfidenceScorer) -> None:
        self._scorer = scorer

    def score(
        self,
        *,
        context: PipelineContext,
        candidates: CandidateSetArtifact,
        decision: LLMDecisionArtifact,
    ) -> ConfidenceArtifact:
        source_record = context.request.get("source_record")
        if not isinstance(source_record, SourceFieldRecord):
            raise TypeError("ForgeMatchConfidenceAdapter requires SourceFieldRecord in request['source_record'].")

        rows = [candidate_to_dict(candidate) for candidate in list(candidates.candidates or [])]
        selected_row: Optional[dict] = None
        if decision.selected_candidate_id is not None:
            for row in rows:
                if str(row.get("column_id") or row.get("candidate_id") or "").strip() == str(decision.selected_candidate_id):
                    selected_row = row
                    break

        score_payload = self._scorer.score(
            source_record=source_record,
            selected_candidate=selected_row,
            candidates=rows,
            llm_result=dict(decision.raw_payload or {}),
        )
        return ConfidenceArtifact(
            confidence_score=int(score_payload.get("confidence_score") or 0),
            confidence_band=str(score_payload.get("confidence_band") or "low"),
            details=dict(score_payload),
        )


class ForgeMatchPersistenceAdapter:
    def __init__(
        self,
        *,
        persist_result: Callable[..., None],
    ) -> None:
        self._persist_result = persist_result

    def persist(
        self,
        *,
        context: PipelineContext,
        outcome: MatchOutcomeArtifact,
    ) -> PersistenceArtifact:
        session_id = str(context.request.get("session_id") or "").strip()
        if not session_id:
            raise TypeError("ForgeMatchPersistenceAdapter requires session_id in request['session_id'].")
        try:
            source_record_id = int(context.request.get("source_record_id") or 0)
        except PERSISTENCE_SOURCE_ID_ERRORS as exc:
            raise TypeError(
                "ForgeMatchPersistenceAdapter requires integer source_record_id in request['source_record_id']."
            ) from exc
        if source_record_id <= 0:
            raise TypeError("ForgeMatchPersistenceAdapter requires positive source_record_id in request.")

        self._persist_result(
            session_id=session_id,
            source_record_id=source_record_id,
            selected=outcome.selected_candidate,
            alternates=outcome.alternates,
            candidates=outcome.candidates,
            llm_rank=outcome.decision_payload,
            confidence=outcome.confidence_payload,
        )
        return PersistenceArtifact(
            record_id=f"{session_id}:{source_record_id}",
            status="persisted",
            details={
                "session_id": session_id,
                "source_record_id": source_record_id,
                "selected_column_id": (
                    outcome.selected_candidate.get("column_id") if outcome.selected_candidate else None
                ),
            },
        )


class ExistingRetrieverCandidateAdapter:
    def __init__(self, *, retriever: object) -> None:
        self._retriever = retriever

    def retrieve(self, *, context: PipelineContext) -> CandidateSetArtifact:
        source_record = context.request.get("source_record")
        if not isinstance(source_record, SourceFieldRecord):
            raise TypeError("ExistingRetrieverCandidateAdapter requires SourceFieldRecord in request['source_record'].")
        rows = self._retriever.retrieve(
            workspace_id=str(context.workspace_id or "").strip(),
            source_record=source_record,
            top_n=int(context.request.get("top_n") or 8),
            vertical_norm=str(context.vertical_norm or "generic"),
            domain_id=int(context.request["domain_id"]) if context.request.get("domain_id") is not None else None,
        )
        return CandidateSetArtifact(
            candidates=[candidate_from_column_row(row) for row in rows],
            retrieval_debug={
                "candidate_count": len(rows),
                "mode": "existing_retriever_adapter",
            },
        )


class ForgeMatchSessionPreparationAdapter:
    def __init__(
        self,
        *,
        load_session: Callable[..., dict[str, Any]],
        load_source_rows: Callable[..., list[dict[str, Any]]],
        existing_results_by_source: Callable[..., dict[int, str]],
        clear_results: Callable[..., None],
        update_progress: Callable[..., None],
    ) -> None:
        self._load_session = load_session
        self._load_source_rows = load_source_rows
        self._existing_results_by_source = existing_results_by_source
        self._clear_results = clear_results
        self._update_progress = update_progress

    def prepare(self, *, context: PipelineContext) -> ForgeMatchSessionWorkArtifact:
        workspace_id = str(context.workspace_id or "").strip()
        session_id = str(context.request.get("session_id") or "").strip()
        force = bool(context.request.get("force"))
        job_id = _text_or_none(context.request.get("job_id"))

        session = self._load_session(workspace_id=workspace_id, session_id=session_id)
        source_rows = self._load_source_rows(session_id=session_id)
        if not source_rows:
            from app.exceptions.forge_error import ForgeError

            raise ForgeError("No source records found for session", status_code=400)

        if force:
            self._clear_results(session_id=session_id)

        source_total = len(source_rows)
        existing_by_source = {} if force else self._existing_results_by_source(session_id=session_id)
        self._update_progress(
            session_id=session_id,
            status="analyzing",
            job_id=job_id,
            source_total=source_total,
            source_done=0,
            source_skipped=0,
            source_failed=0,
            current_phase="analyzing",
            current_source_row_id=None,
            analysis_error=None,
            cancel_requested=False,
            started_at=datetime.now(timezone.utc),
            completed_at=None,
        )
        context.metadata["session_progress"] = {"source_total": source_total}
        _set_session_progress(context, analyzed=0, skipped=0, failed=0)
        return ForgeMatchSessionWorkArtifact(
            session=session,
            source_rows=list(source_rows),
            existing_by_source=dict(existing_by_source),
            source_total=source_total,
        )


class ForgeMatchSessionExecutionAdapter:
    def __init__(
        self,
        *,
        is_cancel_requested: Callable[..., bool],
        update_progress: Callable[..., None],
        run_row_pipeline: Callable[..., tuple[Any, dict[str, Any], Any]],
        persist_failure_result: Callable[..., None],
    ) -> None:
        self._is_cancel_requested = is_cancel_requested
        self._update_progress = update_progress
        self._run_row_pipeline = run_row_pipeline
        self._persist_failure_result = persist_failure_result

    def execute(
        self,
        *,
        context: PipelineContext,
        work: ForgeMatchSessionWorkArtifact,
    ) -> ForgeMatchSessionExecutionArtifact:
        workspace_id = str(context.workspace_id or "").strip()
        session_id = str(context.request.get("session_id") or "").strip()
        job_id = _text_or_none(context.request.get("job_id"))
        force = bool(context.request.get("force"))
        top_n = max(3, int(context.request.get("top_n") or 8))
        vertical_norm = _text_or_none(context.request.get("vertical_norm")) or str(context.vertical_norm or "generic")
        domain_id = _safe_int(context.request.get("domain_id"))
        llm_id = _safe_int(context.request.get("llm_id"))

        analyzed = 0
        skipped = 0
        failed = 0

        for source in list(work.source_rows or []):
            src_id = int(source["id"])
            current_source_row_id = str(source.get("row_id") or "")

            if self._is_cancel_requested(session_id=session_id):
                self._update_progress(
                    session_id=session_id,
                    status="canceled",
                    job_id=job_id,
                    source_total=work.source_total,
                    source_done=analyzed,
                    source_skipped=skipped,
                    source_failed=failed,
                    current_phase="canceled",
                    current_source_row_id=current_source_row_id or None,
                    analysis_error="Canceled by operator",
                    cancel_requested=True,
                    started_at=None,
                    completed_at=datetime.now(timezone.utc),
                )
                _set_session_progress(context, analyzed=analyzed, skipped=skipped, failed=failed)
                return ForgeMatchSessionExecutionArtifact(
                    status="canceled",
                    analyzed_count=analyzed,
                    skipped_count=skipped,
                    failed_count=failed,
                    last_source_row_id=current_source_row_id or None,
                    current_phase="canceled",
                )

            if (not force) and src_id in work.existing_by_source:
                skipped += 1
                self._update_progress(
                    session_id=session_id,
                    status="analyzing",
                    job_id=job_id,
                    source_total=work.source_total,
                    source_done=analyzed,
                    source_skipped=skipped,
                    source_failed=failed,
                    current_phase="skipping_existing",
                    current_source_row_id=current_source_row_id or None,
                )
                _set_session_progress(context, analyzed=analyzed, skipped=skipped, failed=failed)
                continue

            source_record = SourceFieldRecord(
                row_id=str(source.get("row_id") or ""),
                sheet_name=str(source.get("sheet_name") or ""),
                row_number=int(source.get("row_number") or 0),
                source_field_name=str(source.get("source_field_name") or ""),
                source_description=_text_or_none(source.get("source_description")),
                source_type=_text_or_none(source.get("source_type")),
                source_object_name=_text_or_none(source.get("source_object_name")),
                sample_value=_text_or_none(source.get("sample_value")),
                category=_text_or_none(source.get("category")),
                normalized_search_text=str(source.get("normalized_search_text") or ""),
                raw_row=_parse_json_dict(source.get("raw_row_json")) or {},
            )

            try:
                self._run_row_pipeline(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    source_record_id=src_id,
                    source_record=source_record,
                    top_n=top_n,
                    vertical_norm=vertical_norm,
                    domain_id=domain_id,
                    llm_id=llm_id,
                )
                analyzed += 1
                current_phase = "ranking"
            except ROW_PIPELINE_FALLBACK_ERRORS as row_exc:
                failed += 1
                logger.exception(
                    "ForgeMatch row analyze failed session_id=%s source_record_id=%s",
                    session_id,
                    src_id,
                )
                self._persist_failure_result(
                    session_id=session_id,
                    source_record_id=src_id,
                    selected=None,
                    alternates=[],
                    candidates=[],
                    llm_rank={
                        "match_decision": "no_confident_match",
                        "reason_codes": ["processing_error"],
                        "explanation": f"Processing error: {str(row_exc)[:300]}",
                        "ambiguity_note": None,
                        "llm_confidence": 0.0,
                    },
                    confidence={"confidence_score": 0, "confidence_band": "low"},
                )
                current_phase = "row_error"

            self._update_progress(
                session_id=session_id,
                status="analyzing",
                job_id=job_id,
                source_total=work.source_total,
                source_done=analyzed,
                source_skipped=skipped,
                source_failed=failed,
                current_phase=current_phase,
                current_source_row_id=current_source_row_id or None,
            )
            _set_session_progress(context, analyzed=analyzed, skipped=skipped, failed=failed)

        return ForgeMatchSessionExecutionArtifact(
            status="completed",
            analyzed_count=analyzed,
            skipped_count=skipped,
            failed_count=failed,
            last_source_row_id=None,
            current_phase="analyzed",
        )


class ForgeMatchSessionFinalizationAdapter:
    def __init__(
        self,
        *,
        load_mapping_rows: Callable[..., list[dict[str, Any]]],
        build_summary: Callable[[list[dict[str, Any]]], dict[str, Any]],
        update_progress: Callable[..., None],
    ) -> None:
        self._load_mapping_rows = load_mapping_rows
        self._build_summary = build_summary
        self._update_progress = update_progress

    def finalize(
        self,
        *,
        context: PipelineContext,
        work: ForgeMatchSessionWorkArtifact,
        execution: ForgeMatchSessionExecutionArtifact,
    ) -> ForgeMatchSessionResultArtifact:
        workspace_id = str(context.workspace_id or "").strip()
        session_id = str(context.request.get("session_id") or "").strip()
        job_id = _text_or_none(context.request.get("job_id"))
        mappings = self._load_mapping_rows(workspace_id=workspace_id, session_id=session_id)
        summary = self._build_summary(mappings)

        if execution.status == "canceled":
            return ForgeMatchSessionResultArtifact(
                payload={
                    "job_id": job_id,
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "status": "canceled",
                    "result_count": len(mappings),
                    "analyzed_count": execution.analyzed_count,
                    "skipped_count": execution.skipped_count,
                    "failed_count": execution.failed_count,
                    "summary": summary,
                    "mappings": mappings,
                    "session": work.session,
                }
            )

        warning_error = None
        if execution.failed_count > 0:
            warning_error = f"Completed with row errors: failed_count={execution.failed_count}"

        self._update_progress(
            session_id=session_id,
            status="analyzed",
            job_id=job_id,
            source_total=work.source_total,
            source_done=execution.analyzed_count,
            source_skipped=execution.skipped_count,
            source_failed=execution.failed_count,
            current_phase="analyzed",
            current_source_row_id=None,
            analysis_error=warning_error,
            completed_at=datetime.now(timezone.utc),
        )

        return ForgeMatchSessionResultArtifact(
            payload={
                "job_id": job_id,
                "session_id": session_id,
                "workspace_id": workspace_id,
                "status": "analyzed",
                "result_count": len(mappings),
                "analyzed_count": execution.analyzed_count,
                "skipped_count": execution.skipped_count,
                "failed_count": execution.failed_count,
                "summary": summary,
                "mappings": mappings,
                "session": work.session,
            }
        )


def _set_session_progress(context: PipelineContext, *, analyzed: int, skipped: int, failed: int) -> None:
    payload = dict(context.metadata.get("session_progress") or {})
    payload.update(
        {
        "analyzed_count": int(analyzed),
        "skipped_count": int(skipped),
        "failed_count": int(failed),
        }
    )
    context.metadata["session_progress"] = payload


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_json_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except JSON_PARSE_FALLBACK_ERRORS:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None
