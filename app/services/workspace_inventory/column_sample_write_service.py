from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pyarrow as pa

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.metadata.gateway import MetadataGateway

logger = logging.getLogger(__name__)

# Keep this conservative; if you have weird identifiers, we still support them via backticks escaping.
SAFE_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _quote_uc_ident(ident: str) -> str:
    """
    Quote `catalog.schema.table` into `cat`.`sch`.`tbl` for Spark SQL.
    Escapes any backticks inside parts.
    """
    parts = [p.strip() for p in (ident or "").split(".") if p.strip()]
    if len(parts) != 3:
        return ident
    quoted = []
    for p in parts:
        p = p.replace("`", "``")
        quoted.append(f"`{p}`")
    return ".".join(quoted)


def _quote_col(col: str) -> str:
    """
    Quote a column name safely for SQL.
    - If simple (A-Za-z0-9_), we still quote it for consistency.
    - If it contains other chars, backticks still work if we escape internal backticks.
    """
    c = (col or "").strip()
    if not c:
        raise ValueError("Empty column name")
    c = c.replace("`", "``")
    return f"`{c}`"


class ColumnSampleWriteService:
    """
    Column-level sampling into workspace_column sample fields.
    """

    def __init__(
        self,
        *,
        sql: ForgeQueryPort,
        mysql: Optional[ForgeQueryPort] = None,
        metadata_gateway: Optional[MetadataGateway] = None,
    ):
        self._sql = sql
        self._mysql = mysql or ForgeMetaSQL()
        self._metadata_gateway = metadata_gateway or MetadataGateway(sql=self._mysql)

    def _pick_representative_tables(self, *, workspace_id: str, schema_name: str) -> List[Tuple[int, str]]:
        """
        Returns list of (workspace_table_id, full_name) choosing one physical table row per workspace table.
        """
        sql = """
SELECT
  wt.id AS workspace_table_id,
  wt.full_name
FROM workspace_table wt
WHERE wt.workspace_id = :ws
  AND wt.schema_name = :schema
  AND wt.exists_in_dbx = 1
ORDER BY
  wt.id,
  CASE WHEN wt.variant_code IS NULL THEN 0 ELSE 1 END,
  wt.full_name
"""
        rows = self._mysql.execute_query_mappings(
            sql,
            {"ws": workspace_id, "schema": schema_name},
        )

        out: List[Tuple[int, str]] = []
        seen = set()
        for r in rows:
            workspace_table_id = int(r["workspace_table_id"])
            if workspace_table_id in seen:
                continue
            seen.add(workspace_table_id)
            out.append((workspace_table_id, str(r["full_name"])))
        return out

    def _list_workspace_columns(self, *, workspace_table_id: int, active_only: bool = True) -> List[Dict[str, Any]]:
        sql = """
SELECT id, column_name, data_type, nullable, is_active
FROM workspace_column
WHERE workspace_table_id = :workspace_table_id
  AND (:active_only = 0 OR is_active = 1)
ORDER BY ordinal_position, column_name
"""
        rows = self._mysql.execute_query_mappings(
            sql,
            {"workspace_table_id": int(workspace_table_id), "active_only": 1 if active_only else 0},
        )
        return [dict(r) for r in rows]

    def _fetch_column_stats(self, *, full_name: str, column_name: str, timeout_s: Optional[int] = 120) -> Dict[str, Any]:
        tbl = _quote_uc_ident(full_name)
        col = _quote_col(column_name)

        sql_text = f"""
SELECT
  COUNT(1)                                  AS sample_row_count,
  SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS null_count,
  approx_count_distinct({col})              AS approx_distinct_count
FROM {tbl}
TABLESAMPLE (1 PERCENT)
"""
        resp = self._sql.submit_statement(
            sql_text,
            qf_result_fmt="ARROW_STREAM",
            qf_timeout_s=timeout_s,  # if your executor supports it
        )

        table: Optional[pa.Table] = resp.get("table")
        if table is None or table.num_rows == 0:
            return {"total_rows": 0, "non_null_rows": 0, "null_pct": None, "approx_distinct": None}

        row = table.to_pylist()[0]
        sample_row_count = int(row.get("sample_row_count") or 0)
        null_count = int(row.get("null_count") or 0)
        approx_distinct = row.get("approx_distinct_count")
        approx_distinct = int(approx_distinct) if approx_distinct is not None else None

        null_pct = (float(null_count) / float(sample_row_count)) if sample_row_count > 0 else None

        return {
        "sample_row_count": sample_row_count,
        "null_count": null_count,
        "null_pct": null_pct,
        "approx_distinct": approx_distinct,
        }

    def _fetch_column_samples(
        self,
        *,
        full_name: str,
        column_name: str,
        limit: int = 10,
        timeout_s: Optional[int] = 120,
    ) -> List[str]:
        tbl = _quote_uc_ident(full_name)
        col = _quote_col(column_name)

        sql_text = f"""
    SELECT CAST({col} AS STRING) AS value, COUNT(1) AS n
    FROM {tbl}
    TABLESAMPLE (1 PERCENT)
    WHERE {col} IS NOT NULL
    GROUP BY {col}
    ORDER BY n DESC
    LIMIT {int(limit)}
    """

        resp = self._sql.submit_statement(
            sql_text,
            qf_result_fmt="ARROW_STREAM",
            qf_timeout_s=timeout_s,
        )

        table: Optional[pa.Table] = resp.get("table")
        if table is None or table.num_rows == 0:
            return []

        out: List[str] = []
        for r in table.to_pylist():
            v = r.get("value")
            if v is None:
                continue
            s = str(v)
            if len(s) > 500:
                s = s[:500] + "…"
            out.append(s)
        return out

    def refresh_model_samples(
        self,
        *,
        workspace_id: str,
        schema_name: str = "asset",
        per_column_limit: int = 10,
        max_tables: Optional[int] = None,
        active_only: bool = True,
        distinct_values: bool = True,
        statement_timeout_s: Optional[int] = 120,
    ) -> Dict[str, Any]:
        """
        Sample workspace columns and persist results on workspace_column.
        """
        picked = self._pick_representative_tables(workspace_id=workspace_id, schema_name=schema_name)
        if max_tables is not None:
            picked = picked[: int(max_tables)]

        now = datetime.now(timezone.utc)

        tables_attempted = 0
        tables_processed = 0

        cols_attempted = 0
        cols_updated = 0
        cols_failed = 0

        with self._mysql.transaction() as tx:
            for workspace_table_id, full_name in picked:
                tables_attempted += 1
                cols = self._list_workspace_columns(workspace_table_id=workspace_table_id, active_only=active_only)
                if not cols:
                    continue

                tables_processed += 1

                for c in cols:
                    cols_attempted += 1
                    col_id = int(c["id"])
                    col_name = str(c["column_name"])

                    try:
                        stats = self._fetch_column_stats(
                            full_name=full_name,
                            column_name=col_name,
                            qf_timeout_s=statement_timeout_s,
                        )
                        samples = self._fetch_column_samples(
                            full_name=full_name,
                            column_name=col_name,
                            limit=per_column_limit,
                            distinct=distinct_values,
                            qf_timeout_s=statement_timeout_s,
                        )

                        tx.execute_write(
                            """
                            UPDATE workspace_column
                            SET sample_values_json = :vals,
                                sample_stats_json  = :stats,
                                sample_ran_at      = :ran_at,
                                sample_error       = NULL,
                                metadata_updated_at = CURRENT_TIMESTAMP,
                                updated_at         = CURRENT_TIMESTAMP
                            WHERE id = :id
                            """,
                            {
                                "id": col_id,
                                "vals": json.dumps(samples, ensure_ascii=False),
                                "stats": json.dumps(stats, ensure_ascii=False, default=str),
                                "ran_at": now,
                            },
                        )
                        self._metadata_gateway.sync_column_profile(
                            workspace_column_id=col_id,
                            sample_values_json=json.dumps(samples, ensure_ascii=False),
                            sample_stats_json=json.dumps(stats, ensure_ascii=False, default=str),
                            sample_ran_at=now,
                            sample_error=None,
                        )
                        cols_updated += 1

                    except Exception as e:
                        logger.exception(
                            "Column sample failed workspace_table_id=%s col_id=%s col=%s full_name=%s",
                            workspace_table_id,
                            col_id,
                            col_name,
                            full_name,
                        )
                        msg = (str(e) or "sample failed")[:500]
                        tx.execute_write(
                            """
                            UPDATE workspace_column
                            SET sample_values_json = NULL,
                                sample_stats_json  = NULL,
                                sample_ran_at      = :ran_at,
                                sample_error       = :err,
                                metadata_updated_at = CURRENT_TIMESTAMP,
                                updated_at         = CURRENT_TIMESTAMP
                            WHERE id = :id
                            """,
                            {"id": col_id, "ran_at": now, "err": msg},
                        )
                        self._metadata_gateway.sync_column_profile(
                            workspace_column_id=col_id,
                            sample_values_json=json.dumps([]),
                            sample_stats_json=json.dumps({}),
                            sample_ran_at=now,
                            sample_error=msg,
                        )
                        cols_failed += 1

        return {
            "ok": True,
            "workspace_id": workspace_id,
            "schema_name": schema_name,
            "ran_at_utc": now.isoformat(),
            "tables_attempted": tables_attempted,
            "tables_processed": tables_processed,
            "columns_attempted": cols_attempted,
            "columns_updated": cols_updated,
            "columns_failed": cols_failed,
            "per_column_limit": int(per_column_limit),
            "distinct_values": bool(distinct_values),
            "active_only": bool(active_only),
        }
