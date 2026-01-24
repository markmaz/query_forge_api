from __future__ import annotations

from typing import Optional

from flask import g, request

from app.exceptions.service_error import ServiceError


def get_workspace_id_from_header() -> str:
    ws = (request.headers.get("X-Workspace-Id") or "").strip()
    if not ws:
        raise ServiceError("Missing X-Workspace-Id header", status_code=400)
    return ws

def get_user_id() -> str:
    user_id = getattr(g, "user_id", None)
    if user_id:
        return str(user_id).strip()
    raise ServiceError("Missing user identity", status_code=401)

def int_arg(name: str, default: int) -> int:
    v = (request.args.get(name) or "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        raise ServiceError(f"Invalid integer for '{name}'", status_code=400)

def bool_arg(name: str, default: Optional[bool] = None) -> Optional[bool]:
    v = (request.args.get(name) or "").strip().lower()
    if v == "":
        return default
    if v in ("1", "true", "yes", "y", "on"):
        return True
    if v in ("0", "false", "no", "n", "off"):
        return False
    raise ServiceError(f"Invalid boolean for '{name}'", status_code=400)