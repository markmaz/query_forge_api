from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from celery import shared_task
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError

logger = logging.getLogger(__name__)

INGESTION_PROGRESS_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError)
INGESTION_TASK_FALLBACK_ERRORS = (ForgeError, OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError)


def _get_sync_service():
    """Build MetadataSyncService from the live Flask app registry.

    Requires an active Flask application context.
    """
    from flask import current_app

    from app.services.analytics.dictionary_llm_adapter import DictionaryLLMAdapter
    from app.services.analytics.dictionary_enrichment_service import DictionaryEnrichmentService
    from app.services.analytics.metadata_sync_service import MetadataSyncService
    from app.services.analytics.model_catalog_writer import ModelCatalogWriter
    from app.services.analytics.profiling_service import ProfilingService
    from app.services.analytics.runtime_registry import build_runtime_registry

    registry = build_runtime_registry(
        fallback_registry=current_app.extensions.get("analytics_registry"),
    )
    return MetadataSyncService(
        registry=registry,
        writer=ModelCatalogWriter(),
        profiler=ProfilingService(),
        enricher=DictionaryEnrichmentService(llm=DictionaryLLMAdapter()),
    )


def _run_sync_and_update_record(
    *,
    run_id: str,
    datasource: str,
    catalog: str | None,
    schema: str,
    workspace_id: str | None,
    table_names: list[str] | None,
    run_profiling: bool,
    run_enrichment: bool,
    overwrite_descriptions: bool,
    profiling_options: dict | None,
    llm_id: int | None = None,
    sync_service,
    mysql: ForgeMetaSQL,
) -> None:
    """Run the sync and update the ingestion_run row. Extracted for testability."""
    error_text: str | None = None
    status = "failed"
    result: dict[str, Any] = {}
    advanced_progress_supported = True

    def _persist_progress(progress: dict[str, Any]) -> None:
        nonlocal advanced_progress_supported
        advanced_sql = """
UPDATE ingestion_run
SET tables_total    = :tables_total,
    tables_done     = :tables_done,
    tables_failed   = :tables_failed,
    tables_created  = :tables_created,
    tables_updated  = :tables_updated,
    columns_total   = :columns_total,
    columns_done    = :columns_done,
    columns_failed  = :columns_failed,
    columns_created = :columns_created,
    columns_updated = :columns_updated,
    current_phase   = :current_phase,
    current_table   = :current_table,
    current_column  = :current_column
WHERE id = :run_id
"""
        fallback_sql = """
UPDATE ingestion_run
SET tables_total    = :tables_total,
    tables_done     = :tables_done,
    tables_failed   = :tables_failed,
    tables_created  = :tables_created,
    tables_updated  = :tables_updated,
    columns_created = :columns_created,
    columns_updated = :columns_updated
WHERE id = :run_id
"""
        params = {
            "run_id": run_id,
            "tables_total": int(progress.get("tables_total") or 0),
            "tables_done": int(progress.get("tables_done") or 0),
            "tables_failed": int(progress.get("tables_failed") or 0),
            "tables_created": int(progress.get("tables_created") or 0),
            "tables_updated": int(progress.get("tables_updated") or 0),
            "columns_total": int(progress.get("columns_total") or 0),
            "columns_done": int(progress.get("columns_done") or 0),
            "columns_failed": int(progress.get("columns_failed") or 0),
            "columns_created": int(progress.get("columns_created") or 0),
            "columns_updated": int(progress.get("columns_updated") or 0),
            "current_phase": (
                str(progress.get("current_phase") or "").strip() or None
            ),
            "current_table": (
                str(progress.get("current_table") or "").strip() or None
            ),
            "current_column": (
                str(progress.get("current_column") or "").strip() or None
            ),
        }

        with mysql.transaction() as tx:
            if advanced_progress_supported:
                try:
                    tx.execute_write(advanced_sql, params)
                    return
                except INGESTION_PROGRESS_FALLBACK_ERRORS:
                    advanced_progress_supported = False
                    logger.warning(
                        "ingestion_run does not have advanced progress columns yet; "
                        "falling back to legacy progress updates"
                    )
            tx.execute_write(fallback_sql, params)

    try:
        result = sync_service.sync_workspace_source_metadata(
            datasource_name=datasource,
            catalog=catalog,
            schema=schema,
            workspace_id=workspace_id,
            table_names=table_names,
            run_profiling=run_profiling,
            run_enrichment=run_enrichment,
            overwrite_descriptions=overwrite_descriptions,
            profiling_options=profiling_options,
            llm_id=llm_id,
            progress_callback=_persist_progress,
        )
        status = "completed"
    except INGESTION_TASK_FALLBACK_ERRORS as exc:
        logger.exception("ingestion task %s failed", run_id)
        error_text = str(exc)[:2000]

    profiling = result.get("profiling") or {}
    enrichment = result.get("enrichment") or {}
    profiled_tables = int(profiling.get("profiled") or 0)
    profiling_errors = int(profiling.get("errors") or 0)
    enriched_columns = int(enrichment.get("enriched") or 0)
    enrichment_errors = int(enrichment.get("errors") or 0)
    tables_failed_total = (
        int(result.get("tables_failed", 0) or 0)
        + profiling_errors
        + enrichment_errors
    )

    if status == "completed" and (profiling_errors > 0 or enrichment_errors > 0):
        error_text = (
            f"Completed with warnings: profiling_errors={profiling_errors}, "
            f"enrichment_errors={enrichment_errors}"
        )

    advanced_final_sql = """
UPDATE ingestion_run
SET status          = :status,
    tables_total    = :tables_total,
    tables_done     = :tables_done,
    tables_failed   = :tables_failed,
    tables_created  = :tables_created,
    tables_updated  = :tables_updated,
    columns_total   = :columns_total,
    columns_done    = :columns_done,
    columns_failed  = :columns_failed,
    columns_created = :columns_created,
    columns_updated = :columns_updated,
    current_phase   = :current_phase,
    current_table   = :current_table,
    current_column  = :current_column,
    error           = :error,
    completed_at    = :completed_at
WHERE id = :run_id
"""
    fallback_final_sql = """
UPDATE ingestion_run
SET status          = :status,
    tables_total    = :tables_total,
    tables_done     = :tables_done,
    tables_failed   = :tables_failed,
    tables_created  = :tables_created,
    tables_updated  = :tables_updated,
    columns_created = :columns_created,
    columns_updated = :columns_updated,
    error           = :error,
    completed_at    = :completed_at
WHERE id = :run_id
"""
    final_params = {
        "run_id": run_id,
        "status": status,
        "tables_total": result.get("tables_discovered", 0),
        "tables_done": result.get("tables_done", result.get("tables_upserted", 0)),
        "tables_failed": tables_failed_total,
        "tables_created": result.get("tables_upserted", 0),
        "tables_updated": profiled_tables,
        "columns_total": result.get("columns_total", result.get("columns_upserted", 0)),
        "columns_done": result.get("columns_done", result.get("columns_upserted", 0)),
        "columns_failed": result.get("columns_failed", 0),
        "columns_created": result.get("columns_upserted", 0),
        "columns_updated": enriched_columns,
        "current_phase": status,
        "current_table": None,
        "current_column": None,
        "error": error_text,
        "completed_at": datetime.now(timezone.utc),
    }
    with mysql.transaction() as tx:
        if advanced_progress_supported:
            try:
                tx.execute_write(advanced_final_sql, final_params)
                return
            except INGESTION_PROGRESS_FALLBACK_ERRORS:
                logger.warning(
                    "ingestion_run does not have advanced progress columns yet; "
                    "falling back to legacy final status update"
                )
        tx.execute_write(fallback_final_sql, final_params)


@shared_task(bind=True, name="qf.ingestion.sync_metadata")
def sync_metadata_task(
    _self,
    run_id: str,
    datasource: str,
    catalog: str | None,
    schema: str,
    workspace_id: str | None = None,
    table_names: list[str] | None = None,
    run_profiling: bool = False,
    run_enrichment: bool = False,
    overwrite_descriptions: bool = False,
    profiling_options: dict | None = None,
    llm_id: int | None = None,
) -> dict:
    mysql = ForgeMetaSQL()
    sync_service = _get_sync_service()

    _run_sync_and_update_record(
        run_id=run_id,
        datasource=datasource,
        catalog=catalog,
        schema=schema,
        workspace_id=workspace_id,
        table_names=table_names,
        run_profiling=run_profiling,
        run_enrichment=run_enrichment,
        overwrite_descriptions=overwrite_descriptions,
        profiling_options=profiling_options,
        llm_id=llm_id,
        sync_service=sync_service,
        mysql=mysql,
    )
    return {"run_id": run_id}
