# tests/analytics/test_metadata_sync_service.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.analytics.metadata_sync_service import MetadataSyncService


def _make_registry(dialect="databricks"):
    executor = MagicMock()
    executor.get_dialect.return_value = dialect
    registry = MagicMock()
    registry.get.return_value = executor
    return registry, executor


def _make_provider(tables=None, columns=None):
    provider = MagicMock()
    provider.list_tables.return_value = tables or [
        {"table_name": "orders", "table_type": "TABLE", "comment": None}
    ]
    provider.list_columns.return_value = columns or [
        {"table_name": "orders", "column_name": "id",
         "data_type": "BIGINT", "ordinal_position": 1,
         "is_nullable": False, "comment": None}
    ]
    return provider


def test_sync_returns_summary():
    registry, executor = _make_registry()
    provider = _make_provider()
    writer = MagicMock()
    writer.upsert_tables.return_value = {"tables_upserted": 1, "name_to_id": {"orders": 1}}
    writer.upsert_columns.return_value = {"columns_upserted": 1, "cols_by_table_id": {1: {"id"}}}

    svc = MetadataSyncService(registry=registry, writer=writer)

    with patch("app.services.analytics.metadata_sync_service.MetadataProviderFactory.create",
               return_value=provider):
        result = svc.sync_workspace_source_metadata(
            datasource_name="primary",
            catalog=None,
            schema="sales",
        )

    assert "tables_upserted" in result
    assert result["tables_upserted"] == 1


def test_sync_calls_profiling_when_enabled():
    registry, executor = _make_registry()
    provider = _make_provider()
    writer = MagicMock()
    writer.upsert_tables.return_value = {"tables_upserted": 1, "name_to_id": {"orders": 1}}
    writer.upsert_columns.return_value = {"columns_upserted": 1, "cols_by_table_id": {}}
    profiler = MagicMock()
    profiler.profile_and_persist.return_value = {"profiled": 1, "errors": 0}

    svc = MetadataSyncService(registry=registry, writer=writer, profiler=profiler)

    with patch("app.services.analytics.metadata_sync_service.MetadataProviderFactory.create",
               return_value=provider):
        svc.sync_workspace_source_metadata(
            datasource_name="primary",
            catalog=None,
            schema="sales",
            run_profiling=True,
        )

    assert profiler.profile_and_persist.called


def test_sync_does_not_call_profiling_when_disabled():
    registry, executor = _make_registry()
    provider = _make_provider()
    writer = MagicMock()
    writer.upsert_tables.return_value = {"tables_upserted": 1, "name_to_id": {"orders": 1}}
    writer.upsert_columns.return_value = {"columns_upserted": 1, "cols_by_table_id": {}}
    profiler = MagicMock()

    svc = MetadataSyncService(registry=registry, writer=writer, profiler=profiler)

    with patch("app.services.analytics.metadata_sync_service.MetadataProviderFactory.create",
               return_value=provider):
        svc.sync_workspace_source_metadata(
            datasource_name="primary", catalog=None, schema="sales", run_profiling=False
        )

    profiler.profile_and_persist.assert_not_called()


def test_sync_marks_missing_tables_and_columns():
    registry, executor = _make_registry()
    provider = _make_provider()
    writer = MagicMock()
    writer.upsert_tables.return_value = {"tables_upserted": 1, "name_to_id": {"orders": 1}}
    writer.upsert_columns.return_value = {"columns_upserted": 1, "cols_by_table_id": {1: {"id"}}}

    svc = MetadataSyncService(registry=registry, writer=writer)

    with patch("app.services.analytics.metadata_sync_service.MetadataProviderFactory.create",
               return_value=provider):
        svc.sync_workspace_source_metadata(
            datasource_name="primary", catalog=None, schema="sales"
        )

    writer.mark_tables_missing.assert_called_once()
    writer.mark_columns_missing.assert_called_once()


