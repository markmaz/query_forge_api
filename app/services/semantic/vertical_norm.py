from __future__ import annotations

from typing import Any

_GENERIC_COMPATIBILITY_VERTICALS = {
    "",
    "__global__",
    "education",
    "generic",
    "global",
    "none",
    "null",
}


def normalize_semantic_vertical(value: Any, *, default: str = "generic") -> str:
    fallback = str(default or "generic").strip().lower() or "generic"
    text = str(value or "").strip().lower()
    if text in _GENERIC_COMPATIBILITY_VERTICALS:
        return fallback
    return text or fallback


__all__ = ["normalize_semantic_vertical"]
