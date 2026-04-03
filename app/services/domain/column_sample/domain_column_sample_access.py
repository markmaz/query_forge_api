from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort


@dataclass(frozen=True)
class WorkspaceTableAccess:
    workspace_table_id: int
    full_name: Optional[str]


def load_workspace_table_access(
    *,
    sql: ForgeQueryPort,
    workspace_id: str,
    user_id: str,
    workspace_table_id: int,
) -> WorkspaceTableAccess:
    rows = sql.execute_query_mappings(
        """
        SELECT
          wt.id,
          wt.workspace_id,
          wt.full_name
        FROM workspace_table wt
        WHERE wt.id = :wtid
          AND wt.workspace_id = :ws
          AND wt.exists_in_dbx = 1
          AND EXISTS (
            SELECT 1
            FROM user_domain_mapping udm
            JOIN domain d
              ON d.id = udm.domain_id
             AND d.workspace_id = :ws
             AND d.is_active = 1
            JOIN domain_workspace_table dwt
              ON dwt.domain_id = d.id
             AND dwt.workspace_table_id = wt.id
            WHERE udm.user_id = :uid
              AND udm.can_read = 1
          )
        LIMIT 1
        """,
        {"wtid": int(workspace_table_id), "ws": workspace_id, "uid": user_id},
    )
    row = rows[0] if rows else None
    if not row:
        raise ForgeError("workspace_table not found (or no access)", status_code=404)

    return WorkspaceTableAccess(
        workspace_table_id=int(row.get("id") or 0),
        full_name=row.get("full_name"),
    )
