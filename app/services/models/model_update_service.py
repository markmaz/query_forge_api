from __future__ import annotations

from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor

ALLOWED_FIELDS = {"dataType", "description", "isActive"}

class ModelUpdateService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def patch_column(
        self,
        *,
        column_id: int,
        patch: Dict[str, Any],
        updated_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        bad = [k for k in patch.keys() if k not in ALLOWED_FIELDS]
        if bad:
            raise ServiceError(f"Invalid fields in patch: {', '.join(bad)}", status_code=400)

        sets = []
        params: Dict[str, Any] = {"id": int(column_id)}

        if "dataType" in patch:
            sets.append("c.data_type = :data_type")
            params["data_type"] = patch.get("dataType") or None
        if "description" in patch:
            sets.append("c.description = :description")
            params["description"] = patch.get("description") or None
        if "isActive" in patch:
            sets.append("c.is_active = :is_active")
            params["is_active"] = 1 if bool(patch.get("isActive")) else 0

        if not sets:
            raise ServiceError("Empty patch", status_code=400)

        upd_sql = f"""
UPDATE model_column c
SET {", ".join(sets)}
WHERE c.id = :id
"""
        affected = self._sql.execute_write(upd_sql, params)
        if affected == 0:
            raise ServiceError("Dictionary column not found", status_code=404)

        sel_sql = """
SELECT
  c.id,
  c.model_table_id,
  t.name AS table_name,
  c.column_name,
  c.data_type,
  c.description,
  c.is_active
FROM model_column c
JOIN model_table t ON t.id = c.model_table_id
WHERE c.id = :id
LIMIT 1
"""
        r = self._sql.execute_query(sel_sql, {"id": int(column_id)})
        if not r:
            raise ServiceError("Dictionary column not found", status_code=404)

        row = r[0]
        return {
            "id": int(row[0]),
            "modelTableId": int(row[1]),
            "tableName": str(row[2]),
            "columnName": str(row[3]),
            "dataType": row[4],
            "description": row[5],
            "isActive": bool(row[6]),
        }
    
    def create_column(
        self,
        *,
        table_name: str,
        column_name: str,
        data_type: Optional[str],
        description: Optional[str],
        is_active: bool,
        created_by: str,           # not persisted in schema; ok for audit later
    ) -> Dict[str, Any]:
        # 1) Find model_table.id (create if missing OR raise)
        sql_get_table = "SELECT id, name FROM model_table WHERE name = :name"
        sql_insert_table = "INSERT INTO model_table(name) VALUES(:name)"
        sql_insert_col = """
INSERT INTO model_column(model_table_id, column_name, data_type, description, is_active)
VALUES(:mtid, :col, :dtype, :desc, :active)
"""
        sql_select_created = """
SELECT
  mc.id,
  mc.model_table_id AS logicalTableId,
  mt.name AS tableName,
  mc.column_name AS columnName,
  mc.data_type AS dataType,
  mc.description AS description,
  (mc.is_active = 1) AS isActive
FROM model_column mc
JOIN model_table mt ON mt.id = mc.model_table_id
WHERE mc.id = :id
"""

        with self._sql.transaction() as tx:
            mt_rows = tx.execute_query_mappings(sql_get_table, {"name": table_name})
            mt = mt_rows[0] if mt_rows else None
            if not mt:
                # choose one behavior:
                # A) auto-create table:
                res = tx.execute_insert(sql_insert_table, {"name": table_name})
                mtid = res.lastrowid
            else:
                mtid = int(mt["id"])

            # 2) Insert model_column (handle dup nicely)
            try:
                res = tx.execute_insert(
                    sql_insert_col,
                    {"mtid": mtid, "col": column_name, "dtype": data_type, "desc": description, "active": 1 if is_active else 0},
                )
                new_id = res.lastrowid
            except Exception as e:
                # Most likely unique constraint uq_model_col hit
                raise ServiceError("Column already exists for this table", status_code=409) from e

            created_rows = tx.execute_query_mappings(sql_select_created, {"id": new_id})
            created = created_rows[0] if created_rows else None

        return dict(created) if created else {}
