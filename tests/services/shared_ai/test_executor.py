from __future__ import annotations

import pytest

from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.errors import MissingArtifactError, PipelineNodeExecutionError
from app.services.shared_ai.executor import PipelineExecutor
from app.services.shared_ai.graph import PipelineDefinition, PipelineEdge
from app.services.shared_ai.node import BasePipelineNode


class _WriteNode(BasePipelineNode):
    def __init__(self, *, name: str, output_key: str, output_value: object) -> None:
        self.name = name
        self.output_key = output_key
        self.output_value = output_value

    def run(self, context: PipelineContext) -> PipelineContext:
        context.set_artifact(self.output_key, self.output_value)
        context.add_debug(self.name, {"artifact": self.output_key})
        return context


class _RequireNode(BasePipelineNode):
    def __init__(self, *, name: str, requires: tuple[str, ...], produces: tuple[str, ...] = ()) -> None:
        self.name = name
        self.requires = requires
        self.produces = produces

    def run(self, context: PipelineContext) -> PipelineContext:
        for key in self.requires:
            context.get_artifact(key, node_name=self.name)
        context.add_debug(self.name, {"required": list(self.requires)})
        return context


class _BranchNode(BasePipelineNode):
    def __init__(self, *, name: str, metadata_key: str, metadata_value: object) -> None:
        self.name = name
        self.metadata_key = metadata_key
        self.metadata_value = metadata_value

    def run(self, context: PipelineContext) -> PipelineContext:
        context.metadata[self.metadata_key] = self.metadata_value
        context.add_debug(self.name, {"metadata_key": self.metadata_key})
        return context


class _FailNode(BasePipelineNode):
    def __init__(self, *, name: str) -> None:
        self.name = name

    def run(self, context: PipelineContext) -> PipelineContext:
        del context
        raise RuntimeError("boom")


def _context() -> PipelineContext:
    return PipelineContext(
        pipeline_name="shared_ai_test",
        trace_id="trace-1",
        workspace_id="ws-1",
        user_id="user-1",
        request={},
    )


def test_executor_runs_nodes_in_dependency_order() -> None:
    executor = PipelineExecutor()
    definition = PipelineDefinition(
        name="ordered",
        nodes={
            "start": _WriteNode(name="start", output_key="normalized_text", output_value="hello"),
            "next": _RequireNode(name="next", requires=("normalized_text",)),
        },
        edges=[PipelineEdge("start", "next")],
        start_nodes=["start"],
    )

    context = executor.execute(definition, _context())

    assert context.metadata["executed_nodes"] == ["start", "next"]
    assert context.timings_ms["start"] >= 0
    assert context.timings_ms["next"] >= 0
    assert [row["node"] for row in context.trace_nodes] == ["start", "next"]


def test_executor_raises_for_missing_required_artifact() -> None:
    executor = PipelineExecutor()
    definition = PipelineDefinition(
        name="missing_artifact",
        nodes={"start": _RequireNode(name="start", requires=("required_key",))},
        edges=[],
        start_nodes=["start"],
    )

    with pytest.raises(MissingArtifactError):
        executor.execute(definition, _context())


def test_executor_supports_simple_conditional_branching() -> None:
    executor = PipelineExecutor()
    definition = PipelineDefinition(
        name="branching",
        nodes={
            "start": _BranchNode(name="start", metadata_key="should_run", metadata_value=True),
            "branch": _WriteNode(name="branch", output_key="branch_result", output_value="ok"),
            "skipped": _WriteNode(name="skipped", output_key="skipped_result", output_value="bad"),
        },
        edges=[
            PipelineEdge("start", "branch", condition="metadata:should_run"),
            PipelineEdge("start", "skipped", condition="!metadata:should_run"),
        ],
        start_nodes=["start"],
    )

    context = executor.execute(definition, _context())

    assert context.artifacts["branch_result"] == "ok"
    assert "skipped_result" not in context.artifacts
    assert "skipped" in context.metadata["skipped_nodes"]
    assert [row["node"] for row in context.trace_nodes] == ["start", "branch"]


def test_executor_wraps_node_errors_with_node_name() -> None:
    executor = PipelineExecutor()
    definition = PipelineDefinition(
        name="failing",
        nodes={"start": _FailNode(name="start")},
        edges=[],
        start_nodes=["start"],
    )

    with pytest.raises(PipelineNodeExecutionError) as exc:
        executor.execute(definition, _context())

    assert exc.value.node_name == "start"


def test_executor_surfaces_unexpected_node_errors() -> None:
    class _AssertionFailNode(BasePipelineNode):
        def __init__(self, *, name: str) -> None:
            self.name = name

        def run(self, context: PipelineContext) -> PipelineContext:
            del context
            raise AssertionError("unexpected node bug")

    executor = PipelineExecutor()
    definition = PipelineDefinition(
        name="failing_assertion",
        nodes={"start": _AssertionFailNode(name="start")},
        edges=[],
        start_nodes=["start"],
    )

    with pytest.raises(AssertionError, match="unexpected node bug"):
        executor.execute(definition, _context())
