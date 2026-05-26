from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from mcp.server.fastmcp import Context

from mcp_server.auth import BearerTokenMiddleware, FastMCPRequestAuthenticator, MCPAccessTokenVerifier
from mcp_server.config import MCPSettings
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
        effective_roles_resolver=lambda user_id, workspace_id=None: {
            "query_studio:user",
            "queryforge_mcp:user",
            "queryforge_mcp:preview",
        },
        workspace_feature_checker=lambda workspace_id, feature_key: feature_key == "query_studio",
        mcp_access_service=SimpleNamespace(
            assert_mcp_enabled=lambda workspace_id: {
                "workspace_id": workspace_id,
                "enabled": True,
                "default_preview_row_limit": 100,
                "max_preview_row_limit": 500,
            },
            get_app_grant=lambda **_: None,
        ),
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
        mcp_access_service=SimpleNamespace(assert_mcp_enabled=lambda workspace_id: {}, get_app_grant=lambda **_: None),
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
        mcp_access_service=SimpleNamespace(assert_mcp_enabled=lambda workspace_id: {}, get_app_grant=lambda **_: None),
    )

    with pytest.raises(MCPError) as exc_info:
        auth.resolve("", _ctx({"Authorization": "Bearer good-token"}))

    assert exc_info.value.error_code == "INVALID_WORKSPACE"


def test_authenticator_rejects_user_without_mcp_channel_role():
    auth = FastMCPRequestAuthenticator(
        token_verifier=lambda token: {"sub": "user-1", "scope": "qf:mcp:read"} if token == "good-token" else None,
        workspace_access_service=SimpleNamespace(assert_workspace_access=lambda **_: None),
        domain_explorer_service=SimpleNamespace(list_domains=lambda **_: []),
        effective_roles_resolver=lambda user_id, workspace_id=None: {"workspace_admin", "query_studio:user"},
        workspace_feature_checker=lambda workspace_id, feature_key: True,
        mcp_access_service=SimpleNamespace(
            assert_mcp_enabled=lambda workspace_id: {
                "workspace_id": workspace_id,
                "enabled": True,
                "default_preview_row_limit": 100,
                "max_preview_row_limit": 500,
            },
            get_app_grant=lambda **_: None,
        ),
    )

    with pytest.raises(MCPError) as exc_info:
        auth.resolve("ws-1", _ctx({"Authorization": "Bearer good-token"}))

    assert exc_info.value.error_code == "FORBIDDEN"
    assert "queryforge_mcp:user" in exc_info.value.message


def test_authenticator_user_preview_requires_mcp_preview_role_and_query_studio():
    auth = FastMCPRequestAuthenticator(
        token_verifier=lambda token: {
            "sub": "user-1",
            "scope": "qf:mcp:read qf:mcp:plan qf:mcp:preview",
        }
        if token == "good-token"
        else None,
        workspace_access_service=SimpleNamespace(assert_workspace_access=lambda **_: None),
        domain_explorer_service=SimpleNamespace(list_domains=lambda **_: [{"key": "students"}]),
        effective_roles_resolver=lambda user_id, workspace_id=None: {
            "queryforge_mcp:user",
            "queryforge_mcp:preview",
            "query_studio:user",
        },
        workspace_feature_checker=lambda workspace_id, feature_key: feature_key == "query_studio",
        mcp_access_service=SimpleNamespace(
            assert_mcp_enabled=lambda workspace_id: {
                "workspace_id": workspace_id,
                "enabled": True,
                "default_preview_row_limit": 100,
                "max_preview_row_limit": 250,
            },
            get_app_grant=lambda **_: None,
        ),
    )

    resolved = auth.resolve("ws-1", _ctx({"Authorization": "Bearer good-token"}))

    assert resolved.principal_type == "user"
    assert resolved.oauth_scopes == ["qf:mcp:read", "qf:mcp:plan", "qf:mcp:preview"]
    assert resolved.can_preview is True
    assert resolved.preview_row_limit == 250


