from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config.mcp_oauth_config import MCPOAuthConfig
from app.exceptions.forge_error import ForgeError
from app.services.mcp_oauth.authorization_code_service import AuthorizationCodeService


class _OAuthClientRepository:
    def __init__(self, client=None) -> None:
        self.client = client or {
            "client_id": "client-123",
            "redirect_uris": ["https://chatgpt.com/callback"],
            "scope": "qf:mcp:read qf:mcp:plan",
            "revoked_at": None,
            "expires_at": None,
        }

    def get_active_client(self, *, client_id, now):
        assert client_id == "client-123"
        assert now is not None
        return self.client


class _AuthorizationCodeRepository:
    def __init__(self) -> None:
        self.created_payloads = []
        self.consumed_hashes = set()
        self.rows_by_hash = {}

    def create_code(self, *, payload):
        self.created_payloads.append(dict(payload))
        self.rows_by_hash[payload["code_hash"]] = dict(payload)

    def consume_code(self, *, code_hash, now):
        if code_hash in self.consumed_hashes:
            return None
        row = self.rows_by_hash.get(code_hash)
        if not row:
            return None
        self.consumed_hashes.add(code_hash)
        return dict(row)


def _config(**overrides) -> MCPOAuthConfig:
    base = {
        "mcp_enabled": False,
        "mcp_require_workspace_enablement": True,
        "mcp_require_channel_grant": True,
        "mcp_require_query_studio_for_preview": True,
        "mcp_include_raw_sql": False,
        "mcp_default_preview_row_limit": 100,
        "mcp_max_preview_row_limit": 500,
        "mcp_rate_limit_per_user_per_minute": 60,
        "mcp_rate_limit_per_client_per_minute": 120,
        "mcp_rate_limit_preview_per_user_per_minute": 10,
        "mcp_block_sensitive_domains": False,
        "mcp_resource_url": "https://mcp.query-forge.com",
        "oauth_issuer_url": "https://api.query-forge.com",
        "oauth_access_token_ttl_seconds": 3600,
        "oauth_auth_code_ttl_seconds": 300,
        "oauth_refresh_token_ttl_seconds": 1209600,
        "oauth_client_ttl_seconds": 2592000,
        "oauth_allowed_redirect_hosts": ("chatgpt.com",),
        "oauth_allow_loopback_redirects": False,
        "oauth_require_pkce": True,
        "oauth_allowed_code_challenge_methods": ("S256",),
        "oauth_enable_dynamic_client_registration": True,
        "oauth_enable_refresh_tokens": True,
        "oauth_consent_expires_with_refresh_token": True,
        "oauth_enable_app_client_auth": True,
    }
    base.update(overrides)
    return MCPOAuthConfig(**base)


def test_validate_authorization_request_requires_registered_redirect_and_pkce():
    service = AuthorizationCodeService(
        config_loader=lambda: _config(),
        client_repository=_OAuthClientRepository(),
    )

    request_ctx = service.validate_authorization_request(
        {
            "response_type": "code",
            "client_id": "client-123",
            "redirect_uri": "https://chatgpt.com/callback",
            "scope": "qf:mcp:read",
            "resource": "https://mcp.query-forge.com",
            "code_challenge": "abc123",
            "code_challenge_method": "S256",
            "state": "state-1",
        }
    )

    assert request_ctx.client_id == "client-123"
    assert request_ctx.redirect_uri == "https://chatgpt.com/callback"
    assert request_ctx.scopes == ["qf:mcp:read"]
    assert request_ctx.state == "state-1"


def test_validate_authorization_request_defaults_missing_resource_to_mcp_resource_url():
    service = AuthorizationCodeService(
        config_loader=lambda: _config(),
        client_repository=_OAuthClientRepository(),
    )

    request_ctx = service.validate_authorization_request(
        {
            "response_type": "code",
            "client_id": "client-123",
            "redirect_uri": "https://chatgpt.com/callback",
            "scope": "qf:mcp:read",
            "code_challenge": "abc123",
            "code_challenge_method": "S256",
        }
    )

    assert request_ctx.resource == "https://mcp.query-forge.com"


@pytest.mark.parametrize(
    ("overrides", "payload", "message"),
    [
        ({}, {"code_challenge": ""}, "code_challenge is required"),
        ({}, {"code_challenge_method": "plain"}, "Unsupported code_challenge_method"),
        ({}, {"redirect_uri": "https://evil.example/callback"}, "redirect_uri is not registered"),
        ({}, {"resource": "https://api.query-forge.com"}, "resource does not match"),
        ({}, {"scope": "qf:mcp:read admin"}, "scope contains unsupported values"),
        ({}, {"response_type": "token"}, "response_type must be code"),
    ],
)
def test_validate_authorization_request_rejects_invalid_oauth_params(overrides, payload, message):
    service = AuthorizationCodeService(
        config_loader=lambda: _config(**overrides),
        client_repository=_OAuthClientRepository(),
    )
    request_payload = {
        "response_type": "code",
        "client_id": "client-123",
        "redirect_uri": "https://chatgpt.com/callback",
        "scope": "qf:mcp:read",
        "resource": "https://mcp.query-forge.com",
        "code_challenge": "abc123",
        "code_challenge_method": "S256",
    }
    request_payload.update(payload)

    with pytest.raises(ForgeError) as exc_info:
        service.validate_authorization_request(request_payload)

    assert message in str(exc_info.value)
    assert exc_info.value.status_code == 400


def test_issue_authorization_code_persists_hash_and_builds_redirect():
    code_repo = _AuthorizationCodeRepository()
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    service = AuthorizationCodeService(
        config_loader=lambda: _config(oauth_auth_code_ttl_seconds=300),
        client_repository=_OAuthClientRepository(),
        code_repository=code_repo,
        code_generator=lambda: "plain-code",
        now_provider=lambda: now,
    )

    redirect_url = service.issue_authorization_code(
        user_id="user-1",
        request_payload={
            "response_type": "code",
            "client_id": "client-123",
            "redirect_uri": "https://chatgpt.com/callback",
            "scope": "qf:mcp:read",
            "resource": "https://mcp.query-forge.com",
            "code_challenge": "abc123",
            "code_challenge_method": "S256",
            "state": "state-1",
        },
    )

    assert redirect_url == "https://chatgpt.com/callback?code=plain-code&state=state-1&resource=https%3A%2F%2Fmcp.query-forge.com"
    persisted = code_repo.created_payloads[0]
    assert persisted["client_id"] == "client-123"
    assert persisted["principal_type"] == "user"
    assert persisted["principal_id"] == "user-1"
    assert persisted["code_hash"] != "plain-code"
    assert persisted["expires_at"] == now + timedelta(seconds=300)


def test_consume_authorization_code_is_one_time_use():
    code_repo = _AuthorizationCodeRepository()
    service = AuthorizationCodeService(
        config_loader=lambda: _config(),
        client_repository=_OAuthClientRepository(),
        code_repository=code_repo,
        code_generator=lambda: "plain-code",
    )
    service.issue_authorization_code(
        user_id="user-1",
        request_payload={
            "response_type": "code",
            "client_id": "client-123",
            "redirect_uri": "https://chatgpt.com/callback",
            "scope": "qf:mcp:read",
            "resource": "https://mcp.query-forge.com",
            "code_challenge": "abc123",
            "code_challenge_method": "S256",
        },
    )

    first = service.consume_authorization_code("plain-code")
    second = service.consume_authorization_code("plain-code")

    assert first is not None
    assert second is None
