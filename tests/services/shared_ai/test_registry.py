from __future__ import annotations

from app.services.shared_ai.graph import PipelineDefinition
from app.services.shared_ai.node import BasePipelineNode
from app.services.shared_ai.registry import PipelineRegistry


class _Node(BasePipelineNode):
    name = "start"

    def run(self, context):
        return context


def test_pipeline_registry_registers_and_lists_definitions() -> None:
    registry = PipelineRegistry()
    definition = PipelineDefinition(name="alpha", nodes={"start": _Node()}, edges=[], start_nodes=["start"])

    registry.register(definition)

    assert registry.get("alpha") is definition
    assert registry.list_names() == ["alpha"]
    assert list(registry.definitions()) == [definition]
