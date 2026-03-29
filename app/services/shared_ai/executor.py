from __future__ import annotations

from collections import deque
from time import perf_counter

from app.services.shared_ai.conditions import evaluate_condition
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.errors import MissingArtifactError, PipelineNodeExecutionError
from app.services.shared_ai.graph import PipelineDefinition, incoming_edges, outgoing_edges, validate_pipeline_definition
from app.services.shared_ai.node import BasePipelineNode
from app.services.shared_ai.tracing import build_trace_entry


class PipelineExecutor:
    def execute(self, definition: PipelineDefinition, context: PipelineContext) -> PipelineContext:
        validate_pipeline_definition(definition)

        previous_lineage = list(context.metadata.get("graph_lineage") or [])
        current_lineage = [*previous_lineage, definition.name]
        context.metadata["graph_lineage"] = current_lineage
        context.metadata.setdefault("pipeline_definition", definition.name)
        context.metadata.setdefault("executed_nodes", [])
        context.metadata.setdefault("skipped_nodes", [])
        try:
            incoming = incoming_edges(definition)
            outgoing = outgoing_edges(definition)
            ready = deque(definition.start_nodes)
            queued = set(definition.start_nodes)
            executed: set[str] = set()
            skipped: set[str] = set()
            resolved_counts = {name: 0 for name in definition.nodes}
            active_counts = {name: 0 for name in definition.nodes}

            def _resolve_edge(target: str, *, active: bool) -> None:
                resolved_counts[target] += 1
                if active:
                    active_counts[target] += 1
                if resolved_counts[target] != len(incoming.get(target, [])):
                    return
                if active_counts[target] > 0:
                    if target not in executed and target not in skipped and target not in queued:
                        ready.append(target)
                        queued.add(target)
                    return
                if target not in skipped:
                    skipped.add(target)
                    context.metadata["skipped_nodes"].append(target)
                    for downstream_edge in outgoing.get(target, []):
                        _resolve_edge(downstream_edge.to_node, active=False)

            while ready:
                node_name = ready.popleft()
                node = definition.nodes[node_name]
                for artifact_key in getattr(node, "requires", ()):
                    if artifact_key not in context.artifacts:
                        raise MissingArtifactError(node_name=node_name, artifact_key=artifact_key)

                started = perf_counter()
                try:
                    context = node.run(context)
                except MissingArtifactError:
                    raise
                except Exception as exc:  # pragma: no cover - covered via wrapped error assertion
                    elapsed_ms = int((perf_counter() - started) * 1000)
                    context.timings_ms[node_name] = elapsed_ms
                    summary = _trace_summary(node=node, context=context)
                    context.add_trace_node(
                        build_trace_entry(
                            pipeline_name=definition.name,
                            node_name=node_name,
                            status="failed",
                            ms=elapsed_ms,
                            summary=summary,
                            error=str(exc),
                            lineage=current_lineage,
                        )
                    )
                    raise PipelineNodeExecutionError(node_name=node_name, original_error=exc) from exc

                elapsed_ms = int((perf_counter() - started) * 1000)
                context.timings_ms[node_name] = elapsed_ms
                context.metadata["executed_nodes"].append(node_name)
                executed.add(node_name)

                summary = _trace_summary(node=node, context=context)
                context.add_trace_node(
                    build_trace_entry(
                        pipeline_name=definition.name,
                        node_name=node_name,
                        status="completed",
                        ms=elapsed_ms,
                        summary=summary,
                        lineage=current_lineage,
                    )
                )

                for edge in outgoing.get(node_name, []):
                    is_active = evaluate_condition(condition=edge.condition, context=context)
                    _resolve_edge(edge.to_node, active=is_active)

            return context
        finally:
            context.metadata["graph_lineage"] = previous_lineage


def _trace_summary(*, node: BasePipelineNode | object, context: PipelineContext) -> dict:
    if hasattr(node, "build_trace_summary"):
        summary = getattr(node, "build_trace_summary")(context)
        if isinstance(summary, dict):
            return dict(summary)
    debug_value = context.debug.get(getattr(node, "name", ""))
    if isinstance(debug_value, dict):
        return dict(debug_value)
    return {}
