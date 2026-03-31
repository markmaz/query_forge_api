from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeExecResult, ForgeQueryPort, ForgeQueryTx
from app.services.shared.jsonify import serialize_result_rows

from app.services.domain.join.domain_join_validator import DomainJoinPayload


class DomainJoinRepository:
    def __init__(self, *, sql: ForgeQueryPort) -> None:
        self._sql = sql

    def transaction(self):
        return self._sql.transaction()

    def list_domain_joins(self, *, workspace_id: str, domain_id: int) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
                dtj.id,
                dtj.domain_id,
                dtj.from_workspace_table_id,
                dtj.to_workspace_table_id,
                dtj.join_type,
                dtj.join_spec_json,
                dtj.sort_order,
                dtj.is_active,
                dtj.created_at,
                dtj.updated_at
            FROM domain_table_join dtj
            JOIN domain d ON d.id = dtj.domain_id
            WHERE d.workspace_id = :ws
              AND dtj.domain_id = :did
              AND dtj.is_active = 1
            ORDER BY dtj.sort_order, dtj.created_at
            """,
            {"ws": workspace_id, "did": int(domain_id)},
        )
        return serialize_result_rows([dict(row) for row in rows])

    def ensure_domain(self, tx: ForgeQueryTx, *, workspace_id: str, domain_id: int) -> None:
        rows = tx.execute_query_mappings(
            "SELECT id FROM domain WHERE id = :did AND workspace_id = :ws AND is_active = 1 LIMIT 1",
            {"did": int(domain_id), "ws": workspace_id},
        )
        if not rows:
            raise ForgeError("Domain not found", status_code=404)

    def ensure_tables_in_domain(self, tx: ForgeQueryTx, *, domain_id: int, qf_from_id: int, qf_to_id: int) -> None:
        rows = tx.execute_query_mappings(
            """
            SELECT workspace_table_id
            FROM domain_workspace_table
            WHERE domain_id = :did
              AND workspace_table_id IN (:qf_from_id, :qf_to_id)
            """,
            {"did": int(domain_id), "qf_from_id": int(qf_from_id), "qf_to_id": int(qf_to_id)},
        )
        ids = {int(row["workspace_table_id"]) for row in rows}
        if int(qf_from_id) not in ids or int(qf_to_id) not in ids:
            raise ForgeError("Both tables must be assigned to the domain", status_code=400)

    def ensure_join_exists(self, tx: ForgeQueryTx, *, domain_id: int, join_id: str) -> None:
        rows = tx.execute_query_mappings(
            "SELECT id FROM domain_table_join WHERE domain_id = :did AND id = :join_id LIMIT 1",
            {"did": int(domain_id), "join_id": join_id},
        )
        if not rows:
            raise ForgeError("Join not found", status_code=404)

    def find_existing_join(self, tx: ForgeQueryTx, *, payload: DomainJoinPayload) -> Optional[Dict[str, Any]]:
        rows = tx.execute_query_mappings(
            """
            SELECT id, is_active
            FROM domain_table_join
            WHERE domain_id = :did
              AND from_workspace_table_id = :qf_from_id
              AND to_workspace_table_id = :qf_to_id
              AND sort_order = :sort_order
            LIMIT 1
            """,
            {
                "did": payload.domain_id,
                "qf_from_id": payload.from_workspace_table_id,
                "qf_to_id": payload.to_workspace_table_id,
                "sort_order": payload.sort_order,
            },
        )
        return rows[0] if rows else None

    def reactivate_existing_join(self, tx: ForgeQueryTx, *, payload: DomainJoinPayload, join_id: Any) -> None:
        tx.execute_write(
            """
            UPDATE domain_table_join
            SET
                join_type = :join_type,
                join_spec_json = :join_spec,
                sort_order = :sort_order,
                is_active = 1
            WHERE id = :join_id
            """,
            {
                "join_type": payload.join_type,
                "join_spec": json.dumps(payload.join_spec),
                "sort_order": payload.sort_order,
                "join_id": join_id,
            },
        )

    def insert_join(self, tx: ForgeQueryTx, *, payload: DomainJoinPayload) -> ForgeExecResult:
        return tx.execute_insert(
            """
            INSERT INTO domain_table_join
              (domain_id, from_workspace_table_id, to_workspace_table_id, join_type, join_spec_json, sort_order, is_active)
            VALUES
              (:did, :qf_from_id, :qf_to_id, :join_type, :join_spec, :sort_order, 1)
            """,
            {
                "did": payload.domain_id,
                "qf_from_id": payload.from_workspace_table_id,
                "qf_to_id": payload.to_workspace_table_id,
                "join_type": payload.join_type,
                "join_spec": json.dumps(payload.join_spec),
                "sort_order": payload.sort_order,
            },
        )

    def update_join(self, tx: ForgeQueryTx, *, payload: DomainJoinPayload, join_id: str) -> None:
        tx.execute_write(
            """
            UPDATE domain_table_join
            SET
                from_workspace_table_id = :qf_from_id,
                to_workspace_table_id = :qf_to_id,
                join_type = :join_type,
                join_spec_json = :join_spec,
                sort_order = :sort_order
            WHERE domain_id = :did
              AND id = :join_id
            """,
            {
                "qf_from_id": payload.from_workspace_table_id,
                "qf_to_id": payload.to_workspace_table_id,
                "join_type": payload.join_type,
                "join_spec": json.dumps(payload.join_spec),
                "sort_order": payload.sort_order,
                "did": payload.domain_id,
                "join_id": join_id,
            },
        )

    def deactivate_join(self, tx: ForgeQueryTx, *, domain_id: int, join_id: str) -> None:
        tx.execute_write(
            """
            UPDATE domain_table_join
            SET is_active = 0
            WHERE domain_id = :did
              AND id = :join_id
            """,
            {"did": int(domain_id), "join_id": join_id},
        )

    def ensure_primary_table_assigned(self, tx: ForgeQueryTx, *, domain_id: int, workspace_table_id: int) -> None:
        rows = tx.execute_query_mappings(
            """
            SELECT 1
            FROM domain_workspace_table
            WHERE domain_id = :did
              AND workspace_table_id = :wtid
            LIMIT 1
            """,
            {"did": int(domain_id), "wtid": int(workspace_table_id)},
        )
        if not rows:
            raise ForgeError("Table is not assigned to this domain", status_code=400)

    def set_primary_flags(self, tx: ForgeQueryTx, *, domain_id: int, workspace_table_id: int) -> None:
        tx.execute_write(
            "UPDATE domain_workspace_table SET is_primary = 0 WHERE domain_id = :did",
            {"did": int(domain_id)},
        )
        tx.execute_write(
            """
            UPDATE domain_workspace_table
            SET is_primary = 1
            WHERE domain_id = :did
              AND workspace_table_id = :wtid
            """,
            {"did": int(domain_id), "wtid": int(workspace_table_id)},
        )
        tx.execute_write(
            """
            UPDATE domain_table_join
            SET is_active = 0
            WHERE domain_id = :did
              AND to_workspace_table_id = :wtid
              AND is_active = 1
            """,
            {"did": int(domain_id), "wtid": int(workspace_table_id)},
        )

    def list_domain_tables(self, tx: ForgeQueryTx, *, workspace_id: str, domain_id: int) -> List[Dict[str, Any]]:
        rows = tx.execute_query_mappings(
            """
            SELECT
              wt.id               AS workspace_table_id,
              COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name) AS table_label,
              dwt.relation_kind   AS relation_kind,
              dwt.is_primary      AS is_primary,
              dwt.sort_order      AS sort_order,
              dwt.table_alias     AS table_alias,
              dwt.role            AS role,
              wt.catalog_name,
              wt.schema_name,
              wt.table_name,
              wt.full_name,
              wt.variant_code,
              wt.is_qe,
              wt.exists_in_dbx,
              wt.last_seen_at
            FROM domain_workspace_table dwt
            JOIN domain d ON d.id = dwt.domain_id
            JOIN workspace_table wt ON wt.id = dwt.workspace_table_id
            WHERE d.workspace_id = :ws
              AND d.id = :did
            ORDER BY COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name), wt.full_name
            """,
            {"ws": workspace_id, "did": int(domain_id)},
        )
        payload = []
        for row in rows:
            shaped = dict(row)
            shaped["model_table_id"] = shaped.get("workspace_table_id")
            shaped["model_table_name"] = shaped.get("table_label")
            payload.append(shaped)
        return serialize_result_rows(payload)
