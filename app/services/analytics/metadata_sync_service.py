# app/services/analytics/metadata_sync_service.py
from __future__ import annotations

import logging
from typing import Any, Callable

from app.services.analytics.metadata_provider_factory import MetadataProviderFactory
from app.services.analytics.model_catalog_writer import ModelCatalogWriter

logger = logging.getLogger(__name__)

_SYNC_BATCH_SIZE = 50


def _chunk(xs: list[dict], n: int = _SYNC_BATCH_SIZE) -> list[list[dict]]:
    return [xs[i:i + n] for i in range(0, len(xs), n)]


class MetadataSyncService:
    """Thin orchestrator: discover -> upsert -> (profile) -> (enrich) -> mark-missing."""

    def __init__(
        self,
        *,
        registry,
        writer: ModelCatalogWriter | None = None,
        profiler=None,
        enricher=None,
    ) -> None:
        self._registry = registry
        self._writer = writer or ModelCatalogWriter()
        self._profiler = profiler
        self._enricher = enricher

    def sync_workspace_source_metadata(
        self,
        datasource_name: str,
        catalog: str | None,
        schema: str,
        table_names: list[str] | None = None,
        run_profiling: bool = False,
        run_enrichment: bool = False,
        overwrite_descriptions: bool = False,
        profiling_options: dict | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        executor = self._registry.get(datasource_name)
        provider = MetadataProviderFactory.create(executor.get_dialect(), executor)

        # 1. Discover
        tables = provider.list_tables(catalog, schema)
        if table_names:
            names_set = set(table_names)
            tables = [t for t in tables if t["table_name"] in names_set]

        tables_total = len(tables)
        tables_done = 0
        tables_failed = 0
        tables_upserted = 0
        columns_upserted = 0
        columns_total = 0
        columns_done = 0
        columns_failed = 0
        current_phase = "discovering"
        current_table: str | None = None
        current_column: str | None = None

        discovered_table_names = {t["table_name"] for t in tables}
        columns = provider.list_columns(catalog, schema, list(discovered_table_names) or None)
        columns_total = len(columns)

        def _emit_progress() -> None:
            if progress_callback is None:
                return
            progress_callback(
                {
                    "tables_total": tables_total,
                    "tables_done": tables_done,
                    "tables_failed": tables_failed,
                    "tables_created": tables_upserted,
                    "tables_updated": 0,
                    "columns_total": columns_total,
                    "columns_done": columns_done,
                    "columns_failed": columns_failed,
                    "columns_remaining": max(columns_total - columns_done, 0),
                    "columns_created": columns_upserted,
                    "columns_updated": 0,
                    "current_phase": current_phase,
                    "current_table": current_table,
                    "current_column": current_column,
                }
            )

        current_phase = "upserting_columns"
        _emit_progress()

        # 2/3. Upsert tables/columns in batches so the caller can report progress.
        columns_by_table: dict[str, list[dict]] = {}
        for col in columns:
            table_name = str(col.get("table_name") or "").strip()
            if table_name:
                columns_by_table.setdefault(table_name, []).append(col)

        name_to_id: dict[str, int] = {}
        cols_by_table_id: dict[int, set] = {}
        cols_by_table_name: dict[str, set] = {}
        for table_batch in _chunk(tables):
            table_result = self._writer.upsert_tables(
                tables=table_batch,
                origin=executor.get_dialect(),
                overwrite_descriptions=overwrite_descriptions,
            )
            batch_name_to_id = table_result.get("name_to_id", {})
            name_to_id.update(batch_name_to_id)

            batch_columns: list[dict] = []
            for table in table_batch:
                table_name = str(table.get("table_name") or "").strip()
                if not table_name:
                    continue
                batch_columns.extend(columns_by_table.get(table_name, []))

            if batch_columns:
                first_col = batch_columns[0]
                current_table = str(first_col.get("table_name") or "").strip() or None
                current_column = str(first_col.get("column_name") or "").strip() or None
                _emit_progress()

            col_result = self._writer.upsert_columns(
                table_id_by_name=batch_name_to_id,
                columns=batch_columns,
                origin=executor.get_dialect(),
                overwrite_descriptions=overwrite_descriptions,
            )
            for table_id, col_names in col_result.get("cols_by_table_id", {}).items():
                cols_by_table_id.setdefault(int(table_id), set()).update(col_names)
            for table_name, col_names in col_result.get("cols_by_table_name", {}).items():
                cols_by_table_name.setdefault(str(table_name), set()).update(col_names)

            tables_done += len(table_batch)
            tables_upserted += int(table_result.get("tables_upserted", 0) or 0)
            columns_done += len(batch_columns)
            columns_upserted += int(col_result.get("columns_upserted", 0) or 0)
            if batch_columns:
                last_col = batch_columns[-1]
                current_table = str(last_col.get("table_name") or "").strip() or None
                current_column = str(last_col.get("column_name") or "").strip() or None
            _emit_progress()

        # 4. Mark missing
        self._writer.mark_tables_missing(
            seen_names=discovered_table_names,
            origin=executor.get_dialect(),
        )
        self._writer.mark_columns_missing(
            cols_by_table_id=cols_by_table_id,
            origin=executor.get_dialect(),
            cols_by_table_name=cols_by_table_name,
        )

        # 5. Optional profiling
        profiling_summary: dict = {}
        if run_profiling and self._profiler:
            try:
                current_phase = "profiling"
                columns_done = 0
                columns_failed = 0
                current_table = None
                current_column = None
                _emit_progress()

                def _on_profiling_progress(event: dict[str, Any]) -> None:
                    nonlocal current_phase, current_table, current_column, columns_total, columns_done, columns_failed
                    current_phase = str(event.get("phase") or "profiling")
                    current_table = (
                        str(event.get("current_table") or "").strip() or None
                    )
                    current_column = (
                        str(event.get("current_column") or "").strip() or None
                    )
                    columns_total = int(event.get("columns_total") or columns_total or 0)
                    columns_done = int(event.get("columns_done") or 0)
                    columns_failed = int(event.get("columns_failed") or 0)
                    _emit_progress()

                profiling_summary = self._profiler.profile_and_persist(
                    provider=provider,
                    catalog=catalog,
                    schema=schema,
                    table_id_by_name=name_to_id,
                    columns=columns,
                    options=profiling_options or {},
                    progress_callback=_on_profiling_progress,
                )
            except Exception:
                logger.exception(
                    "MetadataSyncService: profiling failed for %s/%s",
                    datasource_name, schema,
                )

        # 6. Optional enrichment
        enrichment_summary: dict = {}
        if run_enrichment and self._enricher:
            try:
                current_phase = "enrichment"
                columns_done = 0
                columns_failed = 0
                current_table = None
                current_column = None
                _emit_progress()

                def _on_enrichment_progress(event: dict[str, Any]) -> None:
                    nonlocal current_phase, current_table, current_column, columns_total, columns_done, columns_failed
                    current_phase = str(event.get("phase") or "enrichment")
                    current_table = (
                        str(event.get("current_table") or "").strip() or None
                    )
                    current_column = (
                        str(event.get("current_column") or "").strip() or None
                    )
                    columns_total = int(event.get("columns_total") or columns_total or 0)
                    columns_done = int(event.get("columns_done") or 0)
                    columns_failed = int(event.get("columns_failed") or 0)
                    _emit_progress()

                enrichment_summary = self._enricher.enrich(
                    table_id_by_name=name_to_id,
                    columns=columns,
                    overwrite=overwrite_descriptions,
                    progress_callback=_on_enrichment_progress,
                )
            except Exception:
                logger.exception(
                    "MetadataSyncService: enrichment failed for %s/%s",
                    datasource_name, schema,
                )

        current_phase = "completed"
        current_table = None
        current_column = None
        _emit_progress()

        return {
            "datasource": datasource_name,
            "catalog": catalog,
            "schema": schema,
            "tables_discovered": len(tables),
            "tables_upserted": tables_upserted,
            "tables_done": tables_done,
            "tables_failed": tables_failed,
            "columns_total": columns_total,
            "columns_done": columns_done,
            "columns_failed": columns_failed,
            "columns_upserted": columns_upserted,
            "profiling": profiling_summary,
            "enrichment": enrichment_summary,
        }
