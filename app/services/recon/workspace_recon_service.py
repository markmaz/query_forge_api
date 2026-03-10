from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort


@dataclass(frozen=True)
class ReconQuery:
    workspace_id: str
    status: str | None = None
    logical_table_name: str | None = None
    limit: int = 200
    offset: int = 0


class WorkspaceReconService:
    """Build reconciliation views between workspace snapshot metadata and dictionary metadata."""

    def __init__(self, *, sql: ForgeQueryPort | None = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_recon(self, q: ReconQuery) -> list[dict[str, Any]]:
        params = self._query_params(q)
        rows = self._sql.execute_query_mappings(self._list_sql(), params)
        return [dict(row) for row in rows]

    def counts_by_status(self, *, workspace_id: str) -> dict[str, int]:
        rows = self._sql.execute_query_mappings(self._counts_sql(), {"ws": workspace_id})
        return {str(row["status"]): int(row["cnt"]) for row in rows}

    def _query_params(self, query: ReconQuery) -> dict[str, Any]:
        return {
            "ws": query.workspace_id,
            "status": (query.status or "").strip() or None,
            "logical": (query.logical_table_name or "").strip() or None,
            "limit": int(query.limit),
            "offset": int(query.offset),
        }

    def _common_ctes(self) -> str:
        return """
WITH
dbx AS (
  SELECT
    COALESCE(NULLIF(wt.qf_table_name, ''), wt.table_name) AS logical_table_name,
    wc.column_name,
    MIN(wc.data_type) AS dbx_data_type,
    MIN(wc.id) AS dbx_column_id
  FROM workspace_table wt
  JOIN workspace_column wc
    ON wc.workspace_table_id = wt.id
  WHERE wt.workspace_id = :ws
    AND wt.exists_in_dbx = 1
    AND wc.exists_in_dbx = 1
  GROUP BY COALESCE(NULLIF(wt.qf_table_name, ''), wt.table_name), wc.column_name
),
dic AS (
  SELECT
    COALESCE(NULLIF(wt.qf_table_name, ''), wt.table_name) AS logical_table_name,
    wc.column_name,
    MIN(wc.data_type) AS dict_data_type,
    MIN(wc.id) AS dict_column_id,
    MIN(wc.description) AS dict_description
  FROM workspace_table wt
  JOIN workspace_column wc
    ON wc.workspace_table_id = wt.id
  WHERE wt.workspace_id = :ws
    AND (
      wc.exists_in_dbx = 0
      OR COALESCE(wc.origin, '') <> 'DBX'
      OR COALESCE(wc.description, '') <> ''
      OR COALESCE(wc.semantic_concept_key, '') <> ''
    )
  GROUP BY COALESCE(NULLIF(wt.qf_table_name, ''), wt.table_name), wc.column_name
),
kset AS (
  SELECT logical_table_name, column_name FROM dbx
  UNION
  SELECT logical_table_name, column_name FROM dic
),
joined AS (
  SELECT
    k.logical_table_name,
    k.column_name,
    d.dbx_data_type,
    d.dbx_column_id,
    c.dict_data_type,
    c.dict_column_id,
    c.dict_description
  FROM kset k
  LEFT JOIN dbx d
    ON d.logical_table_name = k.logical_table_name
   AND d.column_name = k.column_name
  LEFT JOIN dic c
    ON c.logical_table_name = k.logical_table_name
   AND c.column_name = k.column_name
),
classified AS (
  SELECT
    logical_table_name,
    column_name,
    dbx_data_type,
    dbx_column_id,
    dict_data_type,
    dict_column_id,
    dict_description,
    CASE
      WHEN dbx_data_type IS NOT NULL AND dict_data_type IS NULL THEN 'MISSING_IN_DICT'
      WHEN dbx_data_type IS NULL AND dict_data_type IS NOT NULL THEN 'MISSING_IN_DBX'
      WHEN dbx_data_type IS NOT NULL AND dict_data_type IS NOT NULL
           AND LOWER(dbx_data_type) <> LOWER(dict_data_type) THEN 'TYPE_MISMATCH'
      WHEN dbx_data_type IS NOT NULL AND dict_data_type IS NOT NULL THEN 'MATCHED'
      ELSE 'NEEDS_REVIEW'
    END AS status
  FROM joined
)
"""

    def _list_sql(self) -> str:
        return f"""
{self._common_ctes()}
SELECT
  logical_table_name,
  column_name,
  status,
  dict_column_id,
  dbx_column_id,
  dict_description,
  dbx_data_type,
  dict_data_type
FROM classified
WHERE (:status IS NULL OR status = :status)
  AND (:logical IS NULL OR logical_table_name LIKE CONCAT('%', :logical, '%'))
ORDER BY logical_table_name, column_name
LIMIT :limit OFFSET :offset
"""

    def _counts_sql(self) -> str:
        return f"""
{self._common_ctes()}
SELECT status, COUNT(*) AS cnt
FROM classified
GROUP BY status
"""
