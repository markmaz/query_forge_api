from __future__ import annotations

from typing import Any

from app.exceptions.forge_error import ForgeError

INT_PARSE_ERRORS = (TypeError, ValueError)


def validate_workspace_user_list_args(
    *,
    workspace_id: str,
    limit: int,
    offset: int,
) -> tuple[str, int, int]:
    workspace_value = (workspace_id or "").strip()
    if not workspace_value:
        raise ForgeError("workspace_id is required", status_code=400)

    try:
        limit_value = int(limit)
        offset_value = int(offset)
    except INT_PARSE_ERRORS as exc:
        raise ForgeError("limit/offset must be integers", status_code=400) from exc

    if limit_value <= 0 or limit_value > 20000:
        raise ForgeError("limit must be between 1 and 20000", status_code=400)
    if offset_value < 0:
        raise ForgeError("offset must be >= 0", status_code=400)

    return workspace_value, limit_value, offset_value


def build_workspace_user_list_query(
    *,
    workspace_id: str,
    q: str | None,
    limit: int,
    offset: int,
    include_inactive: bool,
) -> tuple[str, dict[str, Any]]:
    term = (q or "").strip().lower()
    query = """
SELECT
  u.user_id                                           AS user_id,
  u.username                                          AS username,
  u.email                                             AS email,
  u.first_name                                        AS first_name,
  u.last_name                                         AS last_name,
  u.status                                            AS status,
  COALESCE(wm_def.is_default, 0)                      AS is_default,
  CONCAT_WS(' ', NULLIF(u.first_name,''), NULLIF(u.last_name,'')) AS display_name
FROM (
  SELECT wm.user_id
  FROM workspace_membership wm
  WHERE wm.workspace_id = :ws
    AND COALESCE(wm.is_active, 1) = 1

  UNION

  SELECT om.user_id
  FROM workspace w
  JOIN organization_membership om
    ON om.organization_id = w.organization_id
   AND COALESCE(om.is_active, 1) = 1
  WHERE w.id = :ws
    AND COALESCE(w.is_active, 1) = 1
) members
JOIN users u ON u.user_id = members.user_id
LEFT JOIN workspace_membership wm_def
  ON wm_def.user_id = u.user_id
 AND wm_def.workspace_id = :ws
 AND COALESCE(wm_def.is_active, 1) = 1
WHERE 1 = 1
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
    params = {
        "ws": workspace_id,
        "include_inactive": 1 if include_inactive else 0,
        "q_is_null": 0 if term else 1,
        "q_like": f"%{term}%" if term else "%",
        "limit": limit,
        "offset": offset,
    }
    return query, params
