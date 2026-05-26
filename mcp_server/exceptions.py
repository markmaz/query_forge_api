from __future__ import annotations

from typing import Any, Dict, Literal

from app.exceptions.forge_error import ForgeError

MCPErrorCode = Literal[
    "UNAUTHORIZED",
    "FORBIDDEN",
    "INVALID_WORKSPACE",
    "INVALID_DOMAIN",
    "INVALID_PLAN",
    "VALIDATION_FAILED",
    "EXECUTION_DISABLED",
    "PREVIEW_LIMIT_EXCEEDED",
    "QUERY_NOT_FOUND",
    "RATE_LIMITED",
    "INTERNAL_ERROR",
]


class MCPError(Exception):
    def __init__(
        self,
        *,
        error_code: MCPErrorCode,
        message: str,
        details: Dict[str, Any] | None = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = dict(details or {})
        self.status_code = int(status_code)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": dict(self.details or {}),
        }


def map_exception(exc: Exception) -> MCPError:
    if isinstance(exc, MCPError):
        return exc
    if isinstance(exc, ForgeError):
        message = str(exc)
        status = int(getattr(exc, "status_code", 400) or 400)
        details = dict(getattr(exc, "details", {}) or {})
        lowered = message.lower()
        if status == 401:
            return MCPError(error_code="UNAUTHORIZED", message=message, details=details, status_code=status)
        if status == 403:
            return MCPError(error_code="FORBIDDEN", message=message, details=details, status_code=status)
        if "workspace" in lowered:
            return MCPError(error_code="INVALID_WORKSPACE", message=message, details=details, status_code=status)
        if "domain" in lowered:
            return MCPError(error_code="INVALID_DOMAIN", message=message, details=details, status_code=status)
        if "query" in lowered and "not found" in lowered:
            return MCPError(error_code="QUERY_NOT_FOUND", message=message, details=details, status_code=status)
        if "validation" in lowered:
            return MCPError(error_code="VALIDATION_FAILED", message=message, details=details, status_code=status)
        return MCPError(error_code="INVALID_PLAN", message=message, details=details, status_code=status)
    return MCPError(
        error_code="INTERNAL_ERROR",
        message="Internal server error",
        details={},
        status_code=500,
    )
