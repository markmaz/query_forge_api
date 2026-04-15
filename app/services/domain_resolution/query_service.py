from __future__ import annotations

from typing import Any, Dict, List

from app.ports.sql_executor import ForgeQueryPort


class DomainResolutionQueryService:
    def __init__(self, *, sql: ForgeQueryPort, workspace_id: str) -> None:
        self._sql = sql
        self._workspace_id = workspace_id

    def fetch_plan_rows(self, *, domain_id: int) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        table_rows = self._sql.execute_query_mappings(
            """
            SELECT
              dwt.workspace_table_id,
              dwt.table_alias,
              dwt.is_primary,
              dwt.sort_order,
              dwt.filter_mode,
              dwt.cardinality,
              d.column_name_policy,
              wt.full_name
            FROM domain_workspace_table dwt
            JOIN domain d
              ON d.id = dwt.domain_id
             AND d.workspace_id = :ws
             AND d.is_active = 1
            JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
             AND wt.workspace_id = :ws
             AND wt.exists_in_dbx = 1
            WHERE dwt.domain_id = :did
            ORDER BY dwt.is_primary DESC, dwt.sort_order ASC, wt.id ASC
            """,
            {"did": domain_id, "ws": self._workspace_id},
        )
        join_rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              from_workspace_table_id,
              to_workspace_table_id,
              join_type,
              join_spec_json,
              sort_order
            FROM domain_table_join
            WHERE domain_id = :did
              AND is_active = 1
            ORDER BY sort_order ASC, id ASC
            """,
            {"did": domain_id},
        )
        return table_rows, join_rows

    def fetch_mapped_rows(self, *, domain_id: int) -> List[Dict[str, Any]]:
        return self._sql.execute_query_mappings(
            """
            SELECT wt.id AS workspace_table_id, wt.full_name
            FROM domain_workspace_table dwt
            JOIN workspace_table wt ON wt.id = dwt.workspace_table_id
            WHERE dwt.domain_id = :domain_id
              AND wt.workspace_id = :ws
              AND wt.exists_in_dbx = 1
            ORDER BY wt.id ASC
            """,
            {"domain_id": domain_id, "ws": self._workspace_id},
        )
