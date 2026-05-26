from __future__ import annotations

from typing import Any

from app.config.mcp_oauth_config import MCP_OAUTH_SCOPES, load_mcp_oauth_config


def authorization_server_metadata() -> dict[str, Any]:
    config = load_mcp_oauth_config()
    issuer = config.oauth_issuer_url.rstrip("/")
    grant_types = ["authorization_code", "client_credentials"]
    if config.oauth_enable_refresh_tokens:
        grant_types.insert(1, "refresh_token")

    metadata: dict[str, Any] = {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "revocation_endpoint": f"{issuer}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": grant_types,
        "code_challenge_methods_supported": list(config.oauth_allowed_code_challenge_methods),
        "scopes_supported": list(MCP_OAUTH_SCOPES),
        "token_endpoint_auth_methods_supported": [
            "none",
            "client_secret_basic",
            "client_secret_post",
        ],
        "service_documentation": f"{issuer}/docs/mcp",
    }
    if config.oauth_enable_dynamic_client_registration:
        metadata["registration_endpoint"] = f"{issuer}/oauth/register"
    return metadata
