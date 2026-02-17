from __future__ import annotations

from typing import Any, Dict, List


def get_roles_from_claim(payload: Dict[str, Any] | None) -> List[str]:
    if not isinstance(payload, dict):
        return []
    roles = payload.get("roles")
    if not isinstance(roles, list):
        return []
    out: List[str] = []
    seen = set()
    for role in roles:
        text = str(role or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def claim_has_role(payload: Dict[str, Any] | None, role_name: str) -> bool:
    target = str(role_name or "").strip().lower()
    if not target:
        return False
    return any(str(role).strip().lower() == target for role in get_roles_from_claim(payload))


def claim_is_admin(payload: Dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if bool(payload.get("is_admin") or payload.get("admin")):
        return True

    if claim_has_role(payload, "admin"):
        return True

    groups = payload.get("groups")
    if isinstance(groups, list) and any(str(group).strip().lower() == "admin" for group in groups):
        return True

    return False


__all__ = ["get_roles_from_claim", "claim_has_role", "claim_is_admin"]

