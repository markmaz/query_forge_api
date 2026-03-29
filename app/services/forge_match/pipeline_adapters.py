from __future__ import annotations

from typing import Optional

from app.services.forge_match.confidence import ForgeMatchConfidenceScorer
from app.services.forge_match.field_extractor import SourceFieldRecord
from app.services.forge_match.llm_ranker import ForgeMatchLLMRanker
from app.services.shared_ai.adapters.candidates import candidate_from_column_row, candidate_to_dict
from app.services.shared_ai.artifacts import CandidateSetArtifact, ConfidenceArtifact, LLMDecisionArtifact
from app.services.shared_ai.context import PipelineContext


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
