from __future__ import annotations

import inspect
from typing import Any, Callable, Mapping

from mcp.server.fastmcp import Context, FastMCP

from .dependencies import MCPDependencies
from .exceptions import map_exception
from .access_policy import authorize_mcp_operation


async def execute_tool(
    *,
    kind: str,
    name: str,
    workspace_id: str,
    request_summary: Mapping[str, Any],
    ctx: Context,
    dependencies: MCPDependencies,
    handler: Callable[..., Any],
) -> dict[str, Any]:
    audit = dependencies.get_audit_logger()
    started_at = audit.begin()
    request_context = None
    rate_limit_buckets: list[str] = []
    try:
        request_context = dependencies.resolve_request_context(workspace_id, ctx)
        authorize_mcp_operation(
            kind=kind,
            name=name,
            request_context=request_context,
            request_summary=request_summary,
        )
        rate_limit_buckets = dependencies.get_rate_limiter().enforce(
            name=name,
            request_context=request_context,
        )
        result = handler(request_context=request_context)
        if inspect.isawaitable(result):
            result = await result
        payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result or {})
        row_count = None
        if isinstance(payload.get("rows"), list):
            row_count = len(payload["rows"])
        audit.emit(
            kind=kind,
            name=name,
            request_context=request_context,
            request_summary=request_summary,
            status="ok",
            started_at=started_at,
            row_count=row_count,
            rate_limit_buckets=rate_limit_buckets,
        )
        return payload
    except Exception as exc:
        error = map_exception(exc)
        audit.emit(
            kind=kind,
            name=name,
            request_context=request_context,
            request_summary=request_summary,
            status="error",
            started_at=started_at,
            error_code=error.error_code,
            rate_limit_buckets=rate_limit_buckets,
        )
        return error.to_payload()


def register_tools(mcp: FastMCP, dependencies: MCPDependencies) -> None:
    from .tools import dictionary, domains, execution, flowforge, planner, saved_queries

    domains.register(mcp, dependencies)
    dictionary.register(mcp, dependencies)
    planner.register(mcp, dependencies)
    execution.register(mcp, dependencies)
    saved_queries.register(mcp, dependencies)
    flowforge.register(mcp, dependencies)
