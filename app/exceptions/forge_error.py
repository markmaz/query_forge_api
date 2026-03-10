from __future__ import annotations

from typing import Any


class ForgeError(Exception):
    def __init__(self, message: Any, status_code: int = 400, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = dict(details or {})

    def __str__(self) -> str:
        return str(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.message,
            "status_code": self.status_code,
            "details": self.details,
        }
