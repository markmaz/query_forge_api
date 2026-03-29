from __future__ import annotations

from typing import Any

from app.services.shared_ai.artifacts import CandidateSetArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.node import BasePipelineNode


class ResolveCapabilitiesNode(BasePipelineNode):
    def __init__(
        self,
        *,
        adapter: Any,
        name: str = "resolve_capabilities",
        candidates_artifact_key: str = "candidate_set",
        output_artifact_key: str = "capability_map",
        enriched_candidates_artifact_key: str = "capability_enriched_candidates",
    ) -> None:
        self.name = name
        self.requires = (candidates_artifact_key,)
        self.produces = (output_artifact_key, enriched_candidates_artifact_key)
        self._adapter = adapter
        self._candidates_artifact_key = candidates_artifact_key
        self._output_artifact_key = output_artifact_key
        self._enriched_candidates_artifact_key = enriched_candidates_artifact_key

    def run(self, context: PipelineContext) -> PipelineContext:
        candidate_set = context.get_artifact(self._candidates_artifact_key, node_name=self.name)
        if not isinstance(candidate_set, CandidateSetArtifact):
            raise TypeError(f"{self.name} expected CandidateSetArtifact at '{self._candidates_artifact_key}'.")
        enriched_candidates, capability_map = self._adapter.resolve(
            context=context,
            candidates=candidate_set.candidates,
        )
        context.set_artifact(self._output_artifact_key, capability_map)
        context.set_artifact(
            self._enriched_candidates_artifact_key,
            CandidateSetArtifact(
                candidates=list(enriched_candidates),
                retrieval_debug=dict(candidate_set.retrieval_debug),
            ),
        )
        context.add_debug(
            self.name,
            {
                "candidate_count": len(candidate_set.candidates),
                "capability_counts": {
                    candidate_id: len(capabilities)
                    for candidate_id, capabilities in capability_map.candidate_capabilities.items()
                },
            },
        )
        return context