def test_authenticator_resolves_app_principal_from_active_grant():
    auth = FastMCPRequestAuthenticator(
        token_verifier=lambda token: {
            "sub": "app-1",
            "principal_type": "app",
            "scope": "qf:mcp:read qf:mcp:preview",
        }
        if token == "app-token"
        else None,
        workspace_access_service=SimpleNamespace(assert_workspace_access=lambda **_: None),
        domain_explorer_service=SimpleNamespace(list_domains=lambda **_: []),
        effective_roles_resolver=lambda user_id, workspace_id=None: set(),
        workspace_feature_checker=lambda workspace_id, feature_key: False,
        mcp_access_service=SimpleNamespace(
            assert_mcp_enabled=lambda workspace_id: {
                "workspace_id": workspace_id,
                "enabled": True,
                "default_preview_row_limit": 100,
                "max_preview_row_limit": 500,
            },
            get_app_grant=lambda principal_type, principal_id, workspace_id: {
                "principal_type": principal_type,
                "principal_id": principal_id,
                "workspace_id": workspace_id,
                "allowed_tools": ["search_domains", "preview_query"],
                "allowed_domain_keys": ["students"],
                "can_preview": True,
                "preview_row_limit": 25,
            },
        ),
    )

    resolved = auth.resolve("ws-1", _ctx({"Authorization": "Bearer app-token"}))

    assert resolved.user_id == "app-1"
    assert resolved.principal_type == "app"
    assert resolved.allowed_tools == ["preview_query", "search_domains"]
    assert resolved.allowed_domain_keys == ["students"]
    assert resolved.can_preview is True
    assert resolved.preview_row_limit == 25


def test_mcp_access_token_verifier_accepts_resource_bound_mcp_access_token():
    verifier = MCPAccessTokenVerifier(
        settings=MCPSettings(resource_url="https://mcp.query-forge.com"),
        decoder=lambda token: {
            "typ": "mcp_access",
            "sub": "user-1",
            "aud": "https://mcp.query-forge.com",
            "scope": "qf:mcp:read qf:mcp:preview",
        }
        if token == "mcp-token"
        else None,
    )

    payload = verifier.verify("mcp-token")

    assert payload is not None
    assert payload["sub"] == "user-1"
    assert payload["typ"] == "mcp_access"


@pytest.mark.parametrize(
    "payload",
    [
        {"typ": "access", "sub": "user-1", "aud": "https://mcp.query-forge.com"},
        {"typ": "mcp_access", "sub": "user-1", "aud": "https://api.query-forge.com"},
        {"typ": "mcp_access", "sub": "user-1"},
        {"typ": "mcp_access", "aud": "https://mcp.query-forge.com"},
    ],
)
def test_mcp_access_token_verifier_rejects_wrong_type_audience_or_subject(payload):
    verifier = MCPAccessTokenVerifier(
        settings=MCPSettings(resource_url="https://mcp.query-forge.com"),
        decoder=lambda token: payload,
    )

    assert verifier.verify("bad-token") is None


def test_bearer_token_middleware_returns_www_authenticate_challenge_for_missing_token():
    app = Starlette()
    app.add_route("/mcp", lambda request: JSONResponse({"ok": True}), methods=["POST"])
    app.add_middleware(
        BearerTokenMiddleware,
        token_verifier=lambda token: None,
        settings=MCPSettings(resource_url="https://mcp.query-forge.com"),
    )

    response = TestClient(app).post("/mcp")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")
    assert 'resource_metadata="https://mcp.query-forge.com/.well-known/oauth-protected-resource"' in response.headers["WWW-Authenticate"]


def test_bearer_token_middleware_allows_public_protected_resource_metadata_path():
    app = Starlette()
    app.add_route(
        "/.well-known/oauth-protected-resource",
        lambda request: JSONResponse({"resource": "https://mcp.query-forge.com"}),
        methods=["GET"],
    )
    app.add_middleware(
        BearerTokenMiddleware,
        token_verifier=lambda token: None,
        settings=MCPSettings(resource_url="https://mcp.query-forge.com"),
    )

    response = TestClient(app).get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    assert response.json() == {"resource": "https://mcp.query-forge.com"}
