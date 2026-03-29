from __future__ import annotations

from typing import Protocol

from app.services.shared_ai.artifacts import CandidateSetArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.node import BasePipelineNode


class CandidateRetrievalAdapter(Protocol):
    def retrieve(self, *, context: PipelineContext) -> CandidateSetArtifact:
        ...


class RetrieveCandidatesNode(BasePipelineNode):
    def __init__(
        self,
        *,
        adapter: CandidateRetrievalAdapter,
        name: str = "retrieve_candidates",
        output_artifact_key: str = "candidate_set",
    ) -> None:
        self.name = name
        self.requires = ()
        self.produces = (output_artifact_key,)
        self._adapter = adapter
        self._output_artifact_key = output_artifact_key

    def run(self, context: PipelineContext) -> PipelineContext:
        artifact = self._adapter.retrieve(context=context)
        if not isinstance(artifact, CandidateSetArtifact):
            raise TypeError(f"{self.name} expected CandidateSetArtifact from retrieval adapter.")

        context.set_artifact(self._output_artifact_key, artifact)
        context.add_debug(
            self.name,
            {
                "candidate_count": len(artifact.candidates),
                "retrieval_debug": dict(artifact.retrieval_debug),
            },
        )
        return context
