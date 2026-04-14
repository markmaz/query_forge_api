from __future__ import annotations

from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.executor import PipelineExecutor
from app.services.shared_ai.graph import PipelineDefinition, PipelineEdge
from app.services.shared_ai.node import BasePipelineNode
from app.services.shared_ai.nodes.dispatch_subgraph import DispatchSubgraphNode


class _SeedNode(BasePipelineNode):
    name = "seed"
    produces = ("seed_value",)

    def run(self, context: PipelineContext) -> PipelineContext:
        context.set_artifact("seed_value", "alpha")
        return context


class _ChildNode(BasePipelineNode):
    name = "child_transform"
    requires = ("seed_value",)
    produces = ("child_value",)

    def run(self, context: PipelineContext) -> PipelineContext:
        context.set_artifact("child_value", f"{context.get_artifact('seed_value', node_name=self.name)}:beta")
        return context


def _child_definition(_context: PipelineContext) -> PipelineDefinition:
    return PipelineDefinition(
        name="child_pipeline",
        nodes={"child_transform": _ChildNode()},
        edges=[],
        start_nodes=["child_transform"],
    )


def test_dispatch_subgraph_node_executes_child_graph_and_preserves_artifacts() -> None:
    outer = PipelineDefinition(
        name="outer_pipeline",
        nodes={
            "seed": _SeedNode(),
            "dispatch_subgraph": DispatchSubgraphNode(
                definition_factory=_child_definition,
                requires=("seed_value",),
                produces=("child_value",),
            ),
        },
        edges=[PipelineEdge(from_node="seed", to_node="dispatch_subgraph")],
        start_nodes=["seed"],
    )
    context = PipelineContext(
        pipeline_name="outer_pipeline",
        trace_id="trace-1",
        workspace_id="ws-1",
        user_id="user-1",
        request={"prompt": "hello"},
    )

    out = PipelineExecutor().execute(outer, context)

    assert out.get_artifact("child_value", node_name="assert") == "alpha:beta"
    assert [entry["node"] for entry in out.trace_nodes] == ["seed", "child_transform", "dispatch_subgraph"]
    assert out.trace_nodes[0]["lineage"] == ["outer_pipeline"]
    assert out.trace_nodes[1]["lineage"] == ["outer_pipeline", "child_pipeline"]
    assert out.trace_nodes[1]["parent_pipeline"] == "outer_pipeline"
