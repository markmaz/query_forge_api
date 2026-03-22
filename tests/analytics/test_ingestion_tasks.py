from __future__ import annotations

from unittest.mock import MagicMock

from app.tasks.ingestion_tasks import _run_sync_and_update_record


def _make_mysql():
    mysql = MagicMock()
    tx = MagicMock()
    mysql.transaction.return_value.__enter__ = MagicMock(return_value=tx)
    mysql.transaction.return_value.__exit__ = MagicMock(return_value=False)
    return mysql, tx


def test_run_sync_writes_completed_status():
    mysql, tx = _make_mysql()
    sync_svc = MagicMock()
    sync_svc.sync_workspace_source_metadata.return_value = {
        "tables_upserted": 3,
        "columns_upserted": 20,
        "tables_discovered": 3,
    }

    _run_sync_and_update_record(
        run_id="test-run-id",
        datasource="primary",
        catalog=None,
        schema="sales",
        workspace_id="ws-1",
        table_names=None,
        run_profiling=False,
        run_enrichment=False,
        overwrite_descriptions=False,
        profiling_options=None,
        sync_service=sync_svc,
        mysql=mysql,
    )

    # transaction must be used (to write the update)
    assert mysql.transaction.called
    # Final execute_write must set status to 'completed'
    write_calls = tx.execute_write.call_args_list
    assert len(write_calls) >= 1
    final_sql = write_calls[-1][0][0]
    final_params = write_calls[-1][0][1] if len(write_calls[-1][0]) > 1 else {}
    assert "status" in final_sql.lower()
    assert final_params.get("status") == "completed"


def test_run_sync_writes_failed_status_on_error():
    mysql, tx = _make_mysql()
    sync_svc = MagicMock()
    sync_svc.sync_workspace_source_metadata.side_effect = RuntimeError("sync boom")

    _run_sync_and_update_record(
        run_id="test-run-id",
        datasource="primary",
        catalog=None,
        schema="sales",
        workspace_id="ws-1",
        table_names=None,
        run_profiling=False,
        run_enrichment=False,
        overwrite_descriptions=False,
        profiling_options=None,
        sync_service=sync_svc,
        mysql=mysql,
    )

    write_calls = tx.execute_write.call_args_list
    assert len(write_calls) >= 1
    final_params = write_calls[-1][0][1] if len(write_calls[-1][0]) > 1 else {}
    assert final_params.get("status") == "failed"
    # Error text should be captured
    assert "boom" in str(final_params.get("error") or "")


def test_run_sync_passes_options_to_service():
    mysql, tx = _make_mysql()
    sync_svc = MagicMock()
    sync_svc.sync_workspace_source_metadata.return_value = {
        "tables_upserted": 1,
        "columns_upserted": 5,
        "tables_discovered": 1,
    }

    _run_sync_and_update_record(
        run_id="test-run-id",
        datasource="primary",
        catalog="main",
        schema="sales",
        workspace_id="ws-1",
        table_names=["orders"],
        run_profiling=True,
        run_enrichment=False,
        overwrite_descriptions=True,
        profiling_options={"sample_percent": 0.05},
        sync_service=sync_svc,
        mysql=mysql,
    )

    call_kwargs = sync_svc.sync_workspace_source_metadata.call_args[1]
    assert call_kwargs["datasource_name"] == "primary"
    assert call_kwargs["catalog"] == "main"
    assert call_kwargs["schema"] == "sales"
    assert call_kwargs["workspace_id"] == "ws-1"
    assert call_kwargs["table_names"] == ["orders"]
    assert call_kwargs["run_profiling"] is True
    assert call_kwargs["overwrite_descriptions"] is True
    assert call_kwargs["profiling_options"] == {"sample_percent": 0.05}


def test_run_sync_persists_profiling_and_enrichment_counts():
    mysql, tx = _make_mysql()
    sync_svc = MagicMock()
    sync_svc.sync_workspace_source_metadata.return_value = {
        "tables_upserted": 3,
        "columns_upserted": 20,
        "tables_discovered": 3,
        "tables_done": 3,
        "tables_failed": 0,
        "profiling": {"profiled": 2, "errors": 1},
        "enrichment": {"enriched": 5, "errors": 2},
    }

    _run_sync_and_update_record(
        run_id="test-run-id",
        datasource="primary",
        catalog=None,
        schema="sales",
        workspace_id="ws-1",
        table_names=None,
        run_profiling=True,
        run_enrichment=True,
        overwrite_descriptions=False,
        profiling_options=None,
        sync_service=sync_svc,
        mysql=mysql,
    )

    final_params = tx.execute_write.call_args_list[-1][0][1]
    assert final_params["tables_updated"] == 2
    assert final_params["columns_updated"] == 5
    assert final_params["tables_failed"] == 3
    assert "Completed with warnings" in str(final_params.get("error") or "")
