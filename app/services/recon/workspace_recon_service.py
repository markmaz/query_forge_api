from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.ports.sql_executor import SQLExecutor


@dataclass(frozen=True)
class ReconQuery:
    workspace_id: str
    status: Optional[str] = None
    logical_table_name: Optional[str] = None
    limit: int = 200
    offset: int = 0


class WorkspaceReconService:
    """
    Computed reconciliation between:
      - Workspace truth: workspace_table/workspace_column (DBX snapshot)
      - Global dictionary: model_table/model_column
    """

    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def list_recon(self, q: ReconQuery) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "ws": q.workspace_id,
            "status": (q.status or "").strip() or None,
            "logical": (q.logical_table_name or "").strip() or None,
            "limit": int(q.limit),
            "offset": int(q.offset),
        }

        sql = """
WITH
dbx AS (
  SELECT
    mt.name AS logical_table_name,
    wc.column_name,
    MIN(wc.data_type) AS dbx_data_type,
    MIN(wc.id) AS dbx_column_id
  FROM workspace_table wt
  JOIN model_table mt ON mt.id = wt.model_table_id
  JOIN workspace_column wc ON wc.workspace_table_id = wt.id
  WHERE wt.workspace_id = :ws
    AND wt.exists_in_dbx = 1
    AND wc.exists_in_dbx = 1
  GROUP BY mt.name, wc.column_name
),
dic AS (
  SELECT
    mt.name AS logical_table_name,
    mc.column_name,
    MIN(mc.data_type) AS dict_data_type,
    MIN(mc.id) AS dict_column_id,
    MIN(mc.description) AS dict_description
  FROM model_table mt
  JOIN model_column mc ON mc.model_table_id = mt.id
  WHERE mc.is_active = 1
  GROUP BY mt.name, mc.column_name
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

        rows = self._sql.execute_query_mappings(sql, params)

        return [dict(r) for r in rows]

    def counts_by_status(self, *, workspace_id: str) -> Dict[str, int]:
        params = {"ws": workspace_id}

        sql = """
WITH
dbx AS (
  SELECT
    mt.name AS logical_table_name,
    wc.column_name,
    MIN(wc.data_type) AS dbx_data_type
  FROM workspace_table wt
  JOIN model_table mt ON mt.id = wt.model_table_id
  JOIN workspace_column wc ON wc.workspace_table_id = wt.id
  WHERE wt.workspace_id = :ws
    AND wt.exists_in_dbx = 1
    AND wc.exists_in_dbx = 1
  GROUP BY mt.name, wc.column_name
),
dic AS (
  SELECT
    mt.name AS logical_table_name,
    mc.column_name,
    MIN(mc.data_type) AS dict_data_type
  FROM model_table mt
  JOIN model_column mc ON mc.model_table_id = mt.id
  WHERE mc.is_active = 1
  GROUP BY mt.name, mc.column_name
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
    c.dict_data_type
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
SELECT status, COUNT(*) AS cnt
FROM classified
GROUP BY status
"""

        rows = self._sql.execute_query_mappings(sql, params)

        return {str(r["status"]): int(r["cnt"]) for r in rows}
