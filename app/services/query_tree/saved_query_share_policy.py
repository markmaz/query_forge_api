from __future__ import annotations

from typing import Any, Dict, Optional

from app.exceptions.forge_error import ForgeError


def require_field(value: Any, field: str) -> str:
    clean_value = str(value or "").strip()
    if not clean_value:
        raise ForgeError(f"{field} is required", status_code=400)
    return clean_value


def build_share_payload(
    *,
    acl_id: str,
    query_id: str,
    principal_type: str,
    principal_id: str,
    permission: str,
) -> Dict[str, Any]:
    return {
        "aclId": acl_id,
        "queryId": query_id,
        "principalType": principal_type,
        "principalId": principal_id,
        "permission": permission,
        "canEdit": permission == "WRITE",
    }


def build_share_list_item(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "aclId": row["id"],
        "principalType": row["principal_type"],
        "principalId": row["principal_id"],
        "permission": row["permission"],
        "canEdit": row["permission"] == "WRITE",
        "createdAt": _to_isoformat(row.get("created_at")),
    }


def _to_isoformat(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()