def test_sync_filters_tables_by_table_names():
    registry, executor = _make_registry()
    provider = _make_provider(tables=[
        {"table_name": "orders", "table_type": "TABLE", "comment": None},
        {"table_name": "items",  "table_type": "TABLE", "comment": None},
    ])
    writer = MagicMock()
    writer.upsert_tables.return_value = {"tables_upserted": 1, "name_to_id": {"orders": 1}}
    writer.upsert_columns.return_value = {"columns_upserted": 0, "cols_by_table_id": {}}

    svc = MetadataSyncService(registry=registry, writer=writer)

    with patch("app.services.analytics.metadata_sync_service.MetadataProviderFactory.create",
               return_value=provider):
        svc.sync_workspace_source_metadata(
            datasource_name="primary", catalog=None, schema="sales",
            table_names=["orders"],  # only sync orders
        )

    # upsert_tables should only receive the filtered table
    tables_arg = writer.upsert_tables.call_args[1]["tables"]
    assert len(tables_arg) == 1
    assert tables_arg[0]["table_name"] == "orders"


def test_sync_emits_progress_updates():
    registry, _executor = _make_registry()
    provider = _make_provider(
        tables=[
            {"table_name": "orders", "table_type": "TABLE", "comment": None},
            {"table_name": "items", "table_type": "TABLE", "comment": None},
        ],
        columns=[
            {
                "table_name": "orders",
                "column_name": "id",
                "data_type": "BIGINT",
                "ordinal_position": 1,
                "is_nullable": False,
                "comment": None,
            },
            {
                "table_name": "items",
                "column_name": "id",
                "data_type": "BIGINT",
                "ordinal_position": 1,
                "is_nullable": False,
                "comment": None,
            },
        ],
    )
    writer = MagicMock()
    writer.upsert_tables.return_value = {
        "tables_upserted": 2,
        "name_to_id": {"orders": 1, "items": 2},
    }
    writer.upsert_columns.return_value = {
        "columns_upserted": 2,
        "cols_by_table_id": {1: {"id"}, 2: {"id"}},
    }

    svc = MetadataSyncService(registry=registry, writer=writer)
    progress_events: list[dict] = []

    with patch(
        "app.services.analytics.metadata_sync_service.MetadataProviderFactory.create",
        return_value=provider,
    ):
        result = svc.sync_workspace_source_metadata(
            datasource_name="primary",
            catalog=None,
            schema="sales",
            progress_callback=lambda event: progress_events.append(event),
        )

    assert progress_events
    assert progress_events[0]["tables_total"] == 2
    assert progress_events[-1]["tables_done"] == 2
    assert progress_events[0]["columns_total"] == 2
    assert progress_events[-1]["columns_done"] == 2
    assert progress_events[-1]["current_phase"] == "completed"
    assert result["tables_done"] == 2


def test_sync_propagates_overwrite_descriptions_to_writer_and_enricher():
    registry, _executor = _make_registry()
    provider = _make_provider()
    writer = MagicMock()
    writer.upsert_tables.return_value = {"tables_upserted": 1, "name_to_id": {"orders": 1}}
    writer.upsert_columns.return_value = {"columns_upserted": 1, "cols_by_table_id": {1: {"id"}}}
    enricher = MagicMock()
    enricher.enrich.return_value = {"enriched": 1, "errors": 0}

    svc = MetadataSyncService(registry=registry, writer=writer, enricher=enricher)

    with patch(
        "app.services.analytics.metadata_sync_service.MetadataProviderFactory.create",
        return_value=provider,
    ):
        svc.sync_workspace_source_metadata(
            datasource_name="primary",
            catalog=None,
            schema="sales",
            run_enrichment=True,
            overwrite_descriptions=True,
        )

    assert writer.upsert_tables.call_args[1]["overwrite_descriptions"] is True
    assert writer.upsert_columns.call_args[1]["overwrite_descriptions"] is True
    assert enricher.enrich.call_args[1]["overwrite"] is True
