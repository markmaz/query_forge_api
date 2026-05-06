from __future__ import annotations

import inspect
import json
from typing import Any, Callable, Mapping

from mcp.server.fastmcp import Context, FastMCP

from .dependencies import MCPDependencies
from .exceptions import map_exception
from .access_policy import authorize_mcp_operation


async def execute_resource(
    *,
    name: str,
    workspace_id: str,
    request_summary: Mapping[str, Any],
    ctx: Context,
    dependencies: MCPDependencies,
    handler: Callable[..., Any],
) -> str:
    audit = dependencies.get_audit_logger()
    started_at = audit.begin()
    request_context = None
    rate_limit_buckets: list[str] = []
    try:
        request_context = dependencies.resolve_request_context(workspace_id, ctx)
        authorize_mcp_operation(
            kind="resource",
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
        payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        audit.emit(
            kind="resource",
            name=name,
            request_context=request_context,
            request_summary=request_summary,
            status="ok",
            started_at=started_at,
            rate_limit_buckets=rate_limit_buckets,
        )
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:
        error = map_exception(exc)
        audit.emit(
            kind="resource",
            name=name,
            request_context=request_context,
            request_summary=request_summary,
            status="error",
            started_at=started_at,
            error_code=error.error_code,
            rate_limit_buckets=rate_limit_buckets,
        )
        return json.dumps(error.to_payload(), ensure_ascii=False)


def register_resources(mcp: FastMCP, dependencies: MCPDependencies) -> None:
    if not dependencies.settings.enable_resources:
        return
    from .resources import domains, policies, saved_queries, semantic_registry

    domains.register(mcp, dependencies)
    policies.register(mcp, dependencies)
    semantic_registry.register(mcp, dependencies)
    saved_queries.register(mcp, dependencies)
