from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Set

from app.services.shared_ai.errors import PipelineGraphValidationError
from app.services.shared_ai.node import PipelineNode


@dataclass(frozen=True)
class PipelineEdge:
    from_node: str
    to_node: str
    condition: str | None = None


@dataclass(frozen=True)
class PipelineDefinition:
    name: str
    nodes: Dict[str, PipelineNode]
    edges: List[PipelineEdge]
    start_nodes: List[str]


def validate_pipeline_definition(definition: PipelineDefinition) -> None:
    if not definition.name.strip():
        raise PipelineGraphValidationError("Pipeline definition requires a name.")
    if not definition.nodes:
        raise PipelineGraphValidationError("Pipeline definition must include at least one node.")
    if not definition.start_nodes:
        raise PipelineGraphValidationError("Pipeline definition must include at least one start node.")

    node_names = set(definition.nodes.keys())
    unknown_starts = [name for name in definition.start_nodes if name not in node_names]
    if unknown_starts:
        raise PipelineGraphValidationError(
            f"Unknown start node(s): {', '.join(sorted(unknown_starts))}."
        )

    for edge in definition.edges:
        if edge.from_node not in node_names:
            raise PipelineGraphValidationError(f"Edge references unknown from_node '{edge.from_node}'.")
        if edge.to_node not in node_names:
            raise PipelineGraphValidationError(f"Edge references unknown to_node '{edge.to_node}'.")

    adjacency = _adjacency_map(definition.edges)
    visited: Set[str] = set()
    active_stack: Set[str] = set()

    def _visit(node_name: str) -> None:
        if node_name in active_stack:
            raise PipelineGraphValidationError(f"Pipeline graph contains a cycle at '{node_name}'.")
        if node_name in visited:
            return
        active_stack.add(node_name)
        for successor in adjacency.get(node_name, []):
            _visit(successor)
        active_stack.remove(node_name)
        visited.add(node_name)

    for node_name in node_names:
        _visit(node_name)


def incoming_edges(definition: PipelineDefinition) -> dict[str, list[PipelineEdge]]:
    incoming: dict[str, list[PipelineEdge]] = {name: [] for name in definition.nodes}
    for edge in definition.edges:
        incoming.setdefault(edge.to_node, []).append(edge)
    return incoming


def outgoing_edges(definition: PipelineDefinition) -> dict[str, list[PipelineEdge]]:
    outgoing: dict[str, list[PipelineEdge]] = {name: [] for name in definition.nodes}
    for edge in definition.edges:
        outgoing.setdefault(edge.from_node, []).append(edge)
    return outgoing


def _adjacency_map(edges: Iterable[PipelineEdge]) -> dict[str, list[str]]:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.from_node, []).append(edge.to_node)
    return adjacency
