"""Planner-domain service package."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["PlannerDomainService"]


def __getattr__(name: str) -> Any:
    if name == "PlannerDomainService":
        return import_module("app.services.planner_domain.service").PlannerDomainService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
