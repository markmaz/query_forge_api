from __future__ import annotations

from typing import Protocol

from app.services.shared_ai.artifacts import CandidateSetArtifact, LLMDecisionArtifact, RerankedCandidatesArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.node import BasePipelineNode


class CandidateRankingAdapter(Protocol):
    def rank(
        self,
        *,
        context: PipelineContext,
        candidates: CandidateSetArtifact | RerankedCandidatesArtifact,
    ) -> LLMDecisionArtifact:
        ...


class RankCandidatesNode(BasePipelineNode):
    def __init__(
        self,
        *,
        adapter: CandidateRankingAdapter,
        name: str = "rank_candidates",
        candidates_artifact_key: str = "reranked_candidates",
        output_artifact_key: str = "llm_decision",
    ) -> None:
        self.name = name
        self.requires = (candidates_artifact_key,)
        self.produces = (output_artifact_key,)
        self._adapter = adapter
        self._candidates_artifact_key = candidates_artifact_key
        self._output_artifact_key = output_artifact_key

    def run(self, context: PipelineContext) -> PipelineContext:
        candidate_set = context.get_artifact(self._candidates_artifact_key, node_name=self.name)
        if not isinstance(candidate_set, (CandidateSetArtifact, RerankedCandidatesArtifact)):
            raise TypeError(
                f"{self.name} expected CandidateSetArtifact or RerankedCandidatesArtifact at "
                f"'{self._candidates_artifact_key}'."
            )

        artifact = self._adapter.rank(context=context, candidates=candidate_set)
        if not isinstance(artifact, LLMDecisionArtifact):
            raise TypeError(f"{self.name} expected LLMDecisionArtifact from ranking adapter.")

        context.set_artifact(self._output_artifact_key, artifact)
        context.add_debug(
            self.name,
            {
                "selected_candidate_id": artifact.selected_candidate_id,
                "ranked_candidate_ids": list(artifact.ranked_candidate_ids or []),
                "confidence": artifact.confidence,
            },
        )
        return context
