from __future__ import annotations

from typing import Protocol

from app.services.shared_ai.artifacts import MatchOutcomeArtifact, PersistenceArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.node import BasePipelineNode


class MatchOutcomePersistenceAdapter(Protocol):
    def persist(
        self,
        *,
        context: PipelineContext,
        outcome: MatchOutcomeArtifact,
    ) -> PersistenceArtifact:
        ...


class PersistMatchOutcomeNode(BasePipelineNode):
    def __init__(
        self,
        *,
        adapter: MatchOutcomePersistenceAdapter,
        name: str = "persist_match_outcome",
        outcome_artifact_key: str = "match_outcome",
        output_artifact_key: str = "persistence_result",
    ) -> None:
        self.name = name
        self.requires = (outcome_artifact_key,)
        self.produces = (output_artifact_key,)
        self._adapter = adapter
        self._outcome_artifact_key = outcome_artifact_key
        self._output_artifact_key = output_artifact_key

    def run(self, context: PipelineContext) -> PipelineContext:
        outcome = context.get_artifact(self._outcome_artifact_key, node_name=self.name)
        if not isinstance(outcome, MatchOutcomeArtifact):
            raise TypeError(f"{self.name} expected MatchOutcomeArtifact at '{self._outcome_artifact_key}'.")

        artifact = self._adapter.persist(context=context, outcome=outcome)
        if not isinstance(artifact, PersistenceArtifact):
            raise TypeError(f"{self.name} expected PersistenceArtifact from persistence adapter.")

        context.set_artifact(self._output_artifact_key, artifact)
        context.add_debug(
            self.name,
            {
                "record_id": artifact.record_id,
                "status": artifact.status,
            },
        )
        return context
