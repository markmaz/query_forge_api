from __future__ import annotations

from app.config.mcp_oauth_config import load_mcp_oauth_config


def test_mcp_oauth_config_uses_safe_defaults_when_env_missing(monkeypatch) -> None:
    for key in (
        "MCP_ENABLED",
        "MCP_REQUIRE_WORKSPACE_ENABLEMENT",
        "MCP_REQUIRE_CHANNEL_GRANT",
        "MCP_REQUIRE_QUERY_STUDIO_FOR_PREVIEW",
        "MCP_INCLUDE_RAW_SQL",
        "MCP_DEFAULT_PREVIEW_ROW_LIMIT",
        "MCP_MAX_PREVIEW_ROW_LIMIT",
        "MCP_RATE_LIMIT_PER_USER_PER_MINUTE",
        "MCP_RATE_LIMIT_PER_CLIENT_PER_MINUTE",
        "MCP_RATE_LIMIT_PREVIEW_PER_USER_PER_MINUTE",
        "MCP_BLOCK_SENSITIVE_DOMAINS",
        "MCP_RESOURCE_URL",
        "OAUTH_ISSUER_URL",
        "OAUTH_ACCESS_TOKEN_TTL_SECONDS",
        "OAUTH_AUTH_CODE_TTL_SECONDS",
        "OAUTH_REFRESH_TOKEN_TTL_SECONDS",
        "OAUTH_CLIENT_TTL_SECONDS",
        "OAUTH_ALLOWED_REDIRECT_HOSTS",
        "OAUTH_ALLOW_LOOPBACK_REDIRECTS",
        "OAUTH_REQUIRE_PKCE",
        "OAUTH_ALLOWED_CODE_CHALLENGE_METHODS",
        "OAUTH_ENABLE_DYNAMIC_CLIENT_REGISTRATION",
        "OAUTH_ENABLE_REFRESH_TOKENS",
        "OAUTH_CONSENT_EXPIRES_WITH_REFRESH_TOKEN",
        "OAUTH_ENABLE_APP_CLIENT_AUTH",
    ):
        monkeypatch.delenv(key, raising=False)

    config = load_mcp_oauth_config()

    assert config.mcp_enabled is False
    assert config.mcp_require_workspace_enablement is True
    assert config.mcp_require_channel_grant is True
    assert config.mcp_require_query_studio_for_preview is True
    assert config.mcp_include_raw_sql is False
    assert config.mcp_default_preview_row_limit == 100
    assert config.mcp_max_preview_row_limit == 500
    assert config.mcp_rate_limit_per_user_per_minute == 60
    assert config.mcp_rate_limit_per_client_per_minute == 120
    assert config.mcp_rate_limit_preview_per_user_per_minute == 10
    assert config.mcp_block_sensitive_domains is False
    assert config.mcp_resource_url == "http://localhost:8001"
    assert config.oauth_issuer_url == "http://localhost:5000"
    assert config.oauth_access_token_ttl_seconds == 3600
    assert config.oauth_auth_code_ttl_seconds == 300
    assert config.oauth_refresh_token_ttl_seconds == 1209600
    assert config.oauth_client_ttl_seconds == 2592000
    assert config.oauth_allowed_redirect_hosts == ("chatgpt.com",)
    assert config.oauth_allow_loopback_redirects is False
    assert config.oauth_require_pkce is True
    assert config.oauth_allowed_code_challenge_methods == ("S256",)
    assert config.oauth_enable_dynamic_client_registration is True
    assert config.oauth_enable_refresh_tokens is True
    assert config.oauth_consent_expires_with_refresh_token is True
    assert config.oauth_enable_app_client_auth is True


def test_mcp_oauth_config_normalizes_env_values(monkeypatch) -> None:
    monkeypatch.setenv("MCP_ENABLED", "yes")
    monkeypatch.setenv("MCP_DEFAULT_PREVIEW_ROW_LIMIT", "-5")
    monkeypatch.setenv("MCP_MAX_PREVIEW_ROW_LIMIT", "50")
    monkeypatch.setenv("MCP_RATE_LIMIT_PER_USER_PER_MINUTE", "0")
    monkeypatch.setenv("MCP_RATE_LIMIT_PER_CLIENT_PER_MINUTE", "not-an-int")
    monkeypatch.setenv("MCP_RATE_LIMIT_PREVIEW_PER_USER_PER_MINUTE", "3")
    monkeypatch.setenv("MCP_BLOCK_SENSITIVE_DOMAINS", "true")
    monkeypatch.setenv("MCP_RESOURCE_URL", "https://mcp.query-forge.com/")
    monkeypatch.setenv("OAUTH_ISSUER_URL", "https://api.query-forge.com/")
    monkeypatch.setenv("OAUTH_ALLOWED_REDIRECT_HOSTS", "chatgpt.com, chat.openai.com, ")
    monkeypatch.setenv("OAUTH_ALLOW_LOOPBACK_REDIRECTS", "yes")
    monkeypatch.setenv("OAUTH_ALLOWED_CODE_CHALLENGE_METHODS", "S256,plain")
    monkeypatch.setenv("OAUTH_ENABLE_REFRESH_TOKENS", "0")

    config = load_mcp_oauth_config()

    assert config.mcp_enabled is True
    assert config.mcp_default_preview_row_limit == 1
    assert config.mcp_max_preview_row_limit == 50
    assert config.mcp_rate_limit_per_user_per_minute == 1
    assert config.mcp_rate_limit_per_client_per_minute == 120
    assert config.mcp_rate_limit_preview_per_user_per_minute == 3
    assert config.mcp_block_sensitive_domains is True
    assert config.mcp_resource_url == "https://mcp.query-forge.com"
    assert config.oauth_issuer_url == "https://api.query-forge.com"
    assert config.oauth_allowed_redirect_hosts == ("chatgpt.com", "chat.openai.com")
    assert config.oauth_allow_loopback_redirects is True
    assert config.oauth_allowed_code_challenge_methods == ("S256", "plain")
    assert config.oauth_enable_refresh_tokens is False
