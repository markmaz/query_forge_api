from __future__ import annotations

from typing import Protocol

from app.services.shared_ai.artifacts import CandidateSetArtifact, ConfidenceArtifact, LLMDecisionArtifact, RerankedCandidatesArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.node import BasePipelineNode


class CandidateConfidenceAdapter(Protocol):
    def score(
        self,
        *,
        context: PipelineContext,
        candidates: CandidateSetArtifact | RerankedCandidatesArtifact,
        decision: LLMDecisionArtifact,
    ) -> ConfidenceArtifact:
        ...


class ScoreConfidenceNode(BasePipelineNode):
    def __init__(
        self,
        *,
        adapter: CandidateConfidenceAdapter,
        name: str = "score_confidence",
        candidates_artifact_key: str = "reranked_candidates",
        decision_artifact_key: str = "llm_decision",
        output_artifact_key: str = "confidence",
    ) -> None:
        self.name = name
        self.requires = (candidates_artifact_key, decision_artifact_key)
        self.produces = (output_artifact_key,)
        self._adapter = adapter
        self._candidates_artifact_key = candidates_artifact_key
        self._decision_artifact_key = decision_artifact_key
        self._output_artifact_key = output_artifact_key

    def run(self, context: PipelineContext) -> PipelineContext:
        candidate_set = context.get_artifact(self._candidates_artifact_key, node_name=self.name)
        decision = context.get_artifact(self._decision_artifact_key, node_name=self.name)
        if not isinstance(candidate_set, (CandidateSetArtifact, RerankedCandidatesArtifact)):
            raise TypeError(
                f"{self.name} expected CandidateSetArtifact or RerankedCandidatesArtifact at "
                f"'{self._candidates_artifact_key}'."
            )
        if not isinstance(decision, LLMDecisionArtifact):
            raise TypeError(f"{self.name} expected LLMDecisionArtifact at '{self._decision_artifact_key}'.")

        artifact = self._adapter.score(context=context, candidates=candidate_set, decision=decision)
        if not isinstance(artifact, ConfidenceArtifact):
            raise TypeError(f"{self.name} expected ConfidenceArtifact from confidence adapter.")

        context.set_artifact(self._output_artifact_key, artifact)
        context.add_debug(
            self.name,
            {
                "confidence_score": artifact.confidence_score,
                "confidence_band": artifact.confidence_band,
            },
        )
        return context
