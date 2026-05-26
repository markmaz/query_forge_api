from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from mcp_server.config import MCPSettings
from mcp_server.context import RequestContext
from mcp_server.exceptions import MCPError
from mcp_server.rate_limit import MCPRateLimiter


class _Limiter:
    def __init__(self, fail_scope: str | None = None) -> None:
        self.calls = []
        self.fail_scope = fail_scope

    def enforce(self, *, scope, identifier, max_attempts, window_s, message):
        self.calls.append(
            {
                "scope": scope,
                "identifier": identifier,
                "max_attempts": max_attempts,
                "window_s": window_s,
                "message": message,
            }
        )
        if scope == self.fail_scope:
            raise ForgeError(message, status_code=429, details={"retry_after_seconds": 42})


def _ctx(**overrides) -> RequestContext:
    payload = {
        "user_id": "user-1",
        "workspace_id": "ws-1",
        "allowed_domain_keys": ["students"],
        "can_preview": True,
        "can_run_saved_queries": True,
        "trace_id": "trace-1",
        "effective_roles": ["queryforge_mcp:user", "queryforge_mcp:preview"],
        "is_admin": False,
        "principal_type": "user",
        "principal_id": "user-1",
        "client_id": "client-1",
        "oauth_scopes": ["qf:mcp:read", "qf:mcp:plan", "qf:mcp:preview"],
        "allowed_tools": [],
        "preview_row_limit": 100,
    }
    payload.update(overrides)
    return RequestContext(**payload)


def test_mcp_rate_limiter_enforces_user_client_and_preview_buckets():
    limiter = _Limiter()
    service = MCPRateLimiter(
        settings=MCPSettings(
            rate_limit_per_user_per_minute=2,
            rate_limit_per_client_per_minute=3,
            rate_limit_preview_per_user_per_minute=1,
        ),
        rate_limit_service=limiter,
    )

    buckets = service.enforce(name="preview_query", request_context=_ctx())

    assert buckets == [
        "mcp:user:user:user-1",
        "mcp:client:client-1",
        "mcp:preview:user:user-1",
    ]
    assert [call["max_attempts"] for call in limiter.calls] == [2, 3, 1]
    assert all(call["window_s"] == 60 for call in limiter.calls)


def test_mcp_rate_limiter_raises_mcp_rate_limited_error():
    service = MCPRateLimiter(
        settings=MCPSettings(rate_limit_per_user_per_minute=1),
        rate_limit_service=_Limiter(fail_scope="mcp:user"),
    )

    with pytest.raises(MCPError) as exc_info:
        service.enforce(name="search_domains", request_context=_ctx())

    assert exc_info.value.error_code == "RATE_LIMITED"
    assert exc_info.value.status_code == 429
    assert exc_info.value.details["retry_after_seconds"] == 42
