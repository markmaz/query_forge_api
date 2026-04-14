from __future__ import annotations

import uuid
from typing import Any, Callable, Optional

from app.services.forge_match.candidate_retriever import ForgeMatchCandidateRetriever, ForgeMatchColumnRetrievalAdapter
from app.services.forge_match.field_extractor import SourceFieldRecord
from app.services.forge_match.pipeline_adapters import (
    ExistingRetrieverCandidateAdapter,
    ForgeMatchConfidenceAdapter,
    ForgeMatchLLMDecisionAdapter,
    ForgeMatchPersistenceAdapter,
)
from app.services.forge_match.pipeline_definition import (
    build_forge_match_candidate_pipeline_definition,
    build_forge_match_row_pipeline_definition,
)
from app.services.shared_ai.artifacts import MatchOutcomeArtifact, PersistenceArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.executor import PipelineExecutor
from app.services.shared_ai.tracing import serialize_pipeline_context


class ForgeMatchRowPipelineRunner:
    def __init__(
        self,
        *,
        pipeline_executor: PipelineExecutor,
        retriever: Any,
        ranker: Any,
        confidence: Any,
        persist_result: Callable[..., None],
    ) -> None:
        self._pipeline_executor = pipeline_executor
        self._retriever = retriever
        self._ranker = ranker
        self._confidence = confidence
        self._persist_result = persist_result

    def run(
        self,
        *,
        workspace_id: str,
        session_id: str,
        source_record_id: int,
        source_record: SourceFieldRecord,
        top_n: int,
        domain_id: Optional[int],
        llm_id: Optional[int],
    ) -> tuple[MatchOutcomeArtifact, dict[str, Any], PersistenceArtifact]:
        context = PipelineContext(
            pipeline_name="forge_match_row_pipeline",
            trace_id=f"forge_match_row:{uuid.uuid4().hex}",
            workspace_id=workspace_id,
            user_id=None,
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
            persistence_adapter=ForgeMatchPersistenceAdapter(persist_result=self._persist_result),
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


__all__ = ["ForgeMatchRowPipelineRunner"]
