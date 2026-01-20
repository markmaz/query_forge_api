from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional

from app.adapters.databricks_sql_executor import DatabricksSQLExecutor
from app.services.models.model_sample_write_service import ModelSampleService
from app.services.workspace_inventory.workspace_snapshot_service import SnapshotResult, WorkspaceSnapshotService


class WorkspacePipelineService:
    """
    Runs DBX catalog snapshot for a workspace.
    Reconciliation is computed-on-read elsewhere.
    """

    def __init__(self, *, sql: DatabricksSQLExecutor):
        self._snap = WorkspaceSnapshotService(sql=sql)
        self._samples = ModelSampleService(sql=sql)

    def sync_snapshot(
        self,
        *,
        workspace_id: str,
        schema_name: str = "asset",
        catalog_name: Optional[str] = None,
        sample_rows: bool = True,  # keep param name for backward compatibility
    ) -> Dict[str, Any]:
        res: SnapshotResult = self._snap.sync_snapshot(
            workspace_id=workspace_id,
            schema_name=schema_name,
            catalog_name=catalog_name,
        )

        out: Dict[str, Any] = asdict(res)
        return out