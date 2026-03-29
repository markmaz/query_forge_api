from __future__ import annotations

from typing import Any

from app.services.shared_ai.artifacts import CandidateSetArtifact, CapabilityMapArtifact, PromptSignalsArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.node import BasePipelineNode


class ApplyPolicyRerankNode(BasePipelineNode):
    def __init__(
        self,
        *,
        adapter: Any,
        name: str = "apply_policy_rerank",
        candidates_artifact_key: str = "capability_enriched_candidates",
        prompt_signals_artifact_key: str = "prompt_signals",
        capability_map_artifact_key: str = "capability_map",
        output_artifact_key: str = "reranked_candidates",
    ) -> None:
        self.name = name
        self.requires = (
            candidates_artifact_key,
            prompt_signals_artifact_key,
            capability_map_artifact_key,
        )
        self.produces = (output_artifact_key,)
        self._adapter = adapter
        self._candidates_artifact_key = candidates_artifact_key
        self._prompt_signals_artifact_key = prompt_signals_artifact_key
        self._capability_map_artifact_key = capability_map_artifact_key
        self._output_artifact_key = output_artifact_key

    def run(self, context: PipelineContext) -> PipelineContext:
        candidate_set = context.get_artifact(self._candidates_artifact_key, node_name=self.name)
        prompt_signals = context.get_artifact(self._prompt_signals_artifact_key, node_name=self.name)
        capability_map = context.get_artifact(self._capability_map_artifact_key, node_name=self.name)

        if not isinstance(candidate_set, CandidateSetArtifact):
            raise TypeError(f"{self.name} expected CandidateSetArtifact at '{self._candidates_artifact_key}'.")
        if not isinstance(prompt_signals, PromptSignalsArtifact):
            raise TypeError(f"{self.name} expected PromptSignalsArtifact at '{self._prompt_signals_artifact_key}'.")
        if not isinstance(capability_map, CapabilityMapArtifact):
            raise TypeError(f"{self.name} expected CapabilityMapArtifact at '{self._capability_map_artifact_key}'.")

        reranked = self._adapter.rerank(
            context=context,
            candidates=candidate_set.candidates,
            prompt_signals=prompt_signals,
            capability_map=capability_map,
        )
        context.set_artifact(self._output_artifact_key, reranked)
        context.add_debug(
            self.name,
            {
                "candidate_count": len(reranked.candidates),
                "policy_effect_count": len(reranked.policy_effects),
                "signals": list(prompt_signals.signals),
            },
        )
        return context
