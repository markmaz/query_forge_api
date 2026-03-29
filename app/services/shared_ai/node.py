from __future__ import annotations

from typing import Protocol

from app.services.shared_ai.context import PipelineContext


class PipelineNode(Protocol):
    name: str
    requires: tuple[str, ...]
    produces: tuple[str, ...]

    def run(self, context: PipelineContext) -> PipelineContext:
        ...


class BasePipelineNode:
    name = "unnamed"
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    def run(self, context: PipelineContext) -> PipelineContext:
        raise NotImplementedError

    def build_trace_summary(self, context: PipelineContext) -> dict:
        debug_value = context.debug.get(self.name)
        if isinstance(debug_value, dict):
            return dict(debug_value)
        return {}
