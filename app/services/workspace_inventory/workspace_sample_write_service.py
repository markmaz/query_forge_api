from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pyarrow as pa

from app.adapters.databricks_sql_executor import DatabricksForgeQueryPort
from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)

_SAFE_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


def _qf_safe_ident(value: str) -> str:
    if not _SAFE_IDENT.fullmatch(value):
        raise ValueError(f"Unsafe identifier: {value!r}")
    return value


def _quote_full_name(full_name: str) -> str:
    parts = [part.strip() for part in str(full_name or "").split(".") if part.strip()]
    if len(parts) != 3:
        raise ValueError(f"Expected full_name like catalog.schema.table, got: {full_name!r}")
    catalog, schema, table = (_qf_safe_ident(parts[0]), _qf_safe_ident(parts[1]), _qf_safe_ident(parts[2]))
    return f"`{catalog}`.`{schema}`.`{table}`"


@dataclass(frozen=True)
class SampleRunResult:
    attempted: int
    succeeded: int
    failed: int


class WorkspaceSampleWriteService:
    """Capture and persist sample rows for mapped workspace tables."""

    def __init__(self, *, sql: DatabricksForgeQueryPort, mysql: ForgeQueryPort | None = None):
        self._sql = sql
        self._mysql = mysql or ForgeMetaSQL()

    def refresh_samples(
        self,
        *,
        workspace_id: str,
        qf_schema_name: str = "asset",
        limit_rows: int = 10,
        max_tables: int = 200,
    ) -> SampleRunResult:
        candidates = self._list_targets(
            workspace_id=workspace_id,
            qf_schema_name=qf_schema_name,
            max_tables=int(max_tables),
        )

        attempted = len(candidates)
        if attempted == 0:
            return SampleRunResult(attempted=0, succeeded=0, failed=0)

        success_count = 0
        failed_count = 0
        row_limit = int(limit_rows)

        for candidate in candidates:
            table_id = int(candidate["id"])
            full_name = str(candidate["full_name"])
            ran_at = datetime.utcnow()

            try:
                rows = self._fetch_sample_rows(full_name=full_name, limit_rows=row_limit)
                self._persist_success(table_id=table_id, ran_at=ran_at, rows=rows)
                success_count += 1
            except Exception as exc:
                logger.exception("Sample capture failed workspace_table_id=%s full_name=%s", table_id, full_name)
                self._persist_failure(table_id=table_id, ran_at=ran_at, error=exc)
                failed_count += 1

        return SampleRunResult(attempted=attempted, succeeded=success_count, failed=failed_count)

    def _list_targets(self, *, workspace_id: str, qf_schema_name: str, max_tables: int) -> list[dict[str, Any]]:
        query = """
WITH ranked AS (
  SELECT
    wt.id,
    wt.full_name,
    COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name, wt.full_name) AS table_group,
    wt.variant_code,
    wt.last_seen_at,
    wt.sample_ran_at,
    ROW_NUMBER() OVER (
      PARTITION BY COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name, wt.full_name)
      ORDER BY
        CASE WHEN wt.variant_code IS NULL THEN 0 ELSE 1 END,
        wt.full_name
    ) AS rn
  FROM workspace_table wt
  WHERE wt.workspace_id = :ws
    AND wt.schema_name = :schema
    AND wt.exists_in_dbx = 1
    AND (wt.sample_ran_at IS NULL OR wt.sample_ran_at < wt.last_seen_at)
)
SELECT id, full_name
FROM ranked
WHERE rn = 1
ORDER BY id
LIMIT :max_tables
"""
        return self._mysql.execute_query_mappings(
            query,
            {"ws": workspace_id, "schema": qf_schema_name, "max_tables": max_tables},
        )

    def _fetch_sample_rows(self, *, full_name: str, limit_rows: int) -> list[dict[str, Any]]:
        sql_text = f"SELECT * FROM {_quote_full_name(full_name)} LIMIT {limit_rows}"
        response = self._sql.submit_statement(sql_text, qf_result_fmt="ARROW_STREAM")
        table: pa.Table | None = response.get("table")
        if table is None or table.num_rows == 0:
            return []
        return table.to_pylist()

    def _persist_success(self, *, table_id: int, ran_at: datetime, rows: list[dict[str, Any]]) -> None:
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
                {"json": payload, "ran_at": ran_at, "id": table_id},
            )

    def _persist_failure(self, *, table_id: int, ran_at: datetime, error: Exception) -> None:
        message = (str(error) or "sample failed")[:500]
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
                {"ran_at": ran_at, "err": message, "id": table_id},
            )
