from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.adapters.databricks_sql_executor import DatabricksSQLExecutor
from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.config import (
    DBX_MODEL_COLUMNS_SNAPSHOT_TABLE,
    DBX_MODEL_SNAPSHOT_CATALOG,
    DBX_MODEL_SNAPSHOT_SCHEMA,
    DBX_MODEL_TABLES_SNAPSHOT_TABLE,
)
from app.ports.sql_executor import SQLExecutor

COLUMNS_PATH = f"{DBX_MODEL_SNAPSHOT_CATALOG}.{DBX_MODEL_SNAPSHOT_SCHEMA}.{DBX_MODEL_COLUMNS_SNAPSHOT_TABLE}"
TABLE_PATH = f"{DBX_MODEL_SNAPSHOT_CATALOG}.{DBX_MODEL_SNAPSHOT_SCHEMA}.{DBX_MODEL_TABLES_SNAPSHOT_TABLE}"

def _chunk(xs: List[Any], n: int = 500) -> List[List[Any]]:
    return [xs[i:i+n] for i in range(0, len(xs), n)]


@dataclass(frozen=True)
class ImportResult:
    snapshot_id: str
    tables_upserted: int
    columns_upserted: int
    columns_deactivated: int


class ModelSnapshotImportService:
    """
    Imports model structure + samples from DBX Delta snapshot tables into MySQL:
      - model_table (name, source_table_name)
      - model_column (data_type, nullable, ordinal_position, sample_*)

    Preserves dictionary-owned description fields.
    """

    def __init__(
        self,
        *,
        sql: DatabricksSQLExecutor,
        mysql: Optional[SQLExecutor] = None,
    ):
        self._sql = sql
        self._mysql = mysql or MySQLSQLExecutor()

    # ----------------------------
    # DBX reads
    # ----------------------------

    def _latest_snapshot_id(self) -> str:
        sql_text = f"""
SELECT snapshot_id
FROM {TABLE_PATH}
ORDER BY snapshot_utc DESC
LIMIT 1
"""
        resp = self._sql.submit_statement(sql_text, result_format="ARROW_STREAM")
        rows = resp.get("rows") or []
        if not rows:
            raise ValueError("No snapshots found in model_tables_snapshot")
        return str(rows[0]["snapshot_id"])

    def _fetch_tables(self, snapshot_id: str) -> List[Dict[str, Any]]:
        sql_text = f"""
SELECT
  snapshot_id,
  snapshot_utc,
  source_catalog,
  source_schema,
  logical_table_name,
  physical_table_name,
  full_name,
  table_comment,
  column_count
FROM {TABLE_PATH}
WHERE snapshot_id = '{snapshot_id}'
"""
        resp = self._sql.submit_statement(sql_text, result_format="ARROW_STREAM")
        return resp.get("rows") or []

    def _fetch_columns(self, snapshot_id: str) -> List[Dict[str, Any]]:
        sql_text = f"""
SELECT
  snapshot_id,
  snapshot_utc,
  source_catalog,
  source_schema,
  logical_table_name,
  physical_table_name,
  full_name,
  column_name,
  data_type,
  nullable,
  ordinal_position,
  column_comment,
  table_comment,
  sample_values_json,
  sample_stats_json,
  sample_error
FROM {COLUMNS_PATH}
WHERE snapshot_id = '{snapshot_id}'
"""
        resp = self._sql.submit_statement(sql_text, result_format="ARROW_STREAM")
        return resp.get("rows") or []

    # ----------------------------
    # MySQL writes
    # ----------------------------

    def import_snapshot(self, *, snapshot_id: Optional[str] = None, deactivate_missing: bool = True) -> ImportResult:
        sid = snapshot_id or self._latest_snapshot_id()

        tables = self._fetch_tables(sid)
        cols = self._fetch_columns(sid)

        if not tables:
            raise ValueError(f"No table rows found for snapshot_id={sid}")
        if not cols:
            raise ValueError(f"No column rows found for snapshot_id={sid}")

        table_payload = []
        logical_names: List[str] = []

        for r in tables:
            name = str(r.get("logical_table_name") or "").strip()
            src = str(r.get("physical_table_name") or "").strip() or None
            if not name:
                continue
            logical_names.append(name)
            table_payload.append({"name": name, "source_table_name": src})

        with self._mysql.transaction() as tx:
            # 1) Upsert model_table as DBX source-of-truth
            if table_payload:
                tx.execute_write(
                    """
    INSERT INTO model_table (name, source_table_name, description, origin, is_missing_in_source, created_at)
    VALUES (:name, :source_table_name, NULL, 'DBX', 0, CURRENT_TIMESTAMP)
    ON DUPLICATE KEY UPDATE
    source_table_name = VALUES(source_table_name),
    origin = 'DBX',
    is_missing_in_source = 0,
    updated_at = CURRENT_TIMESTAMP
    """,
                    table_payload,
                )

            # 2) Resolve name -> id map (expanding bind)
            name_to_id: Dict[str, int] = {}
            for chunk in _chunk(sorted(set(logical_names)), 500):
                placeholders = ",".join([f":n{i}" for i in range(len(chunk))])
                params = {f"n{i}": name for i, name in enumerate(chunk)}
                rows = tx.execute_query_mappings(
                    f"SELECT id, name FROM model_table WHERE name IN ({placeholders})",
                    params,
                )
                for rr in rows:
                    name_to_id[str(rr["name"])] = int(rr["id"])

            # 3) Upsert model_column (DBX truth) and CLEAR missing flag
            col_payload: List[Dict[str, Any]] = []
            cols_by_table_id: Dict[int, set] = {}

            for r in cols:
                logical = str(r.get("logical_table_name") or "").strip()
                col_name = str(r.get("column_name") or "").strip()
                if not logical or not col_name:
                    continue

                tid = name_to_id.get(logical)
                if not tid:
                    continue

                cols_by_table_id.setdefault(tid, set()).add(col_name)

                nullable_val = r.get("nullable")
                if isinstance(nullable_val, str):
                    nullable = 1 if nullable_val.strip().lower() in ("1", "true", "yes") else 0
                else:
                    nullable = 1 if bool(nullable_val) else 0

                sample_values_json = r.get("sample_values_json")
                sample_stats_json = r.get("sample_stats_json")
                sample_error = r.get("sample_error")

                if sample_values_json is not None and not isinstance(sample_values_json, str):
                    sample_values_json = json.dumps(sample_values_json, default=str)
                if sample_stats_json is not None and not isinstance(sample_stats_json, str):
                    sample_stats_json = json.dumps(sample_stats_json, default=str)

                col_payload.append(
                    {
                        "model_table_id": tid,
                        "column_name": col_name,
                        "data_type": (r.get("data_type") or None),
                        "nullable": nullable,
                        "ordinal_position": int(r.get("ordinal_position") or 0),
                        "sample_values_json": sample_values_json,
                        "sample_stats_json": sample_stats_json,
                        "sample_error": (str(sample_error)[:500] if sample_error else None),
                    }
                )

            columns_upserted = 0
            for chunk in _chunk(col_payload, 2000):
                tx.execute_write(
                    """
    INSERT INTO model_column
    (model_table_id, column_name, data_type, ordinal_position, nullable, is_active,
    origin, is_missing_in_source,
    sample_values_json, sample_stats_json, sample_error, sample_ran_at, created_at)
    VALUES
    (:model_table_id, :column_name, :data_type, :ordinal_position, :nullable, 1,
    'DBX', 0,
    :sample_values_json, :sample_stats_json, :sample_error, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON DUPLICATE KEY UPDATE
    data_type            = VALUES(data_type),
    ordinal_position     = VALUES(ordinal_position),
    nullable             = VALUES(nullable),
    is_active            = 1,
    origin               = 'DBX',
    is_missing_in_source = 0,
    sample_values_json   = VALUES(sample_values_json),
    sample_stats_json    = VALUES(sample_stats_json),
    sample_error         = VALUES(sample_error),
    sample_ran_at        = CURRENT_TIMESTAMP,
    updated_at           = CURRENT_TIMESTAMP
    """,
                    chunk,
                )
                columns_upserted += len(chunk)

            # 4) Deactivate missing DBX columns (optional)
            # IMPORTANT: only deactivate rows that are DBX-origin AND not dictionary-missing placeholders.
            deactivated = 0
            if deactivate_missing:
                for tid, colset in cols_by_table_id.items():
                    cols_list = sorted(colset)
                    if not cols_list:
                        continue
                    placeholders = ",".join([f":c{i}" for i in range(len(cols_list))])
                    params = {"tid": tid, **{f"c{i}": col for i, col in enumerate(cols_list)}}
                    res = tx.execute_write(
                        f"""
                        UPDATE model_column
                        SET is_active = 0, updated_at = CURRENT_TIMESTAMP
                        WHERE model_table_id = :tid
                        AND is_active = 1
                        AND origin = 'DBX'
                        AND is_missing_in_source = 0
                        AND column_name NOT IN ({placeholders})
                        """,
                        params,
                    )
                    deactivated += int(res or 0)

        return ImportResult(
            snapshot_id=sid,
            tables_upserted=len(table_payload),
            columns_upserted=columns_upserted,
            columns_deactivated=deactivated,
        )
