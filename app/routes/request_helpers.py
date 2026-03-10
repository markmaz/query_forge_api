from __future__ import annotations

from typing import Optional

from flask import g, request

from app.exceptions.forge_error import ForgeError
from app.services.workspace_access_service import WorkspaceAccessService

workspace_access_service = WorkspaceAccessService()


def extract_workspace_id() -> str:
    ws = (request.headers.get("X-Workspace-Id") or "").strip()
    if not ws:
        raise ForgeError("Missing X-Workspace-Id header", status_code=400)
    user_id = str(getattr(g, "user_id", "") or "").strip()
    if user_id:
        workspace_access_service.assert_workspace_access(user_id=user_id, workspace_id=ws)
    return ws


def require_user_id() -> str:
    user_id = getattr(g, "user_id", None)
    if user_id:
        return str(user_id).strip()
    raise ForgeError("Missing user identity", status_code=401)


def int_arg(name: str, default: int) -> int:
    v = (request.args.get(name) or "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        raise ForgeError(f"Invalid integer for '{name}'", status_code=400)


def bool_arg(name: str, default: Optional[bool] = None) -> Optional[bool]:
    v = (request.args.get(name) or "").strip().lower()
    if v == "":
        return default
    if v in ("1", "true", "yes", "y", "on"):
        return True
    if v in ("0", "false", "no", "n", "off"):
        return False
    raise ForgeError(f"Invalid boolean for '{name}'", status_code=400)
