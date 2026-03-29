from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from app.services.shared_ai.context import PipelineContext


def build_trace_entry(
    *,
    pipeline_name: str,
    node_name: str,
    status: str,
    ms: int,
    summary: Optional[Mapping[str, Any]] = None,
    error: Optional[str] = None,
    lineage: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    lineage_list = [str(item) for item in list(lineage or [pipeline_name]) if str(item).strip()]
    payload = {
        "pipeline_name": str(pipeline_name),
        "node": str(node_name),
        "status": str(status),
        "ms": int(ms),
        "summary": dict(summary or {}),
        "lineage": lineage_list,
    }
    if len(lineage_list) > 1:
        payload["parent_pipeline"] = lineage_list[-2]
    if error:
        payload["error"] = str(error)
    return payload


def serialize_pipeline_context(context: PipelineContext | None) -> dict[str, Any]:
    if context is None:
        return {}
    return {
        "pipeline_name": str(context.pipeline_name or ""),
        "trace_id": str(context.trace_id or ""),
        "vertical_norm": str(context.vertical_norm or ""),
        "timings_ms": dict(context.timings_ms or {}),
        "debug": dict(context.debug or {}),
        "trace_nodes": [dict(item) for item in list(context.trace_nodes or [])],
        "metadata": dict(context.metadata or {}),
    }
