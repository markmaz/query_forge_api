from __future__ import annotations

from typing import Any

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort


class UnmappedWorkspaceTablesReadService:
    """Read unmapped workspace tables from cached workspace inventory snapshot."""

    def __init__(self, *, sql: ForgeQueryPort | None = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_unmapped_tables(
        self,
        *,
        workspace_id: str,
        schema_name: str | None = None,
        q: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        params = self._params(
            workspace_id=workspace_id,
            schema_name=schema_name,
            q=q,
            limit=limit,
            offset=offset,
        )

        total_rows = self._sql.execute_query_mappings(self._count_sql(), params)
        data_rows = self._sql.execute_query_mappings(self._rows_sql(), params)

        total = int((total_rows[0].get("total") if total_rows else 0) or 0)
        return {
            "rows": [dict(row) for row in data_rows],
            "total": total,
            "limit": params["limit"],
            "offset": params["offset"],
        }

    def _params(
        self,
        *,
        workspace_id: str,
        schema_name: str | None,
        q: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        return {
            "ws": workspace_id,
            "schema": (schema_name or "").strip() or None,
            "q": (q or "").strip() or None,
            "limit": int(limit),
            "offset": int(offset),
        }

    def _count_sql(self) -> str:
        return """
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

    def _rows_sql(self) -> str:
        return """
SELECT
  wt.id,
  wt.catalog_name,
  wt.schema_name,
  wt.table_name,
  wt.full_name,
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
