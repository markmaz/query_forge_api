from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort


class ModelColumnSearchService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def search_columns(self, *, workspace_id: str, q: str, limit: int = 20) -> List[Dict[str, Any]]:
        params = {
            "workspace_id": workspace_id,
            "q": (q or "").strip(),
            "limit": int(limit),
        }

        sql = """
        SELECT DISTINCT
          c.id,
          c.model_table_id,
          t.name AS table_name,
          c.column_name,
          c.data_type,
          c.description,
          c.is_active
        FROM model_column c
        JOIN model_table t ON t.id = c.model_table_id
        WHERE (
          c.column_name LIKE CONCAT('%', :q, '%')
          OR c.description LIKE CONCAT('%', :q, '%')
        )
          AND EXISTS (
            SELECT 1
            FROM workspace_table wt
            WHERE wt.model_table_id = t.id
              AND wt.workspace_id = :workspace_id
          )
        ORDER BY c.column_name
        LIMIT :limit
        """

        rows = self._sql.execute_query(sql, params)
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": int(r[0]),
                    "modelTableId": int(r[1]),
                    "tableName": str(r[2]),
                    "columnName": str(r[3]),
                    "dataType": r[4],
                    "description": r[5],
                    "isActive": bool(r[6]),
                }
            )
        return out
