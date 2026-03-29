from __future__ import annotations

from typing import Any, Callable

from app.services.forge_match.normalizer import normalize_text as default_normalize_text
from app.services.shared_ai.artifacts import NormalizedTextArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.node import BasePipelineNode


class NormalizeTextNode(BasePipelineNode):
    def __init__(
        self,
        *,
        name: str = "normalize_text",
        request_text_key: str = "prompt",
        output_artifact_key: str = "normalized_text",
        normalizer: Callable[[Any], str] | None = None,
    ) -> None:
        self.name = name
        self.requires = ()
        self.produces = (output_artifact_key,)
        self._request_text_key = request_text_key
        self._output_artifact_key = output_artifact_key
        self._normalizer = normalizer or default_normalize_text

    def run(self, context: PipelineContext) -> PipelineContext:
        original_text = str(context.request.get(self._request_text_key) or "")
        artifact = NormalizedTextArtifact(
            original_text=original_text,
            normalized_text=self._normalizer(original_text),
        )
        context.set_artifact(self._output_artifact_key, artifact)
        context.add_debug(
            self.name,
            {
                "request_text_key": self._request_text_key,
                "normalized_text": artifact.normalized_text,
            },
        )
        return context
