from __future__ import annotations

from types import SimpleNamespace

import pytest

from mcp.server.fastmcp import Context

from mcp_server.auth import FastMCPRequestAuthenticator
from mcp_server.exceptions import MCPError


def _ctx(headers: dict[str, str], request_id: str = "trace-123") -> Context:
    request = SimpleNamespace(headers=headers, state=SimpleNamespace())
    request_context = SimpleNamespace(request=request, request_id=request_id)
    return Context(request_context=request_context, fastmcp=None)


def test_authenticator_resolves_workspace_and_domain_access():
    auth = FastMCPRequestAuthenticator(
        token_verifier=lambda token: {"user_id": "user-1"} if token == "good-token" else None,
        workspace_access_service=SimpleNamespace(
            assert_workspace_access=lambda user_id, workspace_id: workspace_id
        ),
        domain_explorer_service=SimpleNamespace(
            list_domains=lambda workspace_id, user_id: [
                {"key": "students"},
                {"key": "schools"},
            ]
        ),
        effective_roles_resolver=lambda user_id, workspace_id=None: {"query_studio:user"},
        workspace_feature_checker=lambda workspace_id, feature_key: feature_key == "query_studio",
    )

    resolved = auth.resolve("ws-1", _ctx({"Authorization": "Bearer good-token"}))

    assert resolved.user_id == "user-1"
    assert resolved.workspace_id == "ws-1"
    assert resolved.allowed_domain_keys == ["schools", "students"]
    assert resolved.can_preview is True
    assert resolved.can_run_saved_queries is True
    assert resolved.trace_id == "trace-123"


def test_authenticator_rejects_missing_bearer_token():
    auth = FastMCPRequestAuthenticator(
        token_verifier=lambda token: None,
        workspace_access_service=SimpleNamespace(assert_workspace_access=lambda **_: None),
        domain_explorer_service=SimpleNamespace(list_domains=lambda **_: []),
        effective_roles_resolver=lambda user_id, workspace_id=None: set(),
        workspace_feature_checker=lambda workspace_id, feature_key: False,
    )

    with pytest.raises(MCPError) as exc_info:
        auth.resolve("ws-1", _ctx({}))

    assert exc_info.value.error_code == "UNAUTHORIZED"


def test_authenticator_rejects_invalid_workspace_id():
    auth = FastMCPRequestAuthenticator(
        token_verifier=lambda token: {"user_id": "user-1"},
        workspace_access_service=SimpleNamespace(assert_workspace_access=lambda **_: None),
        domain_explorer_service=SimpleNamespace(list_domains=lambda **_: []),
        effective_roles_resolver=lambda user_id, workspace_id=None: set(),
        workspace_feature_checker=lambda workspace_id, feature_key: False,
    )

    with pytest.raises(MCPError) as exc_info:
        auth.resolve("", _ctx({"Authorization": "Bearer good-token"}))

    assert exc_info.value.error_code == "INVALID_WORKSPACE"
