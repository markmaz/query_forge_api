from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain_resolver import DomainPlan, DomainPlanJoin, DomainResolver
from app.services.forge_match.candidate_retriever import ForgeMatchCandidateRetriever, ForgeMatchColumnRetrievalAdapter
from app.services.forge_match.confidence import ForgeMatchConfidenceScorer
from app.services.forge_match.export_service import ForgeMatchExportService
from app.services.forge_match.field_extractor import ForgeMatchFieldExtractor, SourceFieldRecord
from app.services.forge_match.file_parser import ForgeMatchFileParser
from app.services.forge_match.llm_ranker import ForgeMatchLLMRanker
from app.services.forge_match.pipeline_adapters import (
    ExistingRetrieverCandidateAdapter,
    ForgeMatchConfidenceAdapter,
    ForgeMatchLLMDecisionAdapter,
    ForgeMatchPersistenceAdapter,
    ForgeMatchSessionExecutionAdapter,
    ForgeMatchSessionFinalizationAdapter,
    ForgeMatchSessionPreparationAdapter,
)
from app.services.forge_match.pipeline_definition import (
    build_forge_match_candidate_pipeline_definition,
    build_forge_match_row_pipeline_definition,
    build_forge_match_session_pipeline_definition,
)
from app.services.forge_match.session_pipeline_artifacts import ForgeMatchSessionResultArtifact
from app.services.shared_ai.artifacts import MatchOutcomeArtifact, PersistenceArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.executor import PipelineExecutor
from app.services.shared_ai.tracing import serialize_pipeline_context
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder

logger = logging.getLogger(__name__)

