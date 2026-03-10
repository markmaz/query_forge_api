from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.adapters.databricks_sql_executor import DatabricksForgeQueryPort
from app.services.models.model_sample_write_service import ModelSampleService
from app.services.workspace_inventory.workspace_snapshot_service import SnapshotResult, WorkspaceSnapshotService


class WorkspacePipelineService:
    """Coordinate workspace snapshot refresh operations."""

    def __init__(self, *, sql: DatabricksForgeQueryPort):
        self._snapshot_service = WorkspaceSnapshotService(sql=sql)
        self._sample_service = ModelSampleService(sql=sql)
        # Backward-compatible attribute names used in tests/legacy callsites.
        self._snap = self._snapshot_service
        self._samples = self._sample_service

    def sync_snapshot(
        self,
        *,
        workspace_id: str,
        schema_name: str = "asset",
        catalog_name: str | None = None,
        sample_rows: bool = True,
    ) -> dict[str, Any]:
        del sample_rows
        result: SnapshotResult = self._snapshot_service.sync_snapshot(
            workspace_id=workspace_id,
            qf_schema_name=schema_name,
            qf_catalog_name=catalog_name,
        )
        return asdict(result)
