from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field

from app.exceptions.forge_error import ForgeError
from mcp.server.fastmcp import Context

from mcp_server.config import MCPSettings
from mcp_server.context import RequestContext
from mcp_server.dependencies import MCPDependencies
from mcp_server.resource_registry import execute_resource
from mcp_server.tool_registry import execute_tool


def _request_context() -> RequestContext:
    return RequestContext(
        user_id="user-1",
        workspace_id="ws-1",
        allowed_domain_keys=["students"],
        can_preview=True,
        can_run_saved_queries=True,
        trace_id="trace-1",
        effective_roles=["query_studio:user"],
        is_admin=False,
    )


def _ctx() -> Context:
    request = SimpleNamespace(headers={"Authorization": "Bearer good-token"}, state=SimpleNamespace())
    request_context = SimpleNamespace(request=request, request_id="trace-1")
    return Context(request_context=request_context, fastmcp=None)


class _RowsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[dict[str, object]] = Field(default_factory=list)


def test_execute_tool_returns_model_payload():
    deps = MCPDependencies(
        settings=MCPSettings(audit_logging=False),
        auth_resolver=lambda workspace_id, ctx: _request_context(),
    )

    payload = asyncio.run(
        execute_tool(
            kind="tool",
            name="preview_query",
            workspace_id="ws-1",
            request_summary={"workspace_id": "ws-1"},
            ctx=_ctx(),
            dependencies=deps,
            handler=lambda request_context: _RowsResponse(rows=[{"school_name": "Barksdale"}]),
        )
    )

    assert payload == {"rows": [{"school_name": "Barksdale"}]}


def test_execute_tool_maps_forge_error_payload():
    deps = MCPDependencies(
        settings=MCPSettings(audit_logging=False),
        auth_resolver=lambda workspace_id, ctx: _request_context(),
    )

    def _handler(*, request_context: RequestContext):
        raise ForgeError("Domain was not found", 404)

    payload = asyncio.run(
        execute_tool(
            kind="tool",
            name="get_domain_profile",
            workspace_id="ws-1",
            request_summary={"workspace_id": "ws-1", "domain_key": "missing"},
            ctx=_ctx(),
            dependencies=deps,
            handler=_handler,
        )
    )

    assert payload["error_code"] == "INVALID_DOMAIN"
    assert payload["message"] == "Domain was not found"


def test_execute_resource_serializes_success_payload():
    deps = MCPDependencies(
        settings=MCPSettings(audit_logging=False),
        auth_resolver=lambda workspace_id, ctx: _request_context(),
    )

    payload = asyncio.run(
        execute_resource(
            name="workspace_domains_index",
            workspace_id="ws-1",
            request_summary={"workspace_id": "ws-1"},
            ctx=_ctx(),
            dependencies=deps,
            handler=lambda request_context: {"workspace_id": request_context.workspace_id, "domains": []},
        )
    )

    assert '"workspace_id": "ws-1"' in payload