_ALLOWED_RESULT_STATUSES = {"suggested", "accepted", "rejected", "needs_review", "manually_mapped"}
_TERMINAL_SESSION_STATUSES = {"uploaded", "analyzed", "failed", "canceled", "cancelled"}
_SQL_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ForgeMatchMappingService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        parser: Optional[ForgeMatchFileParser] = None,
        extractor: Optional[ForgeMatchFieldExtractor] = None,
        retriever: Optional[ForgeMatchCandidateRetriever] = None,
        ranker: Optional[ForgeMatchLLMRanker] = None,
        confidence: Optional[ForgeMatchConfidenceScorer] = None,
        exporter: Optional[ForgeMatchExportService] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._parser = parser or ForgeMatchFileParser()
        self._extractor = extractor or ForgeMatchFieldExtractor()
        self._retriever = retriever or ForgeMatchCandidateRetriever(sql=self._sql)
        self._ranker = ranker or ForgeMatchLLMRanker()
        self._confidence = confidence or ForgeMatchConfidenceScorer()
        self._exporter = exporter or ForgeMatchExportService(sql=self._sql)
        self._pipeline_executor = PipelineExecutor()
        self._extended_progress_columns_supported = True

    def list_sessions(
        self,
        *,
        workspace_id: str,
        page: int = 1,
        page_size: int = 25,
        status: Optional[str] = None,
        q: Optional[str] = None,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        page_val = max(1, int(page or 1))
        size_val = min(200, max(1, int(page_size or 25)))
        offset = (page_val - 1) * size_val

        where = ["s.workspace_id = :workspace_id"]
        params: Dict[str, Any] = {
            "workspace_id": ws,
            "limit": size_val,
            "offset": offset,
        }

        if status is not None and str(status).strip() != "":
            status_norm = str(status).strip().lower()
            where.append("LOWER(s.status) = :status")
            params["status"] = status_norm

        if q is not None and str(q).strip() != "":
            token = f"%{str(q).strip().lower()}%"
            where.append(
                "(LOWER(COALESCE(s.uploaded_filename, '')) LIKE :q "
                "OR LOWER(COALESCE(s.created_by, '')) LIKE :q)"
            )
            params["q"] = token

        where_sql = " AND ".join(where)

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              s.id,
              s.workspace_id,
              s.uploaded_filename,
              s.file_type,
              s.created_by,
              s.status,
              s.sheet_count,
              s.source_record_count,
              s.analysis_started_at,
              s.analysis_completed_at,
              s.created_at,
              s.updated_at,
              (
                SELECT COUNT(*)
                FROM forge_match_result r
                WHERE r.session_id = s.id
              ) AS result_count,
              (
                SELECT COUNT(*)
                FROM forge_match_result r
                WHERE r.session_id = s.id
                  AND r.status = 'accepted'
              ) AS accepted_count,
              (
                SELECT COUNT(*)
                FROM forge_match_result r
                WHERE r.session_id = s.id
                  AND r.status = 'manually_mapped'
              ) AS manually_mapped_count
            FROM forge_match_session s
            WHERE {where_sql}
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

        total_rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM forge_match_session s
            WHERE {where_sql}
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        total = int((total_rows[0] or {}).get("total") or 0) if total_rows else 0

        return {
            "rows": [self._json_safe_row(dict(row)) for row in rows],
            "total": total,
            "page": page_val,
            "page_size": size_val,
        }

    def upload_file(
        self,
        *,
        workspace_id: str,
        created_by: str,
        filename: str,
        file_bytes: bytes,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        user = _required_text(created_by, "created_by")
        upload_name = _required_text(filename, "filename")
        if not file_bytes:
            raise ForgeError("file is empty", status_code=400)

        parsed = self._parser.parse(file_bytes=file_bytes, filename=upload_name)
        records = self._extractor.extract(workbook=parsed)
        if not records:
            raise ForgeError("No source fields detected in uploaded file", status_code=400)

        session_id = str(uuid.uuid4())
        now = datetime.now()

        with self._sql.transaction() as tx:
            tx.execute_insert(
                """
                INSERT INTO forge_match_session (
                  id,
                  workspace_id,
                  uploaded_filename,
                  file_type,
                  created_by,
                  status,
                  sheet_count,
                  source_record_count,
                  summary_json,
                  created_at,
                  updated_at
                ) VALUES (
                  :id,
                  :workspace_id,
                  :uploaded_filename,
                  :file_type,
                  :created_by,
                  'uploaded',
                  :sheet_count,
                  :source_record_count,
                  :summary_json,
                  :created_at,
                  :updated_at
                )
                """,
                {
                    "id": session_id,
                    "workspace_id": ws,
                    "uploaded_filename": upload_name,
                    "file_type": parsed.file_type,
                    "created_by": user,
                    "sheet_count": len(parsed.sheets),
                    "source_record_count": len(records),
                    "summary_json": _json_dumps(
                        {
                            "sheet_names": [sheet.sheet_name for sheet in parsed.sheets],
                            "detected_count": len(records),
                        }
                    ),
                    "created_at": now,
                    "updated_at": now,
                },
            )

            for record in records:
                tx.execute_insert(
                    """
                    INSERT INTO forge_match_source_record (
                      session_id,
                      row_id,
                      sheet_name,
                      `row_number`,
                      source_field_name,
                      source_description,
                      source_type,
                      source_object_name,
                      sample_value,
                      category,
                      normalized_search_text,
                      raw_row_json
                    ) VALUES (
                      :session_id,
                      :row_id,
                      :sheet_name,
                      :row_number,
                      :source_field_name,
                      :source_description,
                      :source_type,
                      :source_object_name,
                      :sample_value,
                      :category,
                      :normalized_search_text,
                      :raw_row_json
                    )
                    """,
                    {
                        "session_id": session_id,
                        "row_id": record.row_id,
                        "sheet_name": record.sheet_name,
                        "row_number": record.row_number,
                        "source_field_name": record.source_field_name,
                        "source_description": record.source_description,
                        "source_type": record.source_type,
                        "source_object_name": record.source_object_name,
                        "sample_value": record.sample_value,
                        "category": record.category,
                        "normalized_search_text": record.normalized_search_text,
                        "raw_row_json": _json_dumps(record.raw_row),
                    },
                )

        return {
            "session_id": session_id,
            "workspace_id": ws,
            "uploaded_filename": upload_name,
            "file_type": parsed.file_type,
            "status": "uploaded",
            "sheet_count": len(parsed.sheets),
            "source_record_count": len(records),
            "source_preview": [self._source_record_to_dict(row) for row in records[:25]],
        }

    def analyze_session(
        self,
        *,
        workspace_id: str,
        session_id: str,
        vertical_norm: Optional[str] = None,
        domain_id: Optional[int] = None,
        top_n: int = 8,
        force: bool = False,
        llm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self.run_analyze_job(
            workspace_id=workspace_id,
            session_id=session_id,
            vertical_norm=vertical_norm,
            domain_id=domain_id,
            top_n=top_n,
            force=force,
            job_id=None,
            llm_id=llm_id,
        )

    def start_analyze_session_job(
        self,
        *,
        workspace_id: str,
        session_id: str,
        top_n: int = 8,
        domain_id: Optional[int] = None,
        vertical_norm: Optional[str] = None,
        force: bool = False,
        llm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        session = self._get_session_row(workspace_id=ws, session_id=sid)

        status = str(session.get("status") or "").strip().lower()
        existing_job_id = _to_text_or_none(session.get("analysis_job_id"))
        if status in {"queued", "analyzing"} and existing_job_id:
            return {
                "job_id": existing_job_id,
                "session_id": sid,
                "workspace_id": ws,
                "status": status,
                "message": "Analyze run already in progress",
            }

        job_id = str(uuid.uuid4())
        source_total = int(session.get("source_record_count") or 0)
        self._update_session_progress(
            session_id=sid,
            status="queued",
            job_id=job_id,
            source_total=source_total,
            source_done=0,
            source_skipped=0,
            source_failed=0,
            current_phase="queued",
            current_source_row_id=None,
            analysis_error=None,
            cancel_requested=False,
            started_at=None,
            completed_at=None,
        )

        return {
            "job_id": job_id,
            "session_id": sid,
            "workspace_id": ws,
            "status": "queued",
            "source_total": source_total,
            "message": "ForgeMatch analysis queued",
            "top_n": max(3, int(top_n or 8)),
            "domain_id": int(domain_id) if domain_id is not None else None,
            "vertical_norm": _to_text_or_none(vertical_norm),
            "force": bool(force),
            "llm_id": int(llm_id) if llm_id is not None else None,
        }

    def run_analyze_job(
        self,
        *,
        workspace_id: str,
        session_id: str,
        vertical_norm: Optional[str] = None,
        domain_id: Optional[int] = None,
        top_n: int = 8,
        force: bool = False,
        job_id: Optional[str] = None,
        llm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        context = PipelineContext(
            pipeline_name="forge_match_session_pipeline",
            trace_id=f"forge_match_session:{uuid.uuid4().hex}",
            workspace_id=ws,
            user_id=None,
            vertical_norm=str(vertical_norm or "generic"),
            request={
                "session_id": sid,
                "job_id": _to_text_or_none(job_id),
                "top_n": max(3, int(top_n or 8)),
                "vertical_norm": _to_text_or_none(vertical_norm),
                "domain_id": int(domain_id) if domain_id is not None else None,
                "preferred_domain_id": int(domain_id) if domain_id is not None else None,
                "force": bool(force),
                "llm_id": int(llm_id) if llm_id is not None else None,
            },
        )

        try:
            result = self._run_session_pipeline(context)
            return dict(result.payload)
        except Exception as exc:
            logger.exception("ForgeMatch analyze session failed session_id=%s", sid)
            progress = context.metadata.get("session_progress") or {}
            analyzed = int(progress.get("analyzed_count") or 0)
            skipped = int(progress.get("skipped_count") or 0)
            failed = int(progress.get("failed_count") or 0)
            source_total = int(progress.get("source_total") or 0)
            self._update_session_progress(
                session_id=sid,
                status="failed",
                job_id=job_id,
                source_total=source_total,
                source_done=analyzed,
                source_skipped=skipped,
                source_failed=failed + 1,
                current_phase="failed",
                current_source_row_id=None,
                analysis_error=str(exc)[:2000],
                completed_at=datetime.now(timezone.utc),
            )
            raise

    def _run_session_pipeline(self, context: PipelineContext) -> ForgeMatchSessionResultArtifact:
        definition = build_forge_match_session_pipeline_definition(
            preparation_adapter=ForgeMatchSessionPreparationAdapter(
                load_session=self._get_session_row,
                load_source_rows=self._load_source_rows,
                existing_results_by_source=self._existing_results_by_source,
                clear_results=self._clear_session_results,
                update_progress=self._update_session_progress,
            ),
            execution_adapter=ForgeMatchSessionExecutionAdapter(
                is_cancel_requested=self._is_cancel_requested,
                update_progress=self._update_session_progress,
                run_row_pipeline=self._run_row_pipeline,
                persist_failure_result=self._upsert_mapping_result,
            ),
            finalization_adapter=ForgeMatchSessionFinalizationAdapter(
                load_mapping_rows=self._load_mapping_rows,
                build_summary=self._build_summary,
                update_progress=self._update_session_progress,
            ),
        )
        context = self._pipeline_executor.execute(definition, context)
        trace_snapshot = serialize_pipeline_context(context)
        work = context.get_artifact("session_work", node_name="forge_match_session_pipeline")
        result = context.get_artifact("session_result", node_name="forge_match_session_pipeline")
        if not isinstance(result, ForgeMatchSessionResultArtifact):
            raise TypeError("forge_match_session_pipeline expected ForgeMatchSessionResultArtifact.")
        if hasattr(work, "session") and isinstance(getattr(work, "session"), dict):
            summary_json = self._persist_session_analysis_trace(
                session_id=str(context.request.get("session_id") or ""),
                current_summary=getattr(work, "session").get("summary_json"),
                trace_snapshot=trace_snapshot,
            )
            payload_session = result.payload.get("session")
            if isinstance(payload_session, dict):
                payload_session["summary_json"] = summary_json
        return result

    def _run_row_pipeline(
        self,
        *,
        workspace_id: str,
        session_id: str,
        source_record_id: int,
        source_record: SourceFieldRecord,
        top_n: int,
        vertical_norm: Optional[str],
        domain_id: Optional[int],
        llm_id: Optional[int],
    ) -> tuple[MatchOutcomeArtifact, dict[str, Any], PersistenceArtifact]:
        context = PipelineContext(
            pipeline_name="forge_match_row_pipeline",
            trace_id=f"forge_match_row:{uuid.uuid4().hex}",
            workspace_id=workspace_id,
            user_id=None,
            vertical_norm=str(vertical_norm or "generic"),
            request={
                "prompt": str(
                    source_record.normalized_search_text
                    or source_record.source_description
                    or source_record.source_field_name
                    or ""
                ).strip(),
                "session_id": session_id,
                "source_record_id": int(source_record_id),
                "source_record": source_record,
                "top_n": int(top_n),
                "domain_id": int(domain_id) if domain_id is not None else None,
                "preferred_domain_id": int(domain_id) if domain_id is not None else None,
                "llm_id": int(llm_id) if llm_id is not None else None,
            },
        )
        definition = build_forge_match_row_pipeline_definition(
            candidate_pipeline_factory=lambda _ctx: self._build_candidate_pipeline_definition(),
            ranking_adapter=ForgeMatchLLMDecisionAdapter(ranker=self._ranker),
            confidence_adapter=ForgeMatchConfidenceAdapter(scorer=self._confidence),
            persistence_adapter=ForgeMatchPersistenceAdapter(persist_result=self._upsert_mapping_result),
        )
        context = self._pipeline_executor.execute(definition, context)

        outcome = context.get_artifact("match_outcome", node_name="forge_match_row_pipeline")
        persistence = context.get_artifact("persistence_result", node_name="forge_match_row_pipeline")
        if not isinstance(outcome, MatchOutcomeArtifact):
            raise TypeError("forge_match_row_pipeline expected MatchOutcomeArtifact.")
        if not isinstance(persistence, PersistenceArtifact):
            raise TypeError("forge_match_row_pipeline expected PersistenceArtifact.")

        return outcome, serialize_pipeline_context(context), persistence

    def _build_candidate_pipeline_definition(self):
        retrieval_adapter = self._candidate_retrieval_adapter()
        capability_adapter = getattr(self._retriever, "_capability_adapter", None)
        policy_adapter = getattr(self._retriever, "_policy_adapter", None)
        return build_forge_match_candidate_pipeline_definition(
            retrieval_adapter=retrieval_adapter,
            capability_adapter=capability_adapter,
            policy_adapter=policy_adapter,
        )

    def _candidate_retrieval_adapter(self):
        if isinstance(self._retriever, ForgeMatchCandidateRetriever):
            return ForgeMatchColumnRetrievalAdapter(owner=self._retriever)
        return ExistingRetrieverCandidateAdapter(retriever=self._retriever)

    def get_analysis_status(self, *, workspace_id: str, job_id: str) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        jid = _required_text(job_id, "job_id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM forge_match_session
            WHERE workspace_id = :workspace_id
              AND (analysis_job_id = :job_id OR id = :job_id)
            ORDER BY CASE WHEN analysis_job_id = :job_id THEN 0 ELSE 1 END
            LIMIT 1
            """,
            {"workspace_id": ws, "job_id": jid},
        )
        if not rows:
            raise ForgeError("ForgeMatch run not found", status_code=404)
        return self._serialize_analysis_status(self._json_safe_row(dict(rows[0])))

    def cancel_analysis_job(self, *, workspace_id: str, job_id: str) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        jid = _required_text(job_id, "job_id")
        status = self.get_analysis_status(workspace_id=ws, job_id=jid)
        current_status = str(status.get("status") or "").lower()
        if current_status in _TERMINAL_SESSION_STATUSES:
            return {
                "job_id": status.get("job_id"),
                "session_id": status.get("session_id"),
                "canceled": False,
                "status": current_status,
                "message": "Run already in terminal status",
            }

        sid = str(status.get("session_id") or "")
        self._update_session_progress(
            session_id=sid,
            status="canceled",
            job_id=str(status.get("job_id") or jid),
            source_total=int(status.get("source_total") or 0),
            source_done=int(status.get("source_done") or 0),
            source_skipped=int(status.get("source_skipped") or 0),
            source_failed=int(status.get("source_failed") or 0),
            current_phase="canceled",
            current_source_row_id=status.get("current_source_row_id"),
            analysis_error="Canceled by operator",
            cancel_requested=True,
            completed_at=datetime.now(timezone.utc),
        )
        refreshed = self.get_analysis_status(workspace_id=ws, job_id=jid)
        return {
            "job_id": refreshed.get("job_id"),
            "session_id": refreshed.get("session_id"),
            "canceled": True,
            "status": str(refreshed.get("status") or "").lower(),
            "message": "Cancellation requested",
        }

    def list_analysis_history(self, *, workspace_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        ws = _required_text(workspace_id, "workspace_id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM forge_match_session
            WHERE workspace_id = :workspace_id
              AND analysis_started_at IS NOT NULL
            ORDER BY analysis_started_at DESC
            LIMIT :limit
            """,
            {"workspace_id": ws, "limit": max(1, min(200, int(limit or 20)))},
        )
        return [self._serialize_analysis_status(self._json_safe_row(dict(row))) for row in rows]

    def mark_enqueue_failed(
        self,
        *,
        session_id: str,
        job_id: str,
        source_total: int,
        error_message: str,
    ) -> None:
        self._update_session_progress(
            session_id=_required_text(session_id, "session_id"),
            status="failed",
            job_id=_required_text(job_id, "job_id"),
            source_total=int(source_total or 0),
            source_done=0,
            source_skipped=0,
            source_failed=1,
            current_phase="failed",
            current_source_row_id=None,
            analysis_error=str(error_message or "Failed to enqueue ForgeMatch analysis task")[:2000],
            completed_at=None,
        )

    def get_session(
        self,
        *,
        workspace_id: str,
        session_id: str,
        source_limit: int = 200,
        source_offset: int = 0,
        mapping_limit: int = 500,
        mapping_offset: int = 0,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")

        session = self._get_session_row(workspace_id=ws, session_id=sid)
        source_records = self._load_source_rows(
            session_id=sid,
            limit=max(1, min(1000, int(source_limit))),
            offset=max(0, int(source_offset)),
        )
        mappings = self._load_mapping_rows(
            workspace_id=ws,
            session_id=sid,
            limit=max(1, min(2000, int(mapping_limit))),
            offset=max(0, int(mapping_offset)),
        )
        summary = self._build_summary(mappings)

        return {
            "session": session,
            "source_records": [self._source_row_to_response(row) for row in source_records],
            "mappings": mappings,
            "summary": summary,
        }

    def delete_session(self, *, workspace_id: str, session_id: str) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        session = self._get_session_row(workspace_id=ws, session_id=sid)

        status = str(session.get("status") or "").strip().lower()
        if status in {"queued", "analyzing"}:
            raise ForgeError("Cannot delete a ForgeMatch session while analysis is in progress", status_code=409)

        self._sql.execute_write(
            """
            DELETE FROM forge_match_session
            WHERE id = :session_id
              AND workspace_id = :workspace_id
            """,
            {"session_id": sid, "workspace_id": ws},
        )

        return {
            "session_id": sid,
            "workspace_id": ws,
            "deleted": True,
            "message": "ForgeMatch session deleted",
        }

    def patch_mappings(
        self,
        *,
        workspace_id: str,
        session_id: str,
        reviewer_user_id: str,
        updates: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        reviewer = _required_text(reviewer_user_id, "reviewer_user_id")
        self._get_session_row(workspace_id=ws, session_id=sid)

        changed: list[dict[str, Any]] = []

        for update in updates:
            mapping_id = _required_text(update.get("mapping_id"), "mapping_id")
            row = self._get_mapping_row_by_id(workspace_id=ws, session_id=sid, mapping_id=mapping_id)
            if not row:
                raise ForgeError(f"mapping_id not found: {mapping_id}", status_code=404)

            action = _to_text_or_none(update.get("action"))
            status = update.get("status")
            manual_col = update.get("manually_selected_workspace_column_id")
            notes = update.get("review_notes")

            if action:
                action_norm = action.lower()
                if action_norm == "accept":
                    status = "accepted"
                elif action_norm == "reject":
                    status = "rejected"
                elif action_norm == "needs_review":
                    status = "needs_review"
                elif action_norm == "remap":
                    status = "manually_mapped"
                elif action_norm == "edit_notes":
                    pass
                else:
                    raise ForgeError(f"Invalid action: {action}", status_code=400)

            if status is not None:
                status = str(status).strip().lower()
                if status not in _ALLOWED_RESULT_STATUSES:
                    raise ForgeError(f"Invalid status: {status}", status_code=400)

            manual_col_id = None
            if manual_col is not None:
                try:
                    manual_col_id = int(manual_col)
                except Exception as exc:
                    raise ForgeError("manually_selected_workspace_column_id must be integer", status_code=400) from exc
                if manual_col_id <= 0:
                    raise ForgeError("manually_selected_workspace_column_id must be > 0", status_code=400)
                self._assert_workspace_column(workspace_id=ws, workspace_column_id=manual_col_id)
                if status is None:
                    status = "manually_mapped"
            elif action and action.lower() == "remap":
                raise ForgeError("remap action requires manually_selected_workspace_column_id", status_code=400)

            if status is None and notes is None and manual_col is None:
                continue

            params: Dict[str, Any] = {
                "id": mapping_id,
                "session_id": sid,
                "reviewer_user_id": reviewer,
            }
            set_parts = ["reviewer_user_id = :reviewer_user_id", "reviewed_at = CURRENT_TIMESTAMP", "updated_at = CURRENT_TIMESTAMP"]

            if status is not None:
                set_parts.append("status = :status")
                params["status"] = status
            if manual_col is not None:
                set_parts.append("manually_selected_workspace_column_id = :manually_selected_workspace_column_id")
                params["manually_selected_workspace_column_id"] = manual_col_id
            if notes is not None:
                set_parts.append("review_notes = :review_notes")
                params["review_notes"] = str(notes)

            self._sql.execute_write(
                f"""
                UPDATE forge_match_result
                SET {', '.join(set_parts)}
                WHERE id = :id
                  AND session_id = :session_id
                """,
                params,
            )
            changed.append({"mapping_id": mapping_id, "status": status, "manual_column_id": manual_col_id})

        return {
            "session_id": sid,
            "workspace_id": ws,
            "updated": len(changed),
            "rows": changed,
        }

    def export_session(
        self,
        *,
        workspace_id: str,
        session_id: str,
        export_format: str,
    ) -> tuple[bytes, str, str]:
        return self._exporter.export_session(
            workspace_id=workspace_id,
            session_id=session_id,
            export_format=export_format,
        )

    def create_view_draft(self, *, workspace_id: str, session_id: str, name: Optional[str] = None) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        self._get_session_row(workspace_id=ws, session_id=sid)
        accepted = self._accepted_columns(workspace_id=ws, session_id=sid)
        artifact_id = f"fmdv_{uuid.uuid4().hex[:16]}"
        draft_name = (name or f"ForgeMatch View Draft {sid[:8]}").strip()
        sql_preview = self._build_view_draft_sql_preview(
            workspace_id=ws,
            session_id=sid,
            draft_name=draft_name,
            accepted_columns=accepted,
        )
        return {
            "artifact_id": artifact_id,
            "workspace_id": ws,
            "session_id": sid,
            "name": draft_name,
            "accepted_column_count": len(accepted),
            "columns": accepted,
            "status": "draft_created",
            "note": (
                "SQL preview included when the accepted mappings resolve to an executable table/join plan. "
                "No SQL view was created."
            ),
            **sql_preview,
        }

    def execute_view_draft_sql(
        self,
        *,
        workspace_id: str,
        session_id: str,
        sql: str,
        catalog_name: Optional[str] = None,
        schema_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        self._get_session_row(workspace_id=ws, session_id=sid)

        statement_type = _classify_draft_sql_statement(sql)
        catalog = _normalize_optional_sql_identifier(catalog_name, field="catalog_name")
        schema = _normalize_optional_sql_identifier(schema_name, field="schema_name")
        effective_sql = _prepare_draft_execution_sql(
            sql,
            catalog_name=catalog,
            schema_name=schema,
        )

        ctx = WorkspaceSqlContextBuilder().build(ws)
        try:
            result = ctx.sql_exec.submit_statement(
                effective_sql,
                qf_result_fmt="ARROW_STREAM",
            )
        except ForgeError:
            raise
        except Exception as exc:
            raise ForgeError(f"Draft SQL execution failed: {str(exc)}", status_code=500) from exc

        status_payload = dict(result.get("status") or {})
        status = str(status_payload.get("state") or "SUCCEEDED").upper()
        rows = result.get("rows") if statement_type == "select" else []
        if not isinstance(rows, list):
            rows = []

        return {
            "workspace_id": ws,
            "session_id": sid,
            "statement_type": statement_type,
            "status": status,
            "catalog_name": catalog,
            "schema_name": schema,
            "effective_sql": effective_sql,
            "row_count": len(rows),
            "rows": rows[:200],
            "message": (
                "SQL executed successfully."
                if statement_type == "select"
                else "View statement executed successfully."
            ),
        }

    def create_domain_draft(self, *, workspace_id: str, session_id: str, name: Optional[str] = None) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        accepted = self._accepted_columns(workspace_id=ws, session_id=sid)
        artifact_id = f"fmdd_{uuid.uuid4().hex[:16]}"
        return {
            "artifact_id": artifact_id,
            "workspace_id": ws,
            "session_id": sid,
            "name": (name or f"ForgeMatch Domain Draft {sid[:8]}").strip(),
            "accepted_column_count": len(accepted),
            "columns": accepted,
            "status": "draft_created",
            "note": "V1 draft artifact only; no production domain was created.",
        }

    def _upsert_mapping_result(
        self,
        *,
        session_id: str,
        source_record_id: int,
        selected: Optional[Dict[str, Any]],
        alternates: Sequence[Dict[str, Any]],
        candidates: Sequence[Dict[str, Any]],
        llm_rank: Dict[str, Any],
        confidence: Dict[str, Any],
    ) -> None:
        mapping_id = str(uuid.uuid4())
        self._sql.execute_insert(
            """
            INSERT INTO forge_match_result (
              id,
              session_id,
              source_record_id,
              best_match_workspace_column_id,
              alternate_workspace_column_ids,
              retrieved_candidates_json,
              llm_response_json,
              match_decision,
              reason_codes_json,
              explanation,
              ambiguity_note,
              llm_confidence,
              confidence_score,
              confidence_band,
              status
            ) VALUES (
              :id,
              :session_id,
              :source_record_id,
              :best_match_workspace_column_id,
              :alternate_workspace_column_ids,
              :retrieved_candidates_json,
              :llm_response_json,
              :match_decision,
              :reason_codes_json,
              :explanation,
              :ambiguity_note,
              :llm_confidence,
              :confidence_score,
              :confidence_band,
              :status
            )
            ON DUPLICATE KEY UPDATE
              best_match_workspace_column_id = VALUES(best_match_workspace_column_id),
              alternate_workspace_column_ids = VALUES(alternate_workspace_column_ids),
              retrieved_candidates_json = VALUES(retrieved_candidates_json),
              llm_response_json = VALUES(llm_response_json),
              match_decision = VALUES(match_decision),
              reason_codes_json = VALUES(reason_codes_json),
              explanation = VALUES(explanation),
              ambiguity_note = VALUES(ambiguity_note),
              llm_confidence = VALUES(llm_confidence),
              confidence_score = VALUES(confidence_score),
              confidence_band = VALUES(confidence_band),
              status = VALUES(status),
              updated_at = CURRENT_TIMESTAMP
            """,
            {
                "id": mapping_id,
                "session_id": session_id,
                "source_record_id": int(source_record_id),
                "best_match_workspace_column_id": selected.get("column_id") if selected else None,
                "alternate_workspace_column_ids": _json_dumps([row.get("column_id") for row in alternates]),
                "retrieved_candidates_json": _json_dumps(list(candidates)),
                "llm_response_json": _json_dumps(llm_rank),
                "match_decision": str(llm_rank.get("match_decision") or "no_confident_match"),
                "reason_codes_json": _json_dumps(llm_rank.get("reason_codes") or []),
                "explanation": str(llm_rank.get("explanation") or "").strip(),
                "ambiguity_note": _to_text_or_none(llm_rank.get("ambiguity_note")),
                "llm_confidence": float(llm_rank.get("llm_confidence") or 0.0),
                "confidence_score": int(confidence.get("confidence_score") or 0),
                "confidence_band": str(confidence.get("confidence_band") or "low"),
                "status": "suggested",
            },
        )

    def _is_cancel_requested(self, *, session_id: str) -> bool:
        try:
            rows = self._sql.execute_query_mappings(
                """
                SELECT cancel_requested
                FROM forge_match_session
                WHERE id = :session_id
                LIMIT 1
                """,
                {"session_id": session_id},
            )
        except Exception:
            return False
        if not rows:
            return False
        return bool(int(rows[0].get("cancel_requested") or 0))

    def _update_session_progress(
        self,
        *,
        session_id: str,
        status: str,
        job_id: Optional[str],
        source_total: int,
        source_done: int,
        source_skipped: int,
        source_failed: int,
        current_phase: Optional[str],
        current_source_row_id: Optional[str],
        analysis_error: Optional[str] = None,
        cancel_requested: Optional[bool] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> None:
        params = {
            "session_id": session_id,
            "status": status,
            "analysis_job_id": job_id,
            "source_total": int(source_total or 0),
            "source_done": int(source_done or 0),
            "source_skipped": int(source_skipped or 0),
            "source_failed": int(source_failed or 0),
            "current_phase": _to_text_or_none(current_phase),
            "current_source_row_id": _to_text_or_none(current_source_row_id),
            "analysis_error": _to_text_or_none(analysis_error),
            "cancel_requested": None if cancel_requested is None else (1 if cancel_requested else 0),
            "started_at": started_at,
            "completed_at": completed_at,
            "last_heartbeat_at": datetime.now(timezone.utc),
        }

        advanced_sql = """
            UPDATE forge_match_session
            SET status = :status,
                analysis_job_id = COALESCE(:analysis_job_id, analysis_job_id),
                analyzed_count = :source_done,
                skipped_count = :source_skipped,
                failed_count = :source_failed,
                current_phase = :current_phase,
                current_source_row_id = :current_source_row_id,
                analysis_error = COALESCE(:analysis_error, analysis_error),
                cancel_requested = COALESCE(:cancel_requested, cancel_requested),
                analysis_started_at = COALESCE(:started_at, analysis_started_at),
                analysis_completed_at = :completed_at,
                last_heartbeat_at = :last_heartbeat_at,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :session_id
        """

        fallback_sql = """
            UPDATE forge_match_session
            SET status = :status,
                analysis_started_at = COALESCE(:started_at, analysis_started_at),
                analysis_completed_at = :completed_at,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :session_id
        """

        if self._extended_progress_columns_supported:
            try:
                self._sql.execute_write(advanced_sql, params)
                return
            except Exception:
                self._extended_progress_columns_supported = False
                logger.warning(
                    "forge_match_session extended progress columns missing; using fallback updates"
                )

        self._sql.execute_write(fallback_sql, params)

    @staticmethod
    def _serialize_analysis_status(row: Dict[str, Any]) -> Dict[str, Any]:
        source_total = int(row.get("source_record_count") or 0)
        source_done = int(row.get("analyzed_count") or 0)
        source_skipped = int(row.get("skipped_count") or 0)
        source_failed = int(row.get("failed_count") or 0)
        processed = source_done + source_skipped + source_failed
        progress_pct = 0.0
        if source_total > 0:
            progress_pct = max(0.0, min(100.0, round((processed / source_total) * 100.0, 2)))

        return {
            "id": row.get("analysis_job_id") or row.get("id"),
            "job_id": row.get("analysis_job_id") or row.get("id"),
            "session_id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "uploaded_filename": row.get("uploaded_filename"),
            "status": str(row.get("status") or "").lower(),
            "current_phase": _to_text_or_none(row.get("current_phase")),
            "current_source_row_id": _to_text_or_none(row.get("current_source_row_id")),
            "source_total": source_total,
            "source_done": source_done,
            "source_skipped": source_skipped,
            "source_failed": source_failed,
            "progress_pct": progress_pct,
            "analysis_error": _to_text_or_none(row.get("analysis_error")),
            "cancel_requested": bool(int(row.get("cancel_requested") or 0)),
            "started_at": row.get("analysis_started_at"),
            "completed_at": row.get("analysis_completed_at"),
            "last_heartbeat_at": row.get("last_heartbeat_at"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def _accepted_columns(self, *, workspace_id: str, session_id: str) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              fr.id AS mapping_id,
              fsr.sheet_name,
              fsr.`row_number`,
              fsr.source_field_name,
              COALESCE(fr.manually_selected_workspace_column_id, fr.best_match_workspace_column_id) AS selected_workspace_column_id,
              wc.workspace_table_id,
              wc.column_name,
              wt.table_name,
              wt.full_name
            FROM forge_match_result fr
            JOIN forge_match_source_record fsr ON fsr.id = fr.source_record_id
            JOIN forge_match_session fms ON fms.id = fr.session_id
            LEFT JOIN workspace_column wc
              ON wc.id = COALESCE(fr.manually_selected_workspace_column_id, fr.best_match_workspace_column_id)
            LEFT JOIN workspace_table wt ON wt.id = wc.workspace_table_id
            WHERE fr.session_id = :session_id
              AND fms.workspace_id = :workspace_id
              AND fr.status IN ('accepted', 'manually_mapped')
            ORDER BY fsr.sheet_name ASC, fsr.`row_number` ASC
            """,
            {"workspace_id": workspace_id, "session_id": session_id},
        )
        return [
            {
                "mapping_id": row.get("mapping_id"),
                "sheet_name": row.get("sheet_name"),
                "row_number": row.get("row_number"),
                "source_field_name": row.get("source_field_name"),
                "selected_workspace_column_id": row.get("selected_workspace_column_id"),
                "workspace_table_id": row.get("workspace_table_id"),
                "column_name": row.get("column_name"),
                "table_name": row.get("table_name"),
                "full_name": row.get("full_name"),
            }
            for row in rows
            if row.get("selected_workspace_column_id")
        ]

    def _build_view_draft_sql_preview(
        self,
        *,
        workspace_id: str,
        session_id: str,
        draft_name: str,
        accepted_columns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        view_name = _normalize_sql_identifier(draft_name, fallback=f"forge_match_view_{session_id[:8]}")
        involved_tables = self._collect_involved_tables(accepted_columns)
        suspected_keys_by_table = self._load_suspected_table_keys(
            workspace_id=workspace_id,
            involved_tables=involved_tables,
        )
        if not accepted_columns:
            return {
                "view_name": view_name,
                "base_table_name": None,
                "is_executable": False,
                "blocking_reason": "No accepted mappings are available for this session.",
                "select_sql": None,
                "create_view_sql": None,
                "editable_sql": None,
                "join_domain_id": None,
                "join_domain_name": None,
                "involved_tables": [],
            }

        table_ids = sorted(
            {
                int(row.get("workspace_table_id") or 0)
                for row in accepted_columns
                if int(row.get("workspace_table_id") or 0) > 0
            }
        )
        if not table_ids:
            return {
                "view_name": view_name,
                "base_table_name": None,
                "is_executable": False,
                "blocking_reason": "Accepted mappings do not resolve to workspace tables.",
                "select_sql": None,
                "create_view_sql": None,
                "editable_sql": None,
                "join_domain_id": None,
                "join_domain_name": None,
                "involved_tables": involved_tables,
            }

        select_sql = None
        base_table_name = None
        join_domain_id = None
        join_domain_name = None
        blocking_reason = None

        if len(table_ids) == 1:
            base_table_name = str(accepted_columns[0].get("full_name") or "").strip() or None
            if not base_table_name:
                blocking_reason = "Accepted mappings do not have a resolvable base table name."
            else:
                table_alias = _build_table_alias_map_for_rows(accepted_columns).get(table_ids[0], "src")
                select_sql = self._compile_single_table_select_sql(
                    full_name=base_table_name,
                    table_alias=table_alias,
                    accepted_columns=accepted_columns,
                )
        else:
            join_resolution = self._resolve_joinable_domain_for_tables(workspace_id=workspace_id, workspace_table_ids=table_ids)
            if join_resolution is None:
                blocking_reason = (
                    "Accepted mappings span multiple tables with no resolvable shared domain join path."
                )
            else:
                join_domain_id = int(join_resolution["domain_id"])
                join_domain_name = str(join_resolution["domain_name"] or "").strip() or None
                base_table_name = str(join_resolution["plan"].primary.full_name)
                select_sql = self._compile_multi_table_select_sql(
                    plan=join_resolution["plan"],
                    resolver=join_resolution["resolver"],
                    required_table_ids=table_ids,
                    accepted_columns=accepted_columns,
                )

        create_view_sql = None
        comment_block = self._build_view_draft_comment_block(
            involved_tables=involved_tables,
            suspected_keys_by_table=suspected_keys_by_table,
            blocking_reason=blocking_reason,
            require_join_note=len(involved_tables) > 1 and not select_sql,
        )
        if select_sql:
            create_view_sql = f"{comment_block}CREATE VIEW {_quote_identifier(view_name)} AS\n{select_sql};"

        editable_sql = create_view_sql
        if editable_sql is None:
            editable_sql = self._compile_unresolved_join_sql_template(
                view_name=view_name,
                accepted_columns=accepted_columns,
                involved_tables=involved_tables,
                comment_block=comment_block,
            )

        return {
            "view_name": view_name,
            "base_table_name": base_table_name,
            "is_executable": bool(create_view_sql),
            "blocking_reason": blocking_reason,
            "select_sql": select_sql,
            "create_view_sql": create_view_sql,
            "editable_sql": editable_sql,
            "join_domain_id": join_domain_id,
            "join_domain_name": join_domain_name,
            "involved_tables": involved_tables,
        }

    @staticmethod
    def _collect_involved_tables(accepted_columns: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set[int] = set()
        tables: List[Dict[str, Any]] = []
        for row in accepted_columns:
            workspace_table_id = int(row.get("workspace_table_id") or 0)
            if workspace_table_id <= 0 or workspace_table_id in seen:
                continue
            seen.add(workspace_table_id)
            tables.append(
                {
                    "workspace_table_id": workspace_table_id,
                    "table_name": row.get("table_name"),
                    "full_name": row.get("full_name"),
                }
            )
        return tables

    def _load_suspected_table_keys(
        self,
        *,
        workspace_id: str,
        involved_tables: Sequence[Dict[str, Any]],
    ) -> Dict[int, List[str]]:
        table_ids = sorted(
            {
                int(row.get("workspace_table_id") or 0)
                for row in involved_tables
                if int(row.get("workspace_table_id") or 0) > 0
            }
        )
        if not table_ids:
            return {}

        placeholders = ", ".join(f":wt_{idx}" for idx, _ in enumerate(table_ids))
        params: Dict[str, Any] = {"workspace_id": workspace_id}
        for idx, workspace_table_id in enumerate(table_ids):
            params[f"wt_{idx}"] = int(workspace_table_id)

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              wc.workspace_table_id,
              wc.column_name,
              wc.description
            FROM workspace_column wc
            JOIN workspace_table wt ON wt.id = wc.workspace_table_id
            WHERE wt.workspace_id = :workspace_id
              AND wc.workspace_table_id IN ({placeholders})
            """,
            params,
        )

        scored: Dict[int, List[tuple[int, str]]] = {}
        for row in rows:
            workspace_table_id = int(row.get("workspace_table_id") or 0)
            column_name = str(row.get("column_name") or "").strip()
            if workspace_table_id <= 0 or not column_name:
                continue
            score = _score_suspected_key_column(
                column_name=column_name,
                description=row.get("description"),
            )
            if score <= 0:
                continue
            scored.setdefault(workspace_table_id, []).append((score, column_name))

        output: Dict[int, List[str]] = {}
        for workspace_table_id, candidates in scored.items():
            names: List[str] = []
            seen: set[str] = set()
            for _, column_name in sorted(candidates, key=lambda item: (-item[0], item[1])):
                if column_name in seen:
                    continue
                seen.add(column_name)
                names.append(column_name)
                if len(names) >= 4:
                    break
            if names:
                output[workspace_table_id] = names
        return output

    def _build_view_draft_comment_block(
        self,
        *,
        involved_tables: Sequence[Dict[str, Any]],
        suspected_keys_by_table: Dict[int, List[str]],
        blocking_reason: Optional[str],
        require_join_note: bool,
    ) -> str:
        comments: List[str] = []
        if blocking_reason:
            comments.append(f"-- {blocking_reason}")
        if involved_tables:
            comments.append("-- Involved tables:")
            for row in involved_tables:
                workspace_table_id = int(row.get("workspace_table_id") or 0)
                table_label = str(row.get("full_name") or row.get("table_name") or "").strip()
                if not table_label:
                    continue
                suspected_keys = suspected_keys_by_table.get(workspace_table_id) or []
                suffix = f" (suspected keys: {', '.join(suspected_keys)})" if suspected_keys else ""
                comments.append(f"-- - {table_label}{suffix}")
        if require_join_note:
            comments.append("-- Add the required JOIN clauses before running this SQL.")
        return "\n".join(comments) + ("\n\n" if comments else "")

    def _resolve_joinable_domain_for_tables(
        self,
        *,
        workspace_id: str,
        workspace_table_ids: Sequence[int],
    ) -> Optional[Dict[str, Any]]:
        if not workspace_table_ids:
            return None
        placeholders = ", ".join(f":wt_{idx}" for idx, _ in enumerate(workspace_table_ids))
        params: Dict[str, Any] = {"workspace_id": workspace_id, "required_count": len(workspace_table_ids)}
        for idx, workspace_table_id in enumerate(workspace_table_ids):
            params[f"wt_{idx}"] = int(workspace_table_id)

        candidate_rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              d.id AS domain_id,
              d.name AS domain_name,
              COUNT(DISTINCT dwt.workspace_table_id) AS matched_table_count,
              COUNT(*) AS total_table_count
            FROM domain d
            JOIN domain_workspace_table dwt
              ON dwt.domain_id = d.id
            WHERE d.workspace_id = :workspace_id
              AND d.is_active = 1
              AND dwt.workspace_table_id IN ({placeholders})
            GROUP BY d.id, d.name
            HAVING COUNT(DISTINCT dwt.workspace_table_id) = :required_count
            ORDER BY total_table_count ASC, d.id ASC
            """,
            params,
        )

        for row in candidate_rows:
            domain_id = int(row.get("domain_id") or 0)
            if domain_id <= 0:
                continue
            resolver = DomainResolver(workspace_id=workspace_id, sql=self._sql)
            try:
                plan = resolver.resolve_plan(domain_id)
                alias_by_workspace_table_id = _build_table_alias_map_for_plan(plan)
                self._compile_domain_from_clause(
                    plan=plan,
                    resolver=resolver,
                    required_table_ids=workspace_table_ids,
                    alias_by_workspace_table_id=alias_by_workspace_table_id,
                )
            except ForgeError:
                continue
            return {
                "domain_id": domain_id,
                "domain_name": row.get("domain_name"),
                "resolver": resolver,
                "plan": plan,
            }
        return None

    def _compile_single_table_select_sql(
        self,
        *,
        full_name: str,
        table_alias: str,
        accepted_columns: Sequence[Dict[str, Any]],
    ) -> str:
        alias = _quote_identifier(table_alias)
        select_lines = self._compile_select_list(
            accepted_columns=accepted_columns,
            alias_by_workspace_table_id={
                int(accepted_columns[0].get("workspace_table_id") or 0): table_alias,
            },
        )
        return (
            "SELECT\n"
            f"{select_lines}\n"
            f"FROM {_quote_fqn(full_name)} {alias}"
        )

    def _compile_multi_table_select_sql(
        self,
        *,
        plan: DomainPlan,
        resolver: DomainResolver,
        required_table_ids: Sequence[int],
        accepted_columns: Sequence[Dict[str, Any]],
    ) -> str:
        alias_by_workspace_table_id = _build_table_alias_map_for_plan(plan)
        from_clause = self._compile_domain_from_clause(
            plan=plan,
            resolver=resolver,
            required_table_ids=required_table_ids,
            alias_by_workspace_table_id=alias_by_workspace_table_id,
        )
        select_lines = self._compile_select_list(
            accepted_columns=accepted_columns,
            alias_by_workspace_table_id=alias_by_workspace_table_id,
        )
        return (
            "SELECT\n"
            f"{select_lines}\n"
            f"FROM {from_clause}"
        )

    def _compile_select_list(
        self,
        *,
        accepted_columns: Sequence[Dict[str, Any]],
        alias_by_workspace_table_id: Dict[int, str],
    ) -> str:
        seen_aliases: set[str] = set()
        lines: List[str] = []
        for row in accepted_columns:
            workspace_table_id = int(row.get("workspace_table_id") or 0)
            column_name = _required_text(row.get("column_name"), "column_name")
            table_alias = alias_by_workspace_table_id.get(workspace_table_id)
            if not table_alias:
                raise ForgeError("Accepted column table is not in the resolved SQL plan", status_code=400)
            output_alias = _normalize_sql_identifier(
                row.get("source_field_name"),
                fallback=f"column_{len(lines) + 1}",
                seen=seen_aliases,
            )
            lines.append(
                f"  {_quote_identifier(table_alias)}.{_quote_identifier(column_name)} AS {_quote_identifier(output_alias)}"
            )
        return ",\n".join(lines)

    def _compile_domain_from_clause(
        self,
        *,
        plan: DomainPlan,
        resolver: DomainResolver,
        required_table_ids: Sequence[int],
        alias_by_workspace_table_id: Dict[int, str],
    ) -> str:
        tables_by_id = {int(table.workspace_table_id): table for table in plan.tables}
        needed_edges: Dict[tuple[str, int, int], DomainPlanJoin] = {}
        for workspace_table_id in required_table_ids:
            target_id = int(workspace_table_id)
            if target_id == int(plan.primary.workspace_table_id):
                continue
            for edge in resolver.get_join_path(plan, target_id):
                key = (str(edge.join_id), int(edge.from_workspace_table_id), int(edge.to_workspace_table_id))
                needed_edges[key] = edge

        joined = {int(plan.primary.workspace_table_id)}
        primary_alias = alias_by_workspace_table_id.get(int(plan.primary.workspace_table_id))
        if not primary_alias:
            raise ForgeError("Primary table alias is missing from the SQL plan", status_code=400)
        clauses = [f"{_quote_fqn(plan.primary.full_name)} {_quote_identifier(primary_alias)}"]
        remaining_edges = sorted(
            needed_edges.values(),
            key=lambda edge: (int(getattr(edge, "sort_order", 0)), str(edge.join_id)),
        )

        while remaining_edges:
            progress = False
            deferred: List[DomainPlanJoin] = []
            for edge in remaining_edges:
                from_id = int(edge.from_workspace_table_id)
                to_id = int(edge.to_workspace_table_id)
                if from_id == to_id:
                    raise ForgeError("Join cannot reference the same table", status_code=400)
                if from_id not in tables_by_id or to_id not in tables_by_id:
                    raise ForgeError("Join references table not in domain", status_code=400)
                if from_id not in joined:
                    deferred.append(edge)
                    continue

                join_type = str(edge.join_type or "").upper()
                if join_type not in {"INNER", "LEFT", "RIGHT"}:
                    raise ForgeError(f"Invalid join_type: {join_type}", status_code=400)

                to_table = tables_by_id[to_id]
                to_alias = alias_by_workspace_table_id.get(to_id)
                if not to_alias:
                    raise ForgeError("Join table alias is missing from the SQL plan", status_code=400)
                on_sql = self._compile_join_on(edge=edge, alias_by_wt=alias_by_workspace_table_id)
                clauses.append(
                    f"{join_type} JOIN {_quote_fqn(to_table.full_name)} {_quote_identifier(to_alias)} ON {on_sql}"
                )
                joined.add(to_id)
                progress = True

            if progress:
                remaining_edges = deferred
                continue
            raise ForgeError("Join order invalid: from table not yet joined", status_code=400)

        missing = [table_id for table_id in required_table_ids if int(table_id) not in joined]
        if missing:
            raise ForgeError("Domain join plan does not cover all required tables", status_code=400)
        return "\n".join(clauses)

    def _compile_join_on(self, *, edge: DomainPlanJoin, alias_by_wt: Dict[int, str]) -> str:
        from_alias = alias_by_wt.get(int(edge.from_workspace_table_id))
        to_alias = alias_by_wt.get(int(edge.to_workspace_table_id))
        if not from_alias or not to_alias:
            raise ForgeError("Join references table not in domain", status_code=400)
        return " AND ".join(
            self._join_predicates(edge=edge, from_alias=from_alias, to_alias=to_alias)
        )

    def _join_predicates(
        self,
        *,
        edge: DomainPlanJoin,
        from_alias: str,
        to_alias: str,
    ) -> List[str]:
        spec = edge.join_spec or {}
        on_list = spec.get("on") or []
        if not isinstance(on_list, list) or not on_list:
            raise ForgeError("Join spec must include a non-empty on[] list", status_code=400)

        predicates: List[str] = []
        for item in on_list:
            if not isinstance(item, dict):
                raise ForgeError("Join spec on[] must contain objects", status_code=400)

            left = item.get("left") or {}
            right = item.get("right") or {}
            left_wt = left.get("workspaceTableId")
            right_wt = right.get("workspaceTableId")
            if left_wt is not None and int(left_wt) != int(edge.from_workspace_table_id):
                raise ForgeError("Join spec left.workspaceTableId must match from table", status_code=400)
            if right_wt is not None and int(right_wt) != int(edge.to_workspace_table_id):
                raise ForgeError("Join spec right.workspaceTableId must match to table", status_code=400)

            left_expr = self._compile_join_side(left, expected_scope="from", alias=from_alias)
            right_expr = self._compile_join_side(right, expected_scope="to", alias=to_alias)
            predicates.append(f"{left_expr} = {right_expr}")
        return predicates

    def _compile_join_side(self, side: Dict[str, Any], *, expected_scope: str, alias: str) -> str:
        expr = side.get("expr")
        if expr:
            scope, column_name, key = self._parse_join_expr(str(expr))
            if scope != expected_scope:
                raise ForgeError("Join spec expr uses wrong table scope", status_code=400)
            return f"get_json_object({_quote_identifier(alias)}.{_quote_identifier(column_name)}, '$.{key}')"

        column_name = side.get("columnName") or side.get("col")
        if not isinstance(column_name, str) or "." in column_name or not column_name.strip():
            raise ForgeError("Join spec column invalid", status_code=400)
        return f"{_quote_identifier(alias)}.{_quote_identifier(column_name)}"

    def _compile_unresolved_join_sql_template(
        self,
        *,
        view_name: str,
        accepted_columns: Sequence[Dict[str, Any]],
        involved_tables: Sequence[Dict[str, Any]],
        comment_block: str,
    ) -> str:
        table_aliases = _build_table_alias_map_for_rows(involved_tables)
        primary_table = next(
            (row for row in involved_tables if str(row.get("full_name") or "").strip()),
            None,
        )
        primary_alias = (
            table_aliases.get(int(primary_table.get("workspace_table_id") or 0), "src")
            if primary_table
            else "src"
        )
        base_from = (
            f"{_quote_fqn(primary_table.get('full_name'))} {_quote_identifier(primary_alias)}"
            if primary_table
            else "`<table>` `src`"
        )

        seen_aliases: set[str] = set()
        select_lines: List[str] = []
        for row in accepted_columns:
            column_name = str(row.get("column_name") or "").strip()
            if not column_name:
                continue
            workspace_table_id = int(row.get("workspace_table_id") or 0)
            table_alias = table_aliases.get(workspace_table_id, primary_alias if primary_table else "src")
            output_alias = _normalize_sql_identifier(
                row.get("source_field_name"),
                fallback=column_name,
                seen=seen_aliases,
            )
            select_lines.append(
                f"  {_quote_identifier(table_alias)}.{_quote_identifier(column_name)} AS {_quote_identifier(output_alias)}"
            )

        select_clause = ",\n".join(select_lines) if select_lines else "  -- add accepted columns here"
        return (
            f"{comment_block}CREATE VIEW {_quote_identifier(view_name)} AS\n"
            "SELECT\n"
            f"{select_clause}\n"
            f"FROM {base_from}\n"
            ";"
        )

    @staticmethod
    def _parse_join_expr(expr: str) -> tuple[str, str, str]:
        pattern = r"^get_json_object\(\{(from|to)\}\.([A-Za-z0-9_]+),\s*'\$\.([A-Za-z0-9_]+)'\)$"
        match = re.match(pattern, expr)
        if not match:
            raise ForgeError(
                "Join spec expr must match get_json_object({from|to}.<col>, '$.<key>')",
                status_code=400,
            )
        return match.group(1), match.group(2), match.group(3)

    def _get_session_row(self, *, workspace_id: str, session_id: str) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM forge_match_session
            WHERE id = :session_id
              AND workspace_id = :workspace_id
            LIMIT 1
            """,
            {"workspace_id": workspace_id, "session_id": session_id},
        )
        if not rows:
            raise ForgeError("ForgeMatch session not found", status_code=404)
        return self._session_row_to_response(rows[0])

    def _existing_results_by_source(self, *, session_id: str) -> Dict[int, str]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT source_record_id, id
            FROM forge_match_result
            WHERE session_id = :session_id
            """,
            {"session_id": session_id},
        )
        out: dict[int, str] = {}
        for row in rows:
            source_id = int(row.get("source_record_id") or 0)
            mapping_id = str(row.get("id") or "").strip()
            if source_id > 0 and mapping_id:
                out[source_id] = mapping_id
        return out

    def _clear_session_results(self, *, session_id: str) -> None:
        self._sql.execute_write(
            """
            DELETE FROM forge_match_result
            WHERE session_id = :session_id
            """,
            {"session_id": session_id},
        )

    def _persist_session_analysis_trace(
        self,
        *,
        session_id: str,
        current_summary: Any,
        trace_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        summary = current_summary if isinstance(current_summary, dict) else {}
        next_summary = dict(summary)
        next_summary["analysis_trace"] = dict(trace_snapshot)
        self._sql.execute_write(
            """
            UPDATE forge_match_session
            SET summary_json = :summary_json,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :session_id
            """,
            {
                "session_id": session_id,
                "summary_json": _json_dumps(next_summary),
            },
        )
        return next_summary

    def _load_source_rows(self, *, session_id: str, limit: int = 2000, offset: int = 0) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              row_id,
              sheet_name,
              `row_number`,
              source_field_name,
              source_description,
              source_type,
              source_object_name,
              sample_value,
              category,
              normalized_search_text,
              raw_row_json,
              created_at
            FROM forge_match_source_record
            WHERE session_id = :session_id
            ORDER BY sheet_name ASC, `row_number` ASC
            LIMIT :limit OFFSET :offset
            """,
            {"session_id": session_id, "limit": int(limit), "offset": int(offset)},
        )
        return [self._json_safe_row(dict(row)) for row in rows]

    def _load_mapping_rows(
        self,
        *,
        workspace_id: str,
        session_id: str,
        limit: int = 5000,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              fr.id AS mapping_id,
              fr.session_id,
              fr.source_record_id,
              fsr.row_id AS source_row_id,
              fsr.sheet_name,
              fsr.`row_number`,
              fsr.source_field_name,
              fsr.source_description,
              fsr.source_type,
              fsr.source_object_name,
              fsr.sample_value,
              fr.best_match_workspace_column_id,
              wc_best.column_name AS best_match_column_name,
              wt_best.table_name AS best_match_table_name,
              fr.alternate_workspace_column_ids,
              fr.retrieved_candidates_json,
              fr.llm_response_json,
              fr.match_decision,
              fr.reason_codes_json,
              fr.explanation,
              fr.ambiguity_note,
              fr.llm_confidence,
              fr.confidence_score,
              fr.confidence_band,
              fr.status,
              fr.review_notes,
              fr.manually_selected_workspace_column_id,
              wc_manual.column_name AS manual_column_name,
              wt_manual.table_name AS manual_table_name,
              fr.reviewer_user_id,
              fr.reviewed_at,
              fr.created_at,
              fr.updated_at
            FROM forge_match_result fr
            JOIN forge_match_source_record fsr ON fsr.id = fr.source_record_id
            JOIN forge_match_session fms ON fms.id = fr.session_id
            LEFT JOIN workspace_column wc_best ON wc_best.id = fr.best_match_workspace_column_id
            LEFT JOIN workspace_table wt_best ON wt_best.id = wc_best.workspace_table_id
            LEFT JOIN workspace_column wc_manual ON wc_manual.id = fr.manually_selected_workspace_column_id
            LEFT JOIN workspace_table wt_manual ON wt_manual.id = wc_manual.workspace_table_id
            WHERE fr.session_id = :session_id
              AND fms.workspace_id = :workspace_id
            ORDER BY fsr.sheet_name ASC, fsr.`row_number` ASC
            LIMIT :limit OFFSET :offset
            """,
            {
                "workspace_id": workspace_id,
                "session_id": session_id,
                "limit": int(limit),
                "offset": int(offset),
            },
        )

        return [self._mapping_row_to_response(self._json_safe_row(dict(row))) for row in rows]

    def _mapping_row_to_response(self, row: Dict[str, Any]) -> Dict[str, Any]:
        best_match = None
        if row.get("best_match_workspace_column_id"):
            best_match = {
                "column_id": int(row["best_match_workspace_column_id"]),
                "column_name": row.get("best_match_column_name"),
                "display_name": _display_name(row.get("best_match_column_name")),
                "table_name": row.get("best_match_table_name"),
            }

        alt_ids = _parse_json_list(row.get("alternate_workspace_column_ids"))
        retrieved = _parse_json_list(row.get("retrieved_candidates_json"))
        llm_response = _parse_json_dict(row.get("llm_response_json")) or {}
        alternates = [item for item in retrieved if int(item.get("column_id") or 0) in {int(v) for v in alt_ids if _safe_int(v) is not None}]

        out = {
            "mapping_id": row.get("mapping_id"),
            "source_record_id": row.get("source_record_id"),
            "source_row_id": row.get("source_row_id"),
            "sheet_name": row.get("sheet_name"),
            "row_number": row.get("row_number"),
            "source_field_name": row.get("source_field_name"),
            "source_description": row.get("source_description"),
            "source_type": row.get("source_type"),
            "source_object_name": row.get("source_object_name"),
            "sample_value": row.get("sample_value"),
            "best_match": best_match,
            "alternates": alternates[:2],
            "confidence_score": int(row.get("confidence_score") or 0),
            "confidence_band": str(row.get("confidence_band") or "low"),
            "match_decision": row.get("match_decision"),
            "explanation": row.get("explanation"),
            "reason_codes": _parse_json_list(row.get("reason_codes_json")),
            "status": row.get("status"),
            "review_notes": row.get("review_notes"),
            "manually_selected_workspace_column_id": row.get("manually_selected_workspace_column_id"),
            "manual_selection": None,
            "retrieved_candidates": retrieved,
            "llm_result": llm_response,
            "shared_pipeline": dict(llm_response.get("shared_pipeline") or {}),
            "reviewer_user_id": row.get("reviewer_user_id"),
            "reviewed_at": row.get("reviewed_at"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
        if row.get("manually_selected_workspace_column_id"):
            out["manual_selection"] = {
                "column_id": int(row["manually_selected_workspace_column_id"]),
                "column_name": row.get("manual_column_name"),
                "display_name": _display_name(row.get("manual_column_name")),
                "table_name": row.get("manual_table_name"),
            }
        return out

    @staticmethod
    def _source_record_to_dict(record: SourceFieldRecord) -> Dict[str, Any]:
        return {
            "row_id": record.row_id,
            "sheet_name": record.sheet_name,
            "row_number": record.row_number,
            "source_field_name": record.source_field_name,
            "source_description": record.source_description,
            "source_type": record.source_type,
            "source_object_name": record.source_object_name,
            "sample_value": record.sample_value,
            "category": record.category,
        }

    @staticmethod
    def _source_row_to_response(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": int(row.get("id") or 0),
            "row_id": row.get("row_id"),
            "sheet_name": row.get("sheet_name"),
            "row_number": row.get("row_number"),
            "source_field_name": row.get("source_field_name"),
            "source_description": row.get("source_description"),
            "source_type": row.get("source_type"),
            "source_object_name": row.get("source_object_name"),
            "sample_value": row.get("sample_value"),
            "category": row.get("category"),
            "created_at": row.get("created_at"),
        }

    def _session_row_to_response(self, row: Dict[str, Any]) -> Dict[str, Any]:
        safe = self._json_safe_row(dict(row))
        safe["summary_json"] = _parse_json_dict(safe.get("summary_json"))
        return safe

    @staticmethod
    def _build_summary(mappings: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        counts = {status: 0 for status in _ALLOWED_RESULT_STATUSES}
        decision_counts = {"matched": 0, "ambiguous": 0, "no_confident_match": 0}
        by_band = {"high": 0, "medium": 0, "low": 0}

        for row in mappings:
            status = str(row.get("status") or "suggested")
            if status in counts:
                counts[status] += 1
            decision = str(row.get("match_decision") or "no_confident_match")
            if decision in decision_counts:
                decision_counts[decision] += 1
            band = str(row.get("confidence_band") or "low")
            if band in by_band:
                by_band[band] += 1

        return {
            "total": len(mappings),
            "status_counts": counts,
            "decision_counts": decision_counts,
            "confidence_bands": by_band,
        }

    def _get_mapping_row_by_id(self, *, workspace_id: str, session_id: str, mapping_id: str) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT fr.id, fr.session_id
            FROM forge_match_result fr
            JOIN forge_match_session fms ON fms.id = fr.session_id
            WHERE fr.id = :id
              AND fr.session_id = :session_id
              AND fms.workspace_id = :workspace_id
            LIMIT 1
            """,
            {"id": mapping_id, "session_id": session_id, "workspace_id": workspace_id},
        )
        return dict(rows[0]) if rows else None

    def _assert_workspace_column(self, *, workspace_id: str, workspace_column_id: int) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT wc.id
            FROM workspace_column wc
            JOIN workspace_table wt ON wt.id = wc.workspace_table_id
            WHERE wc.id = :id
              AND wt.workspace_id = :workspace_id
            LIMIT 1
            """,
            {"id": int(workspace_column_id), "workspace_id": workspace_id},
        )
        if not rows:
            raise ForgeError("manually_selected_workspace_column_id not found in workspace", status_code=404)

    @staticmethod
    def _json_safe_row(row: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, (datetime, date)):
                out[key] = value.isoformat()
            else:
                out[key] = value
        return out


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, default=str)


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if text == "":
        raise ForgeError(f"{field} is required", status_code=400)
    return text


def _to_text_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed


def _parse_json_dict(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _parse_json_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _display_name(column_name: Any) -> str:
    text = str(column_name or "").strip()
    if text == "":
        return ""
    return " ".join(token.capitalize() for token in text.replace("-", "_").split("_") if token)


def _require_sql_identifier(value: Any, *, field: str = "identifier") -> str:
    text = str(value or "").strip()
    if not text or not _SQL_IDENT.match(text):
        raise ForgeError(f"Unsafe SQL {field}: {text or '<empty>'}", status_code=400)
    return text


def _quote_identifier(value: Any) -> str:
    return f"`{_require_sql_identifier(value)}`"


def _quote_fqn(full_name: Any) -> str:
    text = str(full_name or "").strip()
    parts = text.split(".")
    if len(parts) not in (2, 3):
        raise ForgeError("Invalid fully qualified table name", status_code=400)
    return ".".join(_quote_identifier(part) for part in parts)


def _normalize_sql_identifier(
    value: Any,
    *,
    fallback: str,
    seen: Optional[set[str]] = None,
) -> str:
    raw = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")
    if normalized == "":
        normalized = fallback
    if normalized and normalized[0].isdigit():
        normalized = f"col_{normalized}"
    normalized = re.sub(r"_+", "_", normalized)
    if not _SQL_IDENT.match(normalized):
        normalized = re.sub(r"[^a-z0-9_]+", "_", fallback.lower()).strip("_") or "draft_view"
        if normalized[0].isdigit():
            normalized = f"col_{normalized}"
    if seen is None:
        return normalized
    candidate = normalized
    suffix = 2
    while candidate in seen:
        candidate = f"{normalized}_{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


def _build_table_alias_map_for_rows(rows: Sequence[Dict[str, Any]]) -> Dict[int, str]:
    seen_aliases: set[str] = set()
    aliases: Dict[int, str] = {}
    for row in rows:
        workspace_table_id = int(row.get("workspace_table_id") or 0)
        if workspace_table_id <= 0 or workspace_table_id in aliases:
            continue
        aliases[workspace_table_id] = _make_table_alias(
            table_name=row.get("table_name"),
            full_name=row.get("full_name"),
            workspace_table_id=workspace_table_id,
            seen=seen_aliases,
        )
    return aliases


def _build_table_alias_map_for_plan(plan: DomainPlan) -> Dict[int, str]:
    seen_aliases: set[str] = set()
    aliases: Dict[int, str] = {}
    for table in plan.tables:
        workspace_table_id = int(getattr(table, "workspace_table_id", 0) or 0)
        if workspace_table_id <= 0 or workspace_table_id in aliases:
            continue
        aliases[workspace_table_id] = _make_table_alias(
            table_name=getattr(table, "table_name", None),
            full_name=getattr(table, "full_name", None),
            workspace_table_id=workspace_table_id,
            seen=seen_aliases,
        )
    return aliases


def _make_table_alias(
    *,
    table_name: Any,
    full_name: Any,
    workspace_table_id: int,
    seen: set[str],
) -> str:
    base_name = str(table_name or "").strip()
    if not base_name:
        full_name_text = str(full_name or "").strip()
        if full_name_text:
            base_name = full_name_text.split(".")[-1].strip()
    return _normalize_sql_identifier(
        base_name,
        fallback=f"table_{int(workspace_table_id)}",
        seen=seen,
    )


def _score_suspected_key_column(*, column_name: Any, description: Any) -> int:
    name = str(column_name or "").strip().lower()
    desc = str(description or "").strip().lower()
    if not name:
        return 0

    score = 0
    if name in {"id", "pk"}:
        score += 10
    if name.startswith("k_"):
        score += 9
    if name.endswith("_id") or name.endswith("_key"):
        score += 7
    if "_id_" in name or "_key_" in name:
        score += 5
    if "foreign key" in desc:
        score += 8
    if "primary key" in desc:
        score += 8
    if "natural key" in desc:
        score += 7
    if "surrogate" in desc:
        score += 6
    if "identifier" in desc or "identifying" in desc:
        score += 5
    if "used to join" in desc or "join to" in desc or "join key" in desc:
        score += 5
    if "foreign" in desc and "key" in desc:
        score += 4
    if "primary" in desc and "key" in desc:
        score += 4
    if " key " in f" {desc} ":
        score += 3
    return score


def _normalize_optional_sql_identifier(value: Any, *, field: str) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return _require_sql_identifier(text, field=field)


def _canonicalize_sql(sql: str) -> str:
    out = str(sql or "")
    out = re.sub(r"/\*.*?\*/", " ", out, flags=re.DOTALL)
    out = re.sub(r"--[^\n]*", " ", out)
    out = re.sub(r"'(?:''|[^'])*'", "''", out)
    out = re.sub(r'"(?:""|[^"])*"', '""', out)
    out = re.sub(r"`(?:``|[^`])*`", "``", out)
    out = re.sub(r"\s+", " ", out)
    return out.strip()


def _classify_draft_sql_statement(sql: str) -> str:
    source = str(sql or "").strip()
    if source == "":
        raise ForgeError("sql is required", status_code=400)

    canonical = _canonicalize_sql(source)
    without_trailing = canonical[:-1].strip() if canonical.endswith(";") else canonical
    if ";" in without_trailing:
        raise ForgeError("Draft SQL must contain exactly one statement", status_code=400)

    upper = without_trailing.upper()
    if upper.startswith("SELECT ") or upper.startswith("WITH "):
        return "select"
    if re.match(r"^CREATE(\s+OR\s+REPLACE)?\s+VIEW\b", upper):
        forbidden = r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|TRUNCATE|CALL|EXECUTE|GRANT|REVOKE|OPTIMIZE|VACUUM|USE|COPY)\b"
        if re.search(forbidden, upper):
            raise ForgeError("Draft SQL may only execute SELECT or CREATE VIEW statements", status_code=400)
        if " AS " not in f" {upper} ":
            raise ForgeError("CREATE VIEW statement must include an AS clause", status_code=400)
        return "create_view"
    raise ForgeError("Draft SQL must start with SELECT, WITH, CREATE VIEW, or CREATE OR REPLACE VIEW", status_code=400)


def _prepare_draft_execution_sql(
    sql: str,
    *,
    catalog_name: Optional[str],
    schema_name: Optional[str],
) -> str:
    statement_type = _classify_draft_sql_statement(sql)
    if statement_type != "create_view" or (not catalog_name and not schema_name):
        return str(sql or "").strip()
    return _rewrite_create_view_target(
        str(sql or "").strip(),
        catalog_name=catalog_name,
        schema_name=schema_name,
    )


def _rewrite_create_view_target(
    sql: str,
    *,
    catalog_name: Optional[str],
    schema_name: Optional[str],
) -> str:
    pattern = re.compile(
        r"^\s*(CREATE(?:\s+OR\s+REPLACE)?\s+VIEW)\s+(.+?)\s+(AS\b.*)$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.match(str(sql or "").strip())
    if not match:
        raise ForgeError("Unable to parse CREATE VIEW statement", status_code=400)
    prefix, target, suffix = match.groups()
    target_name = _extract_terminal_identifier(target)
    parts = [part for part in (catalog_name, schema_name, target_name) if part]
    rewritten_target = ".".join(_quote_identifier(part) for part in parts)
    return f"{prefix} {rewritten_target} {suffix}"


def _extract_terminal_identifier(target: str) -> str:
    raw = str(target or "").strip()
    if raw == "":
        raise ForgeError("CREATE VIEW target is required", status_code=400)
    pieces = [piece.strip() for piece in raw.split(".") if piece.strip()]
    if not pieces:
        raise ForgeError("CREATE VIEW target is invalid", status_code=400)
    terminal = pieces[-1].strip().strip("`").strip('"')
    return _require_sql_identifier(terminal, field="view_name")


__all__ = ["ForgeMatchMappingService"]
