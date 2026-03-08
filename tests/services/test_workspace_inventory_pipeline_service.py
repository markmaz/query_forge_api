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

    result = pipeline.sync_snapshot(workspace_id="ws")
    assert result["workspace_id"] == "ws"
    assert result["tables_seen"] == 1
