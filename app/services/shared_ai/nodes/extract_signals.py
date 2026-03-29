from __future__ import annotations

from app.services.planner_domain.prompt_signal_service import PromptSignalService
from app.services.shared_ai.artifacts import NormalizedTextArtifact, PromptSignalsArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.node import BasePipelineNode


class ExtractSignalsNode(BasePipelineNode):
    def __init__(
        self,
        *,
        name: str = "extract_signals",
        input_artifact_key: str = "normalized_text",
        request_text_key: str = "prompt",
        output_artifact_key: str = "prompt_signals",
        signal_service: PromptSignalService | None = None,
    ) -> None:
        self.name = name
        self.requires = ()
        self.produces = (output_artifact_key,)
        self._input_artifact_key = input_artifact_key
        self._request_text_key = request_text_key
        self._output_artifact_key = output_artifact_key
        self._signals = signal_service or PromptSignalService()

    def run(self, context: PipelineContext) -> PipelineContext:
        normalized_artifact = context.get_optional_artifact(self._input_artifact_key, expected_type=NormalizedTextArtifact)
        source_text = normalized_artifact.original_text if normalized_artifact is not None else str(context.request.get(self._request_text_key) or "")
        normalized_text = normalized_artifact.normalized_text if normalized_artifact is not None else str(source_text).strip().lower()
        signals = self._signals.extract_signals(prompt=source_text)
        artifact = PromptSignalsArtifact(
            source_text=source_text,
            normalized_text=normalized_text,
            signals=list(signals),
            debug={"signal_count": len(signals)},
        )
        context.set_artifact(self._output_artifact_key, artifact)
        context.add_debug(
            self.name,
            {
                "source_text": source_text,
                "signals": list(signals),
            },
        )
        return context
