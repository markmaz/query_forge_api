from __future__ import annotations

import pytest

from app.services.shared_ai.graph import PipelineDefinition, PipelineEdge, validate_pipeline_definition
from app.services.shared_ai.node import BasePipelineNode
from app.services.shared_ai.errors import PipelineGraphValidationError


class _NoopNode(BasePipelineNode):
    def __init__(self, name: str) -> None:
        self.name = name

    def run(self, context):
        return context


def test_validate_pipeline_definition_rejects_unknown_start_node() -> None:
    definition = PipelineDefinition(
        name="demo",
        nodes={"a": _NoopNode("a")},
        edges=[],
        start_nodes=["missing"],
    )

    with pytest.raises(PipelineGraphValidationError):
        validate_pipeline_definition(definition)


def test_validate_pipeline_definition_rejects_cycle() -> None:
    definition = PipelineDefinition(
        name="cycle",
        nodes={"a": _NoopNode("a"), "b": _NoopNode("b")},
        edges=[
            PipelineEdge("a", "b"),
            PipelineEdge("b", "a"),
        ],
        start_nodes=["a"],
    )

    with pytest.raises(PipelineGraphValidationError):
        validate_pipeline_definition(definition)
