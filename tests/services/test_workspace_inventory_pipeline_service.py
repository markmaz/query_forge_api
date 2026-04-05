from __future__ import annotations

from app.services.workspace_inventory.workspace_inventory_pipeline_service import WorkspacePipelineService
from app.services.workspace_inventory.workspace_snapshot_service import SnapshotResult
from tests._support.fakes import FakeDatabricksForgeQueryPort


def test_sync_snapshot_returns_dict() -> None:
    pipeline = WorkspacePipelineService(sql=FakeDatabricksForgeQueryPort())
    pipeline._snap.sync_snapshot = lambda **_kwargs: SnapshotResult(
        ok=True,
        workspace_id="ws",
        qf_catalog_name="main",
        qf_schema_name="asset",
        run_id="rid",
        ran_at_utc="now",
        tables_seen=1,
        columns_seen=2,
    )
    pipeline._samples.refresh_model_samples = lambda **_kwargs: {"columns_updated": 0}

    result = pipeline.sync_snapshot(workspace_id="ws")
    assert result["workspace_id"] == "ws"
    assert result["tables_seen"] == 1
    assert result["column_samples"]["columns_updated"] == 0


def test_sync_snapshot_runs_column_sampling_by_default() -> None:
    pipeline = WorkspacePipelineService(sql=FakeDatabricksForgeQueryPort())
    pipeline._snap.sync_snapshot = lambda **_kwargs: SnapshotResult(
        ok=True,
        workspace_id="ws",
        qf_catalog_name="main",
        qf_schema_name="asset",
        run_id="rid",
        ran_at_utc="now",
        tables_seen=1,
        columns_seen=2,
    )
    called = {}

    def _refresh_model_samples(**kwargs):
        called["kwargs"] = kwargs
        return {"columns_updated": 2}

    pipeline._samples.refresh_model_samples = _refresh_model_samples

    result = pipeline.sync_snapshot(workspace_id="ws")

    assert called["kwargs"] == {"workspace_id": "ws", "schema_name": "asset"}
    assert result["column_samples"]["columns_updated"] == 2


def test_sync_snapshot_skips_column_sampling_when_disabled() -> None:
    pipeline = WorkspacePipelineService(sql=FakeDatabricksForgeQueryPort())
    pipeline._snap.sync_snapshot = lambda **_kwargs: SnapshotResult(
        ok=True,
        workspace_id="ws",
        qf_catalog_name="main",
        qf_schema_name="asset",
        run_id="rid",
        ran_at_utc="now",
        tables_seen=1,
        columns_seen=2,
    )
    called = {"count": 0}

    def _refresh_samples(**_kwargs):
        called["count"] += 1
        return {"columns_updated": 2}

    pipeline._samples.refresh_model_samples = _refresh_samples

    result = pipeline.sync_snapshot(workspace_id="ws", sample_rows=False)

    assert called["count"] == 0
    assert "column_samples" not in result
