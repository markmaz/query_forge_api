from __future__ import annotations

from typing import Protocol

from app.exceptions.forge_error import ForgeError
from app.services.auth.rate_limit_service import RateLimitService

from .access_policy import PREVIEW_TOOLS
from .config import MCPSettings
from .context import RequestContext
from .exceptions import MCPError


class _RateLimitService(Protocol):
    def enforce(
        self,
        *,
        scope: str,
        identifier: str,
        max_attempts: int,
        window_s: int,
        message: str,
    ) -> None: ...


class MCPRateLimiter:
    def __init__(
        self,
        *,
        settings: MCPSettings,
        rate_limit_service: _RateLimitService | None = None,
    ) -> None:
        self._settings = settings
        self._rate_limits = rate_limit_service or RateLimitService()

    def enforce(self, *, name: str, request_context: RequestContext) -> list[str]:
        buckets = [
            self._enforce_bucket(
                scope="mcp:user",
                identifier=f"{request_context.principal_type}:{request_context.principal_id}",
                max_attempts=self._settings.rate_limit_per_user_per_minute,
            )
        ]
        if request_context.client_id:
            buckets.append(
                self._enforce_bucket(
                    scope="mcp:client",
                    identifier=request_context.client_id,
                    max_attempts=self._settings.rate_limit_per_client_per_minute,
                )
            )
        if name in PREVIEW_TOOLS:
            buckets.append(
                self._enforce_bucket(
                    scope="mcp:preview",
                    identifier=f"{request_context.principal_type}:{request_context.principal_id}",
                    max_attempts=self._settings.rate_limit_preview_per_user_per_minute,
                )
            )
        return buckets

    def _enforce_bucket(self, *, scope: str, identifier: str, max_attempts: int) -> str:
        bucket = f"{scope}:{identifier}"
        try:
            self._rate_limits.enforce(
                scope=scope,
                identifier=identifier,
                max_attempts=max_attempts,
                window_s=60,
                message="MCP rate limit exceeded. Please try again later.",
            )
        except ForgeError as exc:
            if exc.status_code != 429:
                raise
            raise MCPError(
                error_code="RATE_LIMITED",
                message=str(exc),
                details=dict(exc.details or {}),
                status_code=429,
            ) from exc
        return bucket


__all__ = ["MCPRateLimiter"]
