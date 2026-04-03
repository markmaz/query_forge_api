from __future__ import annotations

from typing import Any


def serialize_workspace_user_row(row: dict[str, Any]) -> dict[str, Any]:
    full_name = (row.get("display_name") or "").strip()
    return {
        "user_id": row.get("user_id"),
        "username": row.get("username"),
        "email": row.get("email"),
        "first_name": row.get("first_name"),
        "last_name": row.get("last_name"),
        "status": row.get("status"),
        "is_default": bool(row.get("is_default")) if row.get("is_default") is not None else False,
        "display_name": full_name or None,
    }
