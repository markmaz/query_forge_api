from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import pyarrow as pa

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.workspace_inventory.workspace_snapshot_discovery import (
    build_uc_metadata_sql,
    discover_default_catalog_schema,
    is_qe_from_variant,
    qf_safe_ident,
    split_base_and_variant,
)
from app.services.workspace_inventory.workspace_snapshot_models import SnapshotResult
from app.services.workspace_inventory.workspace_snapshot_persistence import WorkspaceSnapshotPersistenceService
from app.services.workspace_inventory.workspace_snapshot_staging import stage_snapshot_rows

__all__ = [
    "SnapshotResult",
    "WorkspaceSnapshotService",
    "_qf_safe_ident",
    "_discover_default_catalog_schema",
    "_build_uc_metadata_sql",
    "_is_qe_from_variant",
    "_split_base_and_variant",
]


def _qf_safe_ident(s: str) -> str:
    return qf_safe_ident(s)


def _discover_default_catalog_schema(sql: ForgeQueryPort) -> Tuple[str, str]:
    return discover_default_catalog_schema(sql)


def _build_uc_metadata_sql(catalog: str, schema: str) -> str:
    return build_uc_metadata_sql(catalog, schema)


def _is_qe_from_variant(qf_variant_code: Optional[str]) -> bool:
    return is_qe_from_variant(qf_variant_code)


def _split_base_and_variant(qf_table_name: str, accepted_bases: Set[str]) -> Tuple[str, Optional[str]]:
    return split_base_and_variant(qf_table_name, accepted_bases)


class WorkspaceSnapshotService:
    """
    Snapshots UC metadata into:
      - workspace_table (per physical table)
      - workspace_column (per physical table column)

    Mapping rule:
      - each discovered physical table becomes a workspace_table row
      - base/variant handling stays local to workspace metadata only
    """

    def __init__(self, *, sql: ForgeQueryPort, mysql: Optional[ForgeQueryPort] = None):
        self._sql = sql
        self._mysql = mysql or ForgeMetaSQL()
        self._persistence = WorkspaceSnapshotPersistenceService()

    def sync_snapshot(
        self,
        *,
        workspace_id: str,
        qf_schema_name: str = "asset",
        qf_catalog_name: Optional[str] = None,
    ) -> SnapshotResult:
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        if qf_catalog_name is None:
            qf_catalog_name, _ = discover_default_catalog_schema(self._sql)

        sql_text = build_uc_metadata_sql(catalog=qf_catalog_name, schema=qf_schema_name)
        response = self._sql.submit_statement(sql_text, qf_result_fmt="ARROW_STREAM")

        table: pa.Table = response.get("table")
        if table is None or table.num_rows == 0:
            return SnapshotResult(
                ok=True,
                workspace_id=workspace_id,
                qf_catalog_name=qf_catalog_name,
                qf_schema_name=qf_schema_name,
                run_id=run_id,
                ran_at_utc=now.isoformat(),
                tables_seen=0,
                columns_seen=0,
            )

        snapshot_rows: List[Dict[str, Any]] = table.to_pylist()

        with self._mysql.transaction() as tx:
            tx.execute_write(
                "INSERT INTO workspace (id) VALUES (:id) ON DUPLICATE KEY UPDATE id=id",
                {"id": workspace_id},
            )

            accepted_bases: Set[str] = set()
            staged_tables, staged_columns, _seen_bases = stage_snapshot_rows(snapshot_rows, accepted_bases)

            self._persistence.mark_stale(tx, workspace_id=workspace_id, qf_schema_name=qf_schema_name)
            self._persistence.upsert_tables(
                tx,
                workspace_id=workspace_id,
                now=now,
                staged_tables=staged_tables,
            )

            table_id_by_full_name = self._persistence.load_current_workspace_table_ids(
                tx,
                workspace_id=workspace_id,
                qf_schema_name=qf_schema_name,
            )
            self._persistence.upsert_columns(
                tx,
                now=now,
                staged_columns=staged_columns,
                table_id_by_full_name=table_id_by_full_name,
            )

        return SnapshotResult(
            ok=True,
            workspace_id=workspace_id,
            qf_catalog_name=qf_catalog_name,
            qf_schema_name=qf_schema_name,
            run_id=run_id,
            ran_at_utc=now.isoformat(),
            tables_seen=len(staged_tables),
            columns_seen=len(staged_columns),
        )
