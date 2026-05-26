from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config.mcp_oauth_config import MCPOAuthConfig
from app.exceptions.forge_error import ForgeError
from app.services.mcp_oauth.dynamic_client_registration_service import DynamicClientRegistrationService


class _OAuthClientRepository:
    def __init__(self) -> None:
        self.created_payloads = []
        self.cleanup_calls = []

    def create_client(self, *, payload):
        self.created_payloads.append(dict(payload))

    def delete_expired_clients(self, *, now):
        self.cleanup_calls.append(now)
        return 2


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
        "oauth_allowed_redirect_hosts": ("chatgpt.com", "chat.openai.com"),
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


def test_register_public_client_persists_normalized_metadata():
    repo = _OAuthClientRepository()
    service = DynamicClientRegistrationService(
        config_loader=lambda: _config(),
        repository=repo,
        id_generator=lambda: "client-123",
        now_provider=lambda: 1_777_000_000,
    )

    result = service.register_client(
        {
            "client_name": "ChatGPT QueryForge",
            "redirect_uris": ["https://chatgpt.com/aip/g-abc/oauth/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "qf:mcp:read qf:mcp:preview",
            "token_endpoint_auth_method": "none",
            "contacts": ["admin@example.com"],
        }
    )

    assert result["client_id"] == "client-123"
    assert result["client_id_issued_at"] == 1_777_000_000
    assert result["redirect_uris"] == ["https://chatgpt.com/aip/g-abc/oauth/callback"]
    assert result["grant_types"] == ["authorization_code", "refresh_token"]
    assert result["response_types"] == ["code"]
    assert "client_secret" not in result
    assert repo.cleanup_calls == [datetime.fromtimestamp(1_777_000_000, tz=timezone.utc)]
    assert repo.created_payloads[0]["client_id"] == "client-123"
    assert repo.created_payloads[0]["client_secret_hash"] is None
    assert repo.created_payloads[0]["expires_at"] is not None


def test_register_confidential_client_issues_secret_and_hashes_stored_secret():
    repo = _OAuthClientRepository()
    service = DynamicClientRegistrationService(
        config_loader=lambda: _config(),
        repository=repo,
        id_generator=lambda: "client-456",
        secret_generator=lambda: "plain-secret",
        now_provider=lambda: 1_777_000_000,
    )

    result = service.register_client(
        {
            "client_name": "Internal Tool",
            "redirect_uris": ["https://chat.openai.com/oauth/callback"],
            "token_endpoint_auth_method": "client_secret_post",
        }
    )

    assert result["client_secret"] == "plain-secret"
    assert result["client_secret_expires_at"] == 0
    assert result["scope"] == "qf:mcp:read qf:mcp:plan qf:mcp:preview"
    assert repo.created_payloads[0]["client_secret_hash"] != "plain-secret"
    assert len(repo.created_payloads[0]["client_secret_hash"]) == 64


def test_register_client_allows_loopback_redirects_when_enabled():
    repo = _OAuthClientRepository()
    service = DynamicClientRegistrationService(
        config_loader=lambda: _config(oauth_allow_loopback_redirects=True),
        repository=repo,
        id_generator=lambda: "client-loopback",
        now_provider=lambda: 1_777_000_000,
    )

    result = service.register_client(
        {
            "client_name": "Local Codex",
            "redirect_uris": [
                "http://localhost:1455/oauth/callback",
                "http://127.0.0.1:1455/oauth/callback",
                "http://[::1]:1455/oauth/callback",
            ],
            "token_endpoint_auth_method": "none",
        }
    )

    assert result["redirect_uris"] == [
        "http://127.0.0.1:1455/oauth/callback",
        "http://[::1]:1455/oauth/callback",
        "http://localhost:1455/oauth/callback",
    ]
    assert repo.created_payloads[0]["redirect_uris"] == result["redirect_uris"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "redirect_uris is required"),
        ({"redirect_uris": ["not-a-url"]}, "redirect_uris must contain valid absolute HTTPS URLs"),
        ({"redirect_uris": ["http://chatgpt.com/callback"]}, "redirect_uris must contain valid absolute HTTPS URLs"),
        ({"redirect_uris": ["http://localhost:1455/oauth/callback"]}, "redirect_uris must contain valid absolute HTTPS URLs"),
        ({"redirect_uris": ["https://evil.example/callback"]}, "redirect_uri host is not allowed"),
        ({"redirect_uris": ["https://chatgpt.com/callback"], "response_types": ["token"]}, "response_types must be code"),
        ({"redirect_uris": ["https://chatgpt.com/callback"], "grant_types": ["implicit"]}, "grant_types contains unsupported values"),
        ({"redirect_uris": ["https://chatgpt.com/callback"], "scope": "qf:mcp:read admin"}, "scope contains unsupported values"),
        ({"redirect_uris": ["https://chatgpt.com/callback"], "token_endpoint_auth_method": "private_key_jwt"}, "Unsupported token_endpoint_auth_method"),
    ],
)
def test_register_client_rejects_invalid_metadata(payload, message):
    service = DynamicClientRegistrationService(config_loader=lambda: _config())

    with pytest.raises(ForgeError) as exc_info:
        service.register_client(payload)

    assert message in str(exc_info.value)
    assert exc_info.value.status_code == 400


def test_register_client_can_be_disabled_by_runtime_config():
    service = DynamicClientRegistrationService(
        config_loader=lambda: _config(oauth_enable_dynamic_client_registration=False)
    )

    with pytest.raises(ForgeError) as exc_info:
        service.register_client({"redirect_uris": ["https://chatgpt.com/callback"]})

    assert exc_info.value.status_code == 404
