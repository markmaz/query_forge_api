from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Tuple

MCP_OAUTH_SCOPES = ("qf:mcp:read", "qf:mcp:plan", "qf:mcp:preview")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)


def _env_csv(name: str, default: Tuple[str, ...] = ()) -> Tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return tuple(default)
    return tuple(part.strip() for part in str(raw).split(",") if part.strip())


def _env_url(name: str, default: str) -> str:
    raw = str(os.getenv(name, default) or default).strip()
    return raw.rstrip("/") or default.rstrip("/")


@dataclass(frozen=True)
class MCPOAuthConfig:
    mcp_enabled: bool
    mcp_require_workspace_enablement: bool
    mcp_require_channel_grant: bool
    mcp_require_query_studio_for_preview: bool
    mcp_include_raw_sql: bool
    mcp_default_preview_row_limit: int
    mcp_max_preview_row_limit: int
    mcp_rate_limit_per_user_per_minute: int
    mcp_rate_limit_per_client_per_minute: int
    mcp_rate_limit_preview_per_user_per_minute: int
    mcp_block_sensitive_domains: bool
    mcp_resource_url: str
    oauth_issuer_url: str
    oauth_access_token_ttl_seconds: int
    oauth_auth_code_ttl_seconds: int
    oauth_refresh_token_ttl_seconds: int
    oauth_client_ttl_seconds: int
    oauth_allowed_redirect_hosts: Tuple[str, ...]
    oauth_allow_loopback_redirects: bool
    oauth_require_pkce: bool
    oauth_allowed_code_challenge_methods: Tuple[str, ...]
    oauth_enable_dynamic_client_registration: bool
    oauth_enable_refresh_tokens: bool
    oauth_consent_expires_with_refresh_token: bool
    oauth_enable_app_client_auth: bool


def load_mcp_oauth_config() -> MCPOAuthConfig:
    return MCPOAuthConfig(
        mcp_enabled=_env_bool("MCP_ENABLED", False),
        mcp_require_workspace_enablement=_env_bool("MCP_REQUIRE_WORKSPACE_ENABLEMENT", True),
        mcp_require_channel_grant=_env_bool("MCP_REQUIRE_CHANNEL_GRANT", True),
        mcp_require_query_studio_for_preview=_env_bool("MCP_REQUIRE_QUERY_STUDIO_FOR_PREVIEW", True),
        mcp_include_raw_sql=_env_bool("MCP_INCLUDE_RAW_SQL", False),
        mcp_default_preview_row_limit=max(1, _env_int("MCP_DEFAULT_PREVIEW_ROW_LIMIT", 100)),
        mcp_max_preview_row_limit=max(1, _env_int("MCP_MAX_PREVIEW_ROW_LIMIT", 500)),
        mcp_rate_limit_per_user_per_minute=max(1, _env_int("MCP_RATE_LIMIT_PER_USER_PER_MINUTE", 60)),
        mcp_rate_limit_per_client_per_minute=max(1, _env_int("MCP_RATE_LIMIT_PER_CLIENT_PER_MINUTE", 120)),
        mcp_rate_limit_preview_per_user_per_minute=max(1, _env_int("MCP_RATE_LIMIT_PREVIEW_PER_USER_PER_MINUTE", 10)),
        mcp_block_sensitive_domains=_env_bool("MCP_BLOCK_SENSITIVE_DOMAINS", False),
        mcp_resource_url=_env_url("MCP_RESOURCE_URL", "http://localhost:8001"),
        oauth_issuer_url=_env_url("OAUTH_ISSUER_URL", "http://localhost:5000"),
        oauth_access_token_ttl_seconds=max(1, _env_int("OAUTH_ACCESS_TOKEN_TTL_SECONDS", 3600)),
        oauth_auth_code_ttl_seconds=max(1, _env_int("OAUTH_AUTH_CODE_TTL_SECONDS", 300)),
        oauth_refresh_token_ttl_seconds=max(1, _env_int("OAUTH_REFRESH_TOKEN_TTL_SECONDS", 1209600)),
        oauth_client_ttl_seconds=max(1, _env_int("OAUTH_CLIENT_TTL_SECONDS", 2592000)),
        oauth_allowed_redirect_hosts=_env_csv("OAUTH_ALLOWED_REDIRECT_HOSTS", ("chatgpt.com",)),
        oauth_allow_loopback_redirects=_env_bool("OAUTH_ALLOW_LOOPBACK_REDIRECTS", False),
        oauth_require_pkce=_env_bool("OAUTH_REQUIRE_PKCE", True),
        oauth_allowed_code_challenge_methods=_env_csv("OAUTH_ALLOWED_CODE_CHALLENGE_METHODS", ("S256",)),
        oauth_enable_dynamic_client_registration=_env_bool("OAUTH_ENABLE_DYNAMIC_CLIENT_REGISTRATION", True),
        oauth_enable_refresh_tokens=_env_bool("OAUTH_ENABLE_REFRESH_TOKENS", True),
        oauth_consent_expires_with_refresh_token=_env_bool("OAUTH_CONSENT_EXPIRES_WITH_REFRESH_TOKEN", True),
        oauth_enable_app_client_auth=_env_bool("OAUTH_ENABLE_APP_CLIENT_AUTH", True),
    )


MCP_OAUTH_CONFIG = load_mcp_oauth_config()

__all__ = [
    "MCP_OAUTH_CONFIG",
    "MCP_OAUTH_SCOPES",
    "MCPOAuthConfig",
    "load_mcp_oauth_config",
]
