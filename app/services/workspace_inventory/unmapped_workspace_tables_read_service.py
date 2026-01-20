from __future__ import annotations

from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.ports.sql_executor import SQLExecutor


class UnmappedWorkspaceTablesReadService:
    """
    Unmapped = workspace_table rows that exist in DBX snapshot, but do not map to model_table.
    This is the admin view you want for the Recon tab.

    Requires:
      - workspace_table.model_table_id nullable
    """

    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def list_unmapped_tables(
        self,
        *,
        workspace_id: str,
        schema_name: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        params = {
            "ws": workspace_id,
            "schema": (schema_name or "").strip() or None,
            "q": (q or "").strip() or None,
            "limit": int(limit),
            "offset": int(offset),
        }

        count_sql = """
SELECT COUNT(*) AS total
FROM workspace_table wt
WHERE wt.workspace_id = :ws
  AND wt.exists_in_dbx = 1
  AND wt.model_table_id IS NULL
  AND (:schema IS NULL OR wt.schema_name = :schema)
  AND (:q IS NULL OR (
        wt.full_name  LIKE CONCAT('%', :q, '%')
     OR wt.table_name LIKE CONCAT('%', :q, '%')
     OR IFNULL(wt.variant_code, '') LIKE CONCAT('%', :q, '%')
  ))
"""

        rows_sql = """
SELECT
  wt.id,
  wt.catalog_name,
  wt.schema_name,
  wt.table_name,     -- base name
  wt.full_name,      -- physical catalog.schema.table
  wt.variant_code,
  wt.is_qe,
  wt.exists_in_dbx,
  wt.last_seen_at
FROM workspace_table wt
WHERE wt.workspace_id = :ws
  AND wt.exists_in_dbx = 1
  AND wt.model_table_id IS NULL
  AND (:schema IS NULL OR wt.schema_name = :schema)
  AND (:q IS NULL OR (
        wt.full_name  LIKE CONCAT('%', :q, '%')
     OR wt.table_name LIKE CONCAT('%', :q, '%')
     OR IFNULL(wt.variant_code, '') LIKE CONCAT('%', :q, '%')
  ))
ORDER BY wt.schema_name, wt.table_name, wt.variant_code, wt.full_name
LIMIT :limit OFFSET :offset
"""

        total_rows = self._sql.execute_query_mappings(count_sql, params)
        total = int((total_rows[0].get("total") if total_rows else 0) or 0)
        rows = self._sql.execute_query_mappings(rows_sql, params)

        return {
            "rows": [dict(r) for r in rows],
            "total": total,
            "limit": params["limit"],
            "offset": params["offset"],
        }
