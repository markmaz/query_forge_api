from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if raw == "":
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if raw == "":
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


def _env_csv(name: str) -> Tuple[str, ...]:
    raw = str(os.getenv(name, "") or "").strip()
    if raw == "":
        return ()
    return tuple(part.strip().rstrip("/") for part in raw.split(",") if part.strip())


def _env_url(name: str, default: str) -> str:
    raw = str(os.getenv(name, default) or default).strip()
    return raw.rstrip("/") or default.rstrip("/")


def _read_backend_version() -> str:
    version_path = Path(__file__).resolve().parents[1] / "version.json"
    try:
        payload = json.loads(version_path.read_text())
    except (OSError, json.JSONDecodeError):
        return "0.0.0"
    return str(payload.get("version") or "0.0.0").strip() or "0.0.0"


@dataclass(frozen=True)
class MCPSettings:
    server_name: str = "QueryForge MCP"
    server_version: str = "1.0.0"
    include_raw_sql: bool = False
    preview_default_limit: int = 100
    preview_hard_limit: int = 500
    preview_timeout_seconds: int = 30
    max_search_results: int = 50
    enable_resources: bool = True
    enable_saved_queries: bool = True
    audit_logging: bool = True
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8001
    mount_path: str = "/"
    streamable_http_path: str = "/mcp"
    stateless_http: bool = True
    json_response: bool = True
    allowed_origins: Tuple[str, ...] = ()
    backend_version: str = "0.0.0"
    resource_url: str = "http://localhost:8001"
    authorization_server_url: str = "http://localhost:5000"
    rate_limit_per_user_per_minute: int = 60
    rate_limit_per_client_per_minute: int = 120
    rate_limit_preview_per_user_per_minute: int = 10
    oauth_scopes_supported: Tuple[str, ...] = (
        "qf:mcp:read",
        "qf:mcp:plan",
        "qf:mcp:preview",
    )

    @classmethod
    def from_env(cls) -> "MCPSettings":
        allowed_origins = _env_csv("MCP_ALLOWED_ORIGINS")
        if not allowed_origins:
            allowed_origins = _env_csv("FRONTEND_ALLOWED_ORIGINS")
        backend_version = _read_backend_version()
        return cls(
            server_name=str(os.getenv("MCP_SERVER_NAME") or "QueryForge MCP").strip() or "QueryForge MCP",
            server_version=str(os.getenv("MCP_SERVER_VERSION") or backend_version).strip() or backend_version,
            include_raw_sql=_env_bool("MCP_INCLUDE_RAW_SQL", False),
            preview_default_limit=max(1, _env_int("MCP_PREVIEW_DEFAULT_LIMIT", 100)),
            preview_hard_limit=max(1, _env_int("MCP_PREVIEW_HARD_LIMIT", 500)),
            preview_timeout_seconds=max(1, _env_int("MCP_PREVIEW_TIMEOUT_SECONDS", 30)),
            max_search_results=max(1, _env_int("MCP_MAX_SEARCH_RESULTS", 50)),
            enable_resources=_env_bool("MCP_ENABLE_RESOURCES", True),
            enable_saved_queries=_env_bool("MCP_ENABLE_SAVED_QUERIES", True),
            audit_logging=_env_bool("MCP_AUDIT_LOGGING", True),
            debug=_env_bool("MCP_DEBUG", False),
            host=str(os.getenv("MCP_HOST") or "0.0.0.0").strip() or "0.0.0.0",
            port=max(1, _env_int("MCP_PORT", 8001)),
            mount_path=str(os.getenv("MCP_MOUNT_PATH") or "/").strip() or "/",
            streamable_http_path=str(os.getenv("MCP_STREAMABLE_HTTP_PATH") or "/mcp").strip() or "/mcp",
            stateless_http=_env_bool("MCP_STATELESS_HTTP", True),
            json_response=_env_bool("MCP_JSON_RESPONSE", True),
            allowed_origins=allowed_origins,
            backend_version=backend_version,
            resource_url=_env_url("MCP_RESOURCE_URL", "http://localhost:8001"),
            authorization_server_url=_env_url(
                "MCP_AUTHORIZATION_SERVER_URL",
                _env_url("OAUTH_ISSUER_URL", "http://localhost:5000"),
            ),
            rate_limit_per_user_per_minute=max(1, _env_int("MCP_RATE_LIMIT_PER_USER_PER_MINUTE", 60)),
            rate_limit_per_client_per_minute=max(1, _env_int("MCP_RATE_LIMIT_PER_CLIENT_PER_MINUTE", 120)),
            rate_limit_preview_per_user_per_minute=max(1, _env_int("MCP_RATE_LIMIT_PREVIEW_PER_USER_PER_MINUTE", 10)),
            oauth_scopes_supported=_env_csv("MCP_OAUTH_SCOPES_SUPPORTED")
            or ("qf:mcp:read", "qf:mcp:plan", "qf:mcp:preview"),
        )
