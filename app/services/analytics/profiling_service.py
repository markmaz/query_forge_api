# app/services/analytics/profiling_service.py
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.metadata_provider_abc import MetadataProvider
from app.services.metadata.gateway import MetadataGateway

logger = logging.getLogger(__name__)

_DEFAULT_OPTIONS: dict[str, Any] = {
    "sample_percent": 0.10,
    "sample_row_cap": 200_000,
    "per_column_limit": 10,
    "max_distinct_for_top_values": 5_000,
    "max_string_length_for_top_values": 500,
    "profile_top_values_only_for_string_types": False,
    "skip_top_values_for_id_like_cols": False,
}


class ProfilingService:
    """Drives per-table column profiling and persists results to model_column."""

    def __init__(self, *, mysql: ForgeMetaSQL | None = None, metadata_gateway: MetadataGateway | None = None) -> None:
        self._mysql = mysql or ForgeMetaSQL()
        self._metadata_gateway = metadata_gateway or MetadataGateway(sql=self._mysql)

    def profile_and_persist(
        self,
        *,
        provider: MetadataProvider,
        catalog: str | None,
        schema: str,
        table_id_by_name: dict[str, int],
        columns: list[dict],
        options: dict,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        opts = {**_DEFAULT_OPTIONS, **(options or {})}

        # Group columns by table name (only for tables we have IDs for)
        cols_by_table: dict[str, list[dict]] = {}
        for col in columns:
            tn = col["table_name"]
            if tn in table_id_by_name:
                cols_by_table.setdefault(tn, []).append(col)

        profiled = 0
        tables_failed = 0
        total_columns = sum(len(v) for v in cols_by_table.values())
        columns_done = 0
        columns_failed = 0

        def _emit_progress(
            *,
            current_table: str | None = None,
            current_column: str | None = None,
        ) -> None:
            if progress_callback is None:
                return
            progress_callback(
                {
                    "phase": "profiling",
                    "columns_total": total_columns,
                    "columns_done": columns_done,
                    "columns_failed": columns_failed,
                    "current_table": current_table,
                    "current_column": current_column,
                }
            )

        _emit_progress()

        for table_name, table_cols in cols_by_table.items():
            table_id = table_id_by_name[table_name]
            parts = [p for p in [catalog, schema, table_name] if p]
            table_ref = ".".join(parts)
            _emit_progress(
                current_table=table_name,
                current_column=str(table_cols[0].get("column_name") or "") if table_cols else None,
            )

            try:
                stats = provider.profile_table_columns(
                    table_ref=table_ref,
                    columns=table_cols,
                    options=opts,
                )
                persisted_columns = self._persist_column_stats(
                    table_id=table_id,
                    col_stats=stats,
                    table_cols=table_cols,
                )
                profiled += 1
                columns_done += persisted_columns
                _emit_progress(
                    current_table=table_name,
                    current_column=str(table_cols[-1].get("column_name") or "") if table_cols else None,
                )
            except Exception:
                logger.exception(
                    "ProfilingService: failed to profile table %s (id=%d)",
                    table_name, table_id,
                )
                tables_failed += 1
                columns_failed += len(table_cols)
                _emit_progress(
                    current_table=table_name,
                    current_column=str(table_cols[-1].get("column_name") or "") if table_cols else None,
                )

        return {
            "profiled": profiled,
            "tables_failed": tables_failed,
            "errors": tables_failed,
            "columns_total": total_columns,
            "columns_done": columns_done,
            "columns_failed": columns_failed,
        }

    def _persist_column_stats(
        self,
        table_id: int,
        col_stats: dict[str, dict],
        table_cols: list[dict],
    ) -> int:
        now = datetime.utcnow()
        persisted = 0
        with self._mysql.transaction() as tx:
            for col in table_cols:
                cn = col["column_name"]
                stats = col_stats.get(cn, {})
                sample_error = stats.get("sample_error")

                top_values = stats.get("top_values") or []
                sample_stats = {
                    k: stats.get(k)
                    for k in ("null_count", "null_pct", "approx_distinct", "sample_row_count")
                    if k in stats
                }

                tx.execute_write(
                    """
UPDATE model_column
SET sample_values_json = :sample_values_json,
    sample_stats_json  = :sample_stats_json,
    sample_ran_at      = :sample_ran_at,
    sample_error       = :sample_error,
    updated_at         = CURRENT_TIMESTAMP
WHERE model_table_id = :table_id
  AND column_name    = :column_name
""",
                    {
                        "table_id": table_id,
                        "column_name": cn,
                        "sample_values_json": json.dumps(top_values),
                        "sample_stats_json": json.dumps(sample_stats),
                        "sample_ran_at": now,
                        "sample_error": str(sample_error)[:500] if sample_error else None,
                    },
                )
                self._metadata_gateway.sync_column_profile_from_model_table(
                    model_table_id=table_id,
                    column_name=cn,
                    sample_values_json=json.dumps(top_values),
                    sample_stats_json=json.dumps(sample_stats),
                    sample_ran_at=now,
                    sample_error=str(sample_error)[:500] if sample_error else None,
                )
                persisted += 1
        return persisted
