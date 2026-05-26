from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib

import pytest

from app.config.mcp_oauth_config import MCPOAuthConfig
from app.exceptions.forge_error import ForgeError
from app.services.mcp_oauth.token_service import OAuthTokenService


class _OAuthClientRepository:
    def __init__(self, client=None) -> None:
        self.client = client or {
            "client_id": "client-123",
            "client_secret_hash": None,
            "redirect_uris": ["https://chatgpt.com/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "qf:mcp:read qf:mcp:plan",
            "token_endpoint_auth_method": "none",
        }

    def get_active_client(self, *, client_id, now):
        assert now is not None
        if client_id != self.client["client_id"]:
            return None
        return self.client


class _AuthorizationCodeService:
    def __init__(self, row=None) -> None:
        self.row = row or {
            "client_id": "client-123",
            "principal_type": "user",
            "principal_id": "user-1",
            "redirect_uri": "https://chatgpt.com/callback",
            "resource": "https://mcp.query-forge.com",
            "scope": "qf:mcp:read qf:mcp:plan",
            "code_challenge": _s256_challenge("verifier-1"),
            "code_challenge_method": "S256",
        }
        self.consumed_codes = []

    def consume_authorization_code(self, code):
        self.consumed_codes.append(code)
        return dict(self.row) if self.row else None


class _RefreshTokenRepository:
    def __init__(self, row=None) -> None:
        self.created_payloads = []
        self.row = row
        self.rotations = []
        self.revocations = []

    def create_refresh_token(self, *, payload):
        self.created_payloads.append(dict(payload))

    def get_active_refresh_token(self, *, token_hash, now):
        assert now is not None
        if self.row and token_hash == self.row["token_hash"]:
            return dict(self.row)
        return None

    def rotate_refresh_token(self, *, token_hash, replacement_hash, now):
        self.rotations.append(
            {
                "token_hash": token_hash,
                "replacement_hash": replacement_hash,
                "now": now,
            }
        )
        return True

    def revoke_refresh_token(self, *, token_hash, now):
        self.revocations.append({"token_hash": token_hash, "now": now})
        return token_hash == "known-hash"


class _AppClientRepository:
    def __init__(self, client=None) -> None:
        self.client = client or {
            "client_id": "app-1",
            "client_secret_hash": hashlib.sha256(b"app-secret").hexdigest(),
            "display_name": "Customer App",
            "owning_workspace_id": "ws-1",
        }
        self.touched = []

    def get_active_client(self, *, client_id, now):
        assert now is not None
        if client_id == self.client["client_id"]:
            return dict(self.client)
        return None

    def touch_last_used(self, *, client_id, now):
        self.touched.append({"client_id": client_id, "now": now})
        return True


class _AuthService:
    def __init__(self) -> None:
        self.payloads = []

    def _encode(self, payload):
        self.payloads.append(dict(payload))
        return "encoded-access-token"


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


def _s256_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    import base64

    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def test_exchange_authorization_code_issues_mcp_access_and_refresh_tokens():
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    auth = _AuthService()
    refresh_repo = _RefreshTokenRepository()
    service = OAuthTokenService(
        config_loader=lambda: _config(),
        client_repository=_OAuthClientRepository(),
        authorization_code_service=_AuthorizationCodeService(),
        refresh_token_repository=refresh_repo,
        auth_service=auth,
        refresh_token_generator=lambda: "plain-refresh-token",
        jti_generator=lambda: "jti-1",
        now_provider=lambda: now,
    )

    result = service.issue_token(
        {
            "grant_type": "authorization_code",
            "client_id": "client-123",
            "code": "auth-code-1",
            "redirect_uri": "https://chatgpt.com/callback",
            "resource": "https://mcp.query-forge.com",
            "code_verifier": "verifier-1",
        }
    )

    assert result["access_token"] == "encoded-access-token"
    assert result["refresh_token"] == "plain-refresh-token"
    assert result["token_type"] == "Bearer"
    assert result["expires_in"] == 3600
    assert result["scope"] == "qf:mcp:read qf:mcp:plan"
    access_payload = auth.payloads[0]
    assert access_payload["typ"] == "mcp_access"
    assert access_payload["iss"] == "https://api.query-forge.com"
    assert access_payload["aud"] == "https://mcp.query-forge.com"
    assert access_payload["sub"] == "user-1"
    assert access_payload["client_id"] == "client-123"
    assert access_payload["scope"] == "qf:mcp:read qf:mcp:plan"
    assert access_payload["exp"] == now + timedelta(seconds=3600)
    assert refresh_repo.created_payloads[0]["token_hash"] == hashlib.sha256(b"plain-refresh-token").hexdigest()
    assert refresh_repo.created_payloads[0]["expires_at"] == now + timedelta(seconds=1209600)


def test_exchange_authorization_code_rejects_bad_pkce_verifier():
    service = OAuthTokenService(
        config_loader=lambda: _config(),
        client_repository=_OAuthClientRepository(),
        authorization_code_service=_AuthorizationCodeService(),
    )

    with pytest.raises(ForgeError) as exc_info:
        service.issue_token(
            {
                "grant_type": "authorization_code",
                "client_id": "client-123",
                "code": "auth-code-1",
                "redirect_uri": "https://chatgpt.com/callback",
                "resource": "https://mcp.query-forge.com",
                "code_verifier": "wrong",
            }
        )

    assert exc_info.value.status_code == 400
    assert "Invalid code_verifier" in str(exc_info.value)


def test_exchange_authorization_code_requires_confidential_client_secret():
    client = {
        "client_id": "client-123",
        "client_secret_hash": hashlib.sha256(b"secret-1").hexdigest(),
        "redirect_uris": ["https://chatgpt.com/callback"],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "scope": "qf:mcp:read",
        "token_endpoint_auth_method": "client_secret_post",
    }
    service = OAuthTokenService(
        config_loader=lambda: _config(),
        client_repository=_OAuthClientRepository(client=client),
        authorization_code_service=_AuthorizationCodeService(),
    )

    with pytest.raises(ForgeError) as exc_info:
        service.issue_token(
            {
                "grant_type": "authorization_code",
                "client_id": "client-123",
                "client_secret": "wrong",
                "code": "auth-code-1",
                "redirect_uri": "https://chatgpt.com/callback",
                "resource": "https://mcp.query-forge.com",
                "code_verifier": "verifier-1",
            }
        )

    assert exc_info.value.status_code == 401
    assert "Invalid client authentication" in str(exc_info.value)


def test_refresh_token_rotates_persisted_refresh_token_and_issues_new_access_token():
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    old_refresh = "old-refresh-token"
    row = {
        "token_hash": hashlib.sha256(old_refresh.encode("utf-8")).hexdigest(),
        "client_id": "client-123",
        "principal_type": "user",
        "principal_id": "user-1",
        "resource": "https://mcp.query-forge.com",
        "scope": "qf:mcp:read",
    }
    refresh_repo = _RefreshTokenRepository(row=row)
    auth = _AuthService()
    service = OAuthTokenService(
        config_loader=lambda: _config(),
        client_repository=_OAuthClientRepository(),
        refresh_token_repository=refresh_repo,
        auth_service=auth,
        refresh_token_generator=lambda: "new-refresh-token",
        jti_generator=lambda: "jti-2",
        now_provider=lambda: now,
    )

    result = service.issue_token(
        {
            "grant_type": "refresh_token",
            "client_id": "client-123",
            "refresh_token": old_refresh,
        }
    )

    assert result["access_token"] == "encoded-access-token"
    assert result["refresh_token"] == "new-refresh-token"
    assert refresh_repo.rotations[0]["token_hash"] == row["token_hash"]
    assert refresh_repo.rotations[0]["replacement_hash"] == hashlib.sha256(b"new-refresh-token").hexdigest()
    assert refresh_repo.created_payloads[0]["scope"] == "qf:mcp:read"
    assert auth.payloads[0]["jti"] == "jti-2"


def test_refresh_token_grant_can_be_disabled():
    service = OAuthTokenService(config_loader=lambda: _config(oauth_enable_refresh_tokens=False))

    with pytest.raises(ForgeError) as exc_info:
        service.issue_token(
            {
                "grant_type": "refresh_token",
                "client_id": "client-123",
                "refresh_token": "old-refresh-token",
            }
        )

    assert exc_info.value.status_code == 400
    assert "refresh_token grant is disabled" in str(exc_info.value)


def test_revoke_token_marks_refresh_token_revoked_by_hash():
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    refresh_repo = _RefreshTokenRepository()
    service = OAuthTokenService(
        refresh_token_repository=refresh_repo,
        now_provider=lambda: now,
    )

    result = service.revoke_token({"token": "known-token", "token_type_hint": "refresh_token"})

    assert result == {"revoked": True}
    assert refresh_repo.revocations == [
        {
            "token_hash": hashlib.sha256(b"known-token").hexdigest(),
            "now": now,
        }
    ]


def test_client_credentials_issues_mcp_access_token_for_active_app_client():
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    auth = _AuthService()
    app_repo = _AppClientRepository()
    service = OAuthTokenService(
        config_loader=lambda: _config(oauth_enable_app_client_auth=True),
        app_client_repository=app_repo,
        auth_service=auth,
        jti_generator=lambda: "app-jti-1",
        now_provider=lambda: now,
    )

    result = service.issue_token(
        {
            "grant_type": "client_credentials",
            "client_id": "app-1",
            "client_secret": "app-secret",
            "scope": "qf:mcp:read qf:mcp:plan",
            "resource": "https://mcp.query-forge.com",
        }
    )

    assert result == {
        "access_token": "encoded-access-token",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "qf:mcp:read qf:mcp:plan",
    }
    access_payload = auth.payloads[0]
    assert access_payload["typ"] == "mcp_access"
    assert access_payload["principal_type"] == "app"
    assert access_payload["sub"] == "app-1"
    assert access_payload["client_id"] == "app-1"
    assert access_payload["aud"] == "https://mcp.query-forge.com"
    assert app_repo.touched == [{"client_id": "app-1", "now": now}]


def test_client_credentials_can_be_disabled():
    service = OAuthTokenService(config_loader=lambda: _config(oauth_enable_app_client_auth=False))

    with pytest.raises(ForgeError) as exc_info:
        service.issue_token(
            {
                "grant_type": "client_credentials",
                "client_id": "app-1",
                "client_secret": "app-secret",
            }
        )

    assert exc_info.value.status_code == 400
    assert "client_credentials grant is disabled" in str(exc_info.value)
