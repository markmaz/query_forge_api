"""ForgeMatch mapping workflow services."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["ForgeMatchMappingService"]


def __getattr__(name: str) -> Any:
    if name == "ForgeMatchMappingService":
        return import_module("app.services.forge_match.mapping_service").ForgeMatchMappingService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
