from __future__ import annotations

from datetime import datetime, timedelta

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.ports.sql_executor import SQLExecutor
from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder
from app.services.workspace_inventory.workspace_inventory_pipeline_service import WorkspacePipelineService


class WorkspaceSnapshotEnsureService:
    """
    Ensures workspace_table/workspace_column cache exists for a workspace (+schema).
    Throttled so we don't snapshot on every request.
    """

    def __init__(self, *, sql: SQLExecutor | None = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def ensure(
        self,
        *,
        workspace_id: str,
        schema_name: str = "asset",
        min_fresh_age_minutes: int = 15,
    ) -> None:
        schema_name = (schema_name or "asset").strip()
        min_fresh_age_minutes = int(min_fresh_age_minutes)

        any_rows = self._sql.execute_query_mappings(
            """
            SELECT 1
            FROM workspace_table
            WHERE workspace_id=:ws
              AND schema_name=:schema
            LIMIT 1
            """,
            {"ws": workspace_id, "schema": schema_name},
        )
        any_row = any_rows[0] if any_rows else None

        if not any_row:
            self._run_snapshot(workspace_id=workspace_id, schema_name=schema_name)
            return

        last_seen_rows = self._sql.execute_query_mappings(
            """
            SELECT MAX(last_seen_at) AS max_seen
            FROM workspace_table
            WHERE workspace_id=:ws
              AND schema_name=:schema
            """,
            {"ws": workspace_id, "schema": schema_name},
        )
        last_seen = last_seen_rows[0] if last_seen_rows else None

        max_seen = last_seen.get("max_seen") if last_seen else None
        if not max_seen:
            self._run_snapshot(workspace_id=workspace_id, schema_name=schema_name)
            return

        age = datetime.now() - max_seen  # compare naive-to-naive
        if age > timedelta(minutes=min_fresh_age_minutes):
            self._run_snapshot(workspace_id=workspace_id, schema_name=schema_name)

    def _run_snapshot(self, *, workspace_id: str, schema_name: str) -> None:
        ctx = WorkspaceContextBuilder().build(workspace_id)
        WorkspacePipelineService(sql=ctx.sql_exec).sync_snapshot(
            workspace_id=workspace_id,
            schema_name=schema_name,
        )
