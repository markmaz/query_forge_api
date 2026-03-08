from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort


@dataclass(frozen=True)
class DictColumnRow:
    id: int
    modelTableId: int
    tableName: str
    columnName: str
    dataType: Optional[str]
    description: Optional[str]
    isActive: bool

    # column sample fields (now live on model_column)
    sampleValuesJson: Optional[str] = None
    sampleStatsJson: Optional[str] = None
    sampleRanAt: Optional[str] = None
    sampleError: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "modelTableId": self.modelTableId,
            "tableName": self.tableName,
            "columnName": self.columnName,
            "dataType": self.dataType,
            "description": self.description,
            "isActive": bool(self.isActive),

            # keep camelCase for the UI
            "sampleValuesJson": self.sampleValuesJson,
            "sampleStatsJson": self.sampleStatsJson,
            "sampleRanAt": self.sampleRanAt,
            "sampleError": self.sampleError,
        }


class ModelReadService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_tables(
        self,
        *,
        q: Optional[str] = None,
        active: Optional[bool] = None,
        limit: int = 200,
        offset: int = 0,
        include_counts: bool = True,
    ) -> Dict[str, Any]:
        """
        Returns model_table rows (paged).
        - q filters by table name
        - active filters by whether the table has any columns with is_active = active
        - include_counts optionally includes column counts (total/active) for UI badges
        """
        params = {
            "q": (q or "").strip() or None,
            "active": active,
            "limit": int(limit),
            "offset": int(offset),
        }

        qf_count_sql = """
        SELECT COUNT(*) AS total
        FROM model_table t
        WHERE (:q IS NULL OR t.name LIKE CONCAT('%', :q, '%'))
          AND (
            :active IS NULL OR EXISTS (
              SELECT 1
              FROM model_column c
              WHERE c.model_table_id = t.id
                AND c.is_active = :active
            )
          )
        """

        rows_sql = """
        SELECT
          t.id,
          t.name,
          t.source_table_name,
          t.description
        FROM model_table t
        WHERE (:q IS NULL OR t.name LIKE CONCAT('%', :q, '%'))
          AND (
            :active IS NULL OR EXISTS (
              SELECT 1
              FROM model_column c
              WHERE c.model_table_id = t.id
                AND c.is_active = :active
            )
          )
        ORDER BY t.name
        LIMIT :limit OFFSET :offset
        """

        total_rows = self._sql.execute_query(qf_count_sql, params)
        total = int(total_rows[0][0]) if total_rows else 0

        rows = self._sql.execute_query(rows_sql, params)

        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": int(r[0]),
                    "name": str(r[1]),
                    "sourceTableName": (str(r[2]) if r[2] is not None else None),
                    "description": r[3],
                }
            )

        if not include_counts or not out:
            return {"rows": out, "total": total, "limit": params["limit"], "offset": params["offset"]}

        # Optional per-table counts for UI
        ids = [x["id"] for x in out]
        counts_sql = """
        SELECT
          c.model_table_id,
          COUNT(1) AS column_count,
          SUM(CASE WHEN c.is_active = 1 THEN 1 ELSE 0 END) AS active_column_count
        FROM model_column c
        WHERE c.model_table_id IN :ids
        GROUP BY c.model_table_id
        """
        counts_rows = self._sql.execute_query(counts_sql, {"ids": tuple(ids)})
        counts_by_id = {int(r[0]): {"columnCount": int(r[1]), "activeColumnCount": int(r[2])} for r in counts_rows}

        for x in out:
            x.update(counts_by_id.get(int(x["id"]), {"columnCount": 0, "activeColumnCount": 0}))

        return {"rows": out, "total": total, "limit": params["limit"], "offset": params["offset"]}

    def list_table_names(self, *, q: Optional[str] = None, active: Optional[bool] = None) -> List[str]:
        params = {"active": active, "q": (q or "").strip() or None}

        sql = """
        SELECT t.name
        FROM model_table t
        WHERE (:q IS NULL OR t.name LIKE CONCAT('%', :q, '%'))
          AND (
            :active IS NULL OR EXISTS (
              SELECT 1
              FROM model_column c
              WHERE c.model_table_id = t.id
                AND c.is_active = :active
            )
          )
        ORDER BY t.name
        """

        rows = self._sql.execute_query(sql, params)
        return [str(r[0]) for r in rows]

    def list_columns(
        self,
        *,
        q: Optional[str] = None,
        table: Optional[str] = None,
        active: Optional[bool] = None,
        limit: int = 1000,
        offset: int = 0,
        include_table_names: bool = True,
    ) -> Dict[str, Any]:
        params = {
            "q": (q or "").strip() or None,
            "table": (table or "").strip() or None,
            "active": active,
            "limit": int(limit),
            "offset": int(offset),
        }

        sql = """
        SELECT
          c.id,
          c.model_table_id,
          t.name AS table_name,
          c.column_name,
          c.data_type,
          c.description,
          c.is_active,
          c.sample_values_json,
          c.sample_stats_json,
          c.sample_ran_at,
          c.sample_error
        FROM model_column c
        JOIN model_table t ON t.id = c.model_table_id
        WHERE (:active IS NULL OR c.is_active = :active)
          AND (:table IS NULL OR t.name = :table)
          AND (
            :q IS NULL OR
            c.column_name LIKE CONCAT('%', :q, '%') OR
            c.description LIKE CONCAT('%', :q, '%')
          )
        ORDER BY t.name, c.column_name
        LIMIT :limit OFFSET :offset
        """

        rows = self._sql.execute_query(sql, params)

        out_rows: List[Dict[str, Any]] = []
        for r in rows:
            sample_ran_at = r[9]
            out_rows.append(
                DictColumnRow(
                    id=int(r[0]),
                    modelTableId=int(r[1]),
                    tableName=str(r[2]),
                    columnName=str(r[3]),
                    dataType=r[4],
                    description=r[5],
                    isActive=bool(r[6]),
                    sampleValuesJson=r[7],
                    sampleStatsJson=r[8],
                    sampleRanAt=(sample_ran_at.isoformat() if sample_ran_at else None),
                    sampleError=r[10],
                ).to_dict()
            )

        resp: Dict[str, Any] = {"rows": out_rows}
        if include_table_names:
            resp["tableNames"] = self.list_table_names(active=active)
        return resp
