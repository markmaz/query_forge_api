from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.services.workspace_inventory.workspace_snapshot_models import ColumnStage, TableStage


class WorkspaceSnapshotPersistenceService:
    def mark_stale(self, tx, *, workspace_id: str, qf_schema_name: str) -> None:
        tx.execute_write(
            """
            UPDATE workspace_table
            SET exists_in_dbx=0, updated_at=CURRENT_TIMESTAMP
            WHERE workspace_id=:ws
              AND schema_name=:schema
            """,
            {"ws": workspace_id, "schema": qf_schema_name},
        )
        tx.execute_write(
            """
            UPDATE workspace_column wc
            JOIN workspace_table wt ON wt.id = wc.workspace_table_id
            SET wc.exists_in_dbx=0, wc.updated_at=CURRENT_TIMESTAMP
            WHERE wt.workspace_id=:ws
              AND wt.schema_name=:schema
            """,
            {"ws": workspace_id, "schema": qf_schema_name},
        )

    def upsert_tables(
        self,
        tx,
        *,
        workspace_id: str,
        now: datetime,
        staged_tables: List[TableStage],
    ) -> None:
        if not staged_tables:
            return

        payload = [
            {
                "workspace_id": workspace_id,
                "catalog_name": stage.qf_catalog_name,
                "schema_name": stage.qf_schema_name,
                "table_name": stage.qf_table_name,
                "full_name": stage.full_name,
                "variant_code": stage.qf_variant_code,
                "is_qe": stage.is_qe,
                "last_seen_at": now,
            }
            for stage in staged_tables
        ]

        tx.execute_write(
            """
            INSERT INTO workspace_table
            (workspace_id, catalog_name, schema_name, table_name, full_name,
             variant_code, is_qe, exists_in_dbx, last_seen_at, created_at)
            VALUES
            (:workspace_id, :catalog_name, :schema_name, :table_name, :full_name,
             :variant_code, :is_qe, 1, :last_seen_at, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
             catalog_name=VALUES(catalog_name),
             schema_name=VALUES(schema_name),
             table_name=VALUES(table_name),
             variant_code=VALUES(variant_code),
             is_qe=VALUES(is_qe),
             exists_in_dbx=1,
             last_seen_at=VALUES(last_seen_at),
             updated_at=CURRENT_TIMESTAMP
            """,
            payload,
        )

    def load_current_workspace_table_ids(
        self,
        tx,
        *,
        workspace_id: str,
        qf_schema_name: str,
    ) -> Dict[str, int]:
        rows = tx.execute_query_mappings(
            """
            SELECT id, full_name
            FROM workspace_table
            WHERE workspace_id=:ws
              AND schema_name=:schema
              AND exists_in_dbx=1
            """,
            {"ws": workspace_id, "schema": qf_schema_name},
        )
        return {str(row["full_name"]): int(row["id"]) for row in rows}

    def upsert_columns(
        self,
        tx,
        *,
        now: datetime,
        staged_columns: List[ColumnStage],
        table_id_by_full_name: Dict[str, int],
    ) -> None:
        payload: List[Dict[str, Any]] = []
        for column in staged_columns:
            table_id = table_id_by_full_name.get(column.full_name)
            if not table_id:
                continue
            payload.append(
                {
                    "workspace_table_id": table_id,
                    "column_name": column.column_name,
                    "data_type": column.data_type,
                    "nullable": column.nullable,
                    "ordinal_position": column.qf_ordinal_position,
                    "last_seen_at": now,
                }
            )

        if not payload:
            return

        tx.execute_write(
            """
            INSERT INTO workspace_column
            (workspace_table_id, column_name, data_type, nullable, ordinal_position,
             exists_in_dbx, last_seen_at, created_at)
            VALUES
            (:workspace_table_id, :column_name, :data_type, :nullable, :ordinal_position,
             1, :last_seen_at, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
             data_type=VALUES(data_type),
             nullable=VALUES(nullable),
             ordinal_position=VALUES(ordinal_position),
             exists_in_dbx=1,
             last_seen_at=VALUES(last_seen_at),
             updated_at=CURRENT_TIMESTAMP
            """,
            payload,
        )
