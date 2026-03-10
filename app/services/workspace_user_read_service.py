from __future__ import annotations

from typing import Any

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort


class WorkspaceUserReadService:
    ACTIVE_STATUSES = ("Active", "Invited")

    def __init__(self, *, sql: ForgeQueryPort | None = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_workspace_users(
        self,
        *,
        workspace_id: str,
        q: str | None = None,
        limit: int = 5000,
        offset: int = 0,
        include_inactive: bool = True,
    ) -> list[dict[str, Any]]:
        workspace_id = (workspace_id or "").strip()
        if not workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)

        try:
            limit_value = int(limit)
            offset_value = int(offset)
        except Exception as exc:
            raise ForgeError("limit/offset must be integers", status_code=400) from exc

        if limit_value <= 0 or limit_value > 20000:
            raise ForgeError("limit must be between 1 and 20000", status_code=400)
        if offset_value < 0:
            raise ForgeError("offset must be >= 0", status_code=400)

        query = """
SELECT
  u.user_id                                           AS user_id,
  u.username                                          AS username,
  u.email                                             AS email,
  u.first_name                                        AS first_name,
  u.last_name                                         AS last_name,
  u.status                                            AS status,
  uwm.is_default                                      AS is_default,
  CONCAT_WS(' ', NULLIF(u.first_name,''), NULLIF(u.last_name,'')) AS display_name
FROM user_workspace_map uwm
JOIN users u ON u.user_id = uwm.user_id
WHERE uwm.workspace_id = :ws
  AND (
    :include_inactive = 1
    OR u.status IN ('Active', 'Invited')
  )
  AND (
    :q_is_null = 1
    OR LOWER(u.username) LIKE :q_like
    OR LOWER(u.email) LIKE :q_like
    OR LOWER(COALESCE(u.first_name,'')) LIKE :q_like
    OR LOWER(COALESCE(u.last_name,'')) LIKE :q_like
    OR LOWER(CONCAT_WS(' ', COALESCE(u.first_name,''), COALESCE(u.last_name,''))) LIKE :q_like
  )
ORDER BY
  u.username ASC, u.email ASC
LIMIT :limit OFFSET :offset
"""
        term = (q or "").strip().lower()
        rows = self._sql.execute_query_mappings(
            query,
            {
                "ws": workspace_id,
                "include_inactive": 1 if include_inactive else 0,
                "q_is_null": 0 if term else 1,
                "q_like": f"%{term}%" if term else "%",
                "limit": limit_value,
                "offset": offset_value,
            },
        )
        return [self._serialize_row(row) for row in rows]

    def _serialize_row(self, row: dict[str, Any]) -> dict[str, Any]:
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
