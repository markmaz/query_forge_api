from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import pyarrow as pa

from app.adapters.databricks_sql_executor import DatabricksSQLExecutor
from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.ports.sql_executor import SQLExecutor

logger = logging.getLogger(__name__)

IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _safe_ident(s: str) -> str:
    if not IDENT_RE.fullmatch(s):
        raise ValueError(f"Unsafe identifier: {s!r}")
    return s


def _quote_full_name(full_name: str) -> str:
    """
    Convert `catalog.schema.table` -> `\`catalog\`.\`schema\`.\`table\``
    so we can safely query in Databricks SQL.
    """
    parts = [p.strip() for p in (full_name or "").split(".") if p.strip()]
    if len(parts) != 3:
        raise ValueError(f"Expected full_name like catalog.schema.table, got: {full_name!r}")
    cat, sch, tbl = (_safe_ident(parts[0]), _safe_ident(parts[1]), _safe_ident(parts[2]))
    return f"`{cat}`.`{sch}`.`{tbl}`"


@dataclass(frozen=True)
class SampleRunResult:
    attempted: int
    succeeded: int
    failed: int


class WorkspaceSampleWriteService:
    """
    Writes fast preview samples into workspace_table.sample_rows_json.

    Strategy:
      - Prefer base table (variant_code IS NULL) for each model_table_id when present.
      - Only sample rows for mapped tables (model_table_id IS NOT NULL)
      - Only sample rows that are new/changed (sample_ran_at IS NULL OR sample_ran_at < last_seen_at)
    """

    def __init__(self, *, sql: DatabricksSQLExecutor, mysql: Optional[SQLExecutor] = None):
        self._sql = sql
        self._mysql = mysql or MySQLSQLExecutor()

    def refresh_samples(
        self,
        *,
        workspace_id: str,
        schema_name: str = "asset",
        limit_rows: int = 10,
        max_tables: int = 200,  # safety guard; adjust as needed
    ) -> SampleRunResult:
        limit_rows = int(limit_rows)
        max_tables = int(max_tables)

        # Pick representative tables to sample
        pick_sql = """
WITH ranked AS (
  SELECT
    wt.id,
    wt.full_name,
    wt.model_table_id,
    wt.variant_code,
    wt.last_seen_at,
    wt.sample_ran_at,
    ROW_NUMBER() OVER (
      PARTITION BY wt.model_table_id
      ORDER BY
        CASE WHEN wt.variant_code IS NULL THEN 0 ELSE 1 END,
        wt.full_name
    ) AS rn
  FROM workspace_table wt
  WHERE wt.workspace_id = :ws
    AND wt.schema_name = :schema
    AND wt.exists_in_dbx = 1
    AND wt.model_table_id IS NOT NULL
    AND (wt.sample_ran_at IS NULL OR wt.sample_ran_at < wt.last_seen_at)
)
SELECT id, full_name
FROM ranked
WHERE rn = 1
ORDER BY id
LIMIT :max_tables
"""
        targets = self._mysql.execute_query_mappings(
            pick_sql,
            {"ws": workspace_id, "schema": schema_name, "max_tables": max_tables},
        )

        attempted = len(targets)
        if attempted == 0:
            return SampleRunResult(attempted=0, succeeded=0, failed=0)

        ok = 0
        bad = 0

        for t in targets:
            wtid = int(t["id"])
            full_name = str(t["full_name"])

            ran_at = datetime.utcnow()

            try:
                quoted = _quote_full_name(full_name)
                sql_text = f"SELECT * FROM {quoted} LIMIT {limit_rows}"

                resp = self._sql.submit_statement(sql_text, result_format="ARROW_STREAM")
                table: Optional[pa.Table] = resp.get("table")

                rows: List[Dict[str, Any]] = []
                if table is not None and table.num_rows > 0:
                    rows = table.to_pylist()

                payload = json.dumps(rows, default=str)

                with self._mysql.transaction() as tx:
                    tx.execute_write(
                        """
                        UPDATE workspace_table
                        SET sample_rows_json = :json,
                            sample_ran_at    = :ran_at,
                            sample_error     = NULL,
                            updated_at       = CURRENT_TIMESTAMP
                        WHERE id = :id
                        """,
                        {"json": payload, "ran_at": ran_at, "id": wtid},
                    )

                ok += 1

            except Exception as e:
                logger.exception("Sample capture failed for workspace_table.id=%s full_name=%s", wtid, full_name)
                msg = (str(e) or "sample failed")[:500]

                with self._mysql.transaction() as tx:
                    tx.execute_write(
                        """
                        UPDATE workspace_table
                        SET sample_rows_json = NULL,
                            sample_ran_at    = :ran_at,
                            sample_error     = :err,
                            updated_at       = CURRENT_TIMESTAMP
                        WHERE id = :id
                        """,
                        {"ran_at": ran_at, "err": msg, "id": wtid},
                    )

                bad += 1

        return SampleRunResult(attempted=attempted, succeeded=ok, failed=bad)
