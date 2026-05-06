from __future__ import annotations

import pytest

from mcp_server.access_policy import authorize_mcp_operation
from mcp_server.context import RequestContext
from mcp_server.exceptions import MCPError


def _ctx(**overrides) -> RequestContext:
    payload = {
        "user_id": "user-1",
        "workspace_id": "ws-1",
        "allowed_domain_keys": ["students"],
        "can_preview": False,
        "can_run_saved_queries": False,
        "trace_id": "trace-1",
        "effective_roles": ["queryforge_mcp:user"],
        "is_admin": False,
        "principal_type": "user",
        "principal_id": "user-1",
        "oauth_scopes": ["qf:mcp:read", "qf:mcp:plan"],
        "allowed_tools": [],
        "preview_row_limit": 100,
    }
    payload.update(overrides)
    return RequestContext(**payload)


def test_authorize_mcp_operation_requires_preview_scope_and_permission():
    with pytest.raises(MCPError) as exc_info:
        authorize_mcp_operation(
            kind="tool",
            name="preview_query",
            request_context=_ctx(),
            request_summary={"workspace_id": "ws-1", "plan": {"domain_key": "students"}},
        )

    assert exc_info.value.error_code == "FORBIDDEN"
    assert "qf:mcp:preview" in exc_info.value.message


def test_authorize_mcp_operation_rejects_app_tool_outside_grant():
    with pytest.raises(MCPError) as exc_info:
        authorize_mcp_operation(
            kind="tool",
            name="compile_query",
            request_context=_ctx(
                principal_type="app",
                principal_id="app-1",
                user_id="app-1",
                allowed_tools=["search_domains"],
            ),
            request_summary={"workspace_id": "ws-1", "plan": {"domain_key": "students"}},
        )

    assert exc_info.value.error_code == "FORBIDDEN"
    assert "not granted" in exc_info.value.message


def test_authorize_mcp_operation_rejects_app_domain_outside_grant():
    with pytest.raises(MCPError) as exc_info:
        authorize_mcp_operation(
            kind="tool",
            name="plan_query",
            request_context=_ctx(
                principal_type="app",
                principal_id="app-1",
                user_id="app-1",
                allowed_tools=["plan_query"],
                allowed_domain_keys=["students"],
            ),
            request_summary={"workspace_id": "ws-1", "domain_key": "finance"},
        )

    assert exc_info.value.error_code == "FORBIDDEN"
    assert "Domain is not granted" in exc_info.value.message


def test_authorize_mcp_operation_allows_granted_app_preview_tool():
    authorize_mcp_operation(
        kind="tool",
        name="preview_query",
        request_context=_ctx(
            principal_type="app",
            principal_id="app-1",
            user_id="app-1",
            oauth_scopes=["qf:mcp:read", "qf:mcp:plan", "qf:mcp:preview"],
            allowed_tools=["preview_query"],
            allowed_domain_keys=["students"],
            can_preview=True,
        ),
        request_summary={"workspace_id": "ws-1", "plan": {"domain_key": "students"}},
    )
