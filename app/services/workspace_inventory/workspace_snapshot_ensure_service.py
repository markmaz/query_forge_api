from __future__ import annotations

from datetime import datetime, timedelta

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder
from app.services.workspace_inventory.workspace_inventory_pipeline_service import WorkspacePipelineService


class WorkspaceSnapshotEnsureService:
    """Ensure workspace snapshot data exists and is fresh enough for reads."""

    def __init__(self, *, sql: ForgeQueryPort | None = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def ensure(
        self,
        *,
        workspace_id: str,
        schema_name: str = "asset",
        min_fresh_age_minutes: int = 15,
    ) -> None:
        schema = (schema_name or "asset").strip()
        freshness_minutes = int(min_fresh_age_minutes)

        if not self._has_any_rows(workspace_id=workspace_id, schema_name=schema):
            self._run_snapshot(workspace_id=workspace_id, schema_name=schema)
            return

        last_seen_at = self._fetch_last_seen(workspace_id=workspace_id, schema_name=schema)
        if not last_seen_at:
            self._run_snapshot(workspace_id=workspace_id, schema_name=schema)
            return

        threshold = timedelta(minutes=freshness_minutes)
        if datetime.now() - last_seen_at > threshold:
            self._run_snapshot(workspace_id=workspace_id, schema_name=schema)

    def _has_any_rows(self, *, workspace_id: str, schema_name: str) -> bool:
        rows = self._sql.execute_query_mappings(
            """
            SELECT 1
            FROM workspace_table
            WHERE workspace_id=:ws
              AND schema_name=:schema
            LIMIT 1
            """,
            {"ws": workspace_id, "schema": schema_name},
        )
        return bool(rows)

    def _fetch_last_seen(self, *, workspace_id: str, schema_name: str):
        rows = self._sql.execute_query_mappings(
            """
            SELECT MAX(last_seen_at) AS max_seen
            FROM workspace_table
            WHERE workspace_id=:ws
              AND schema_name=:schema
            """,
            {"ws": workspace_id, "schema": schema_name},
        )
        if not rows:
            return None
        return rows[0].get("max_seen")

    def _run_snapshot(self, *, workspace_id: str, schema_name: str) -> None:
        context = WorkspaceContextBuilder().build(workspace_id)
        WorkspacePipelineService(sql=context.sql_exec).sync_snapshot(
            workspace_id=workspace_id,
            schema_name=schema_name,
        )
