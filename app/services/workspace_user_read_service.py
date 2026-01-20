from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor


class WorkspaceUserReadService:
    """
    Lists users in a workspace using user_workspace_map + users.

    users.status values:
      - Invited
      - Active
      - Inactive

    include_inactive=False => returns Invited + Active only
    include_inactive=True  => returns all
    """

    ACTIVE_STATUSES = ("Active", "Invited")

    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def list_workspace_users(
        self,
        *,
        workspace_id: str,
        q: Optional[str] = None,
        limit: int = 5000,
        offset: int = 0,
        include_inactive: bool = True,
    ) -> List[Dict[str, Any]]:
        if not (workspace_id or "").strip():
            raise ServiceError("workspace_id is required", status_code=400)

        try:
            limit_i = int(limit)
            offset_i = int(offset)
        except Exception:
            raise ServiceError("limit/offset must be integers", status_code=400)

        if limit_i <= 0 or limit_i > 20000:
            raise ServiceError("limit must be between 1 and 20000", status_code=400)
        if offset_i < 0:
            raise ServiceError("offset must be >= 0", status_code=400)

        q_norm = (q or "").strip()
        q_like = f"%{q_norm.lower()}%" if q_norm else None

        sql = """
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

        params: Dict[str, Any] = {
            "ws": workspace_id,
            "include_inactive": 1 if include_inactive else 0,
            "q_is_null": 1 if not q_norm else 0,
            "q_like": q_like if q_like else "%",  # harmless fallback
            "limit": limit_i,
            "offset": offset_i,
        }

        rows = self._sql.execute_query_mappings(sql, params)

        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "user_id": r["user_id"],
                    "username": r["username"],
                    "email": r["email"],
                    "first_name": r["first_name"],
                    "last_name": r["last_name"],
                    "status": r["status"],
                    "is_default": bool(r["is_default"]) if r["is_default"] is not None else False,
                    "display_name": (r["display_name"] or "").strip() or None,
                }
            )

        return out
