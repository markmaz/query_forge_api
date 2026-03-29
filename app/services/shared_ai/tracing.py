from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence


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
