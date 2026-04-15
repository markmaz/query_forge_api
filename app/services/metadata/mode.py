from __future__ import annotations

from typing import Optional


_SUPPORTED_METADATA_MODES = {"workspace", "legacy"}


def normalize_metadata_mode(mode: Optional[str]) -> str:
    token = str(mode or "").strip().lower() or "workspace"
    if token not in _SUPPORTED_METADATA_MODES:
        raise ValueError(f"Unsupported metadata_mode: {mode}")
    return token


def effective_metadata_mode(mode: Optional[str]) -> str:
    normalized = normalize_metadata_mode(mode)
    if normalized == "legacy":
        return "workspace"
    return normalized

