from __future__ import annotations

from app.routes.skills.base import skills_ns

from app.routes.skills import schedule_routes as _schedule_routes
from app.routes.skills import skill_crud_routes as _skill_crud_routes

_REGISTERED_ROUTE_MODULES = (
    _schedule_routes,
    _skill_crud_routes,
)

__all__ = ["skills_ns"]
