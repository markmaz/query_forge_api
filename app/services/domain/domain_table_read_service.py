from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.shared.jsonify import serialize_result_rows
from app.services.workspace_inventory.workspace_snapshot_ensure_service import WorkspaceSnapshotEnsureService


class DomainTableReadService:
    """Read domain/workspace table mappings and workspace table inventory."""

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_domain_tables(self, *, workspace_id: str, domain_id: int) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              wt.id               AS workspace_table_id,
              d.model_table_id    AS model_table_id,
              mt.name             AS model_table_name,
              dwt.relation_kind   AS relation_kind,
              dwt.is_primary      AS is_primary,
              dwt.sort_order      AS sort_order,
              dwt.table_alias     AS table_alias,
              dwt.role            AS role,
              dwt.filter_mode     AS filter_mode,
              dwt.cardinality     AS cardinality,
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
            LEFT JOIN model_table mt ON mt.id = d.model_table_id
            WHERE d.workspace_id = :ws
              AND d.id = :did
            ORDER BY COALESCE(mt.name, ''), wt.full_name
            """,
            {"ws": workspace_id, "did": int(domain_id)},
        )
        return serialize_result_rows([dict(row) for row in rows])

    def get_domain(self, *, workspace_id: str, domain_name: str) -> Dict[str, Any]:
        ws = (workspace_id or "").strip()
        name = (domain_name or "").strip()

        if not ws:
            raise ForgeError("workspace_id is required", status_code=400)
        if not name:
            raise ForgeError("domain_name is required", status_code=400)

        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.id AS domain_id,
              d.column_name_policy
            FROM domain d
            WHERE d.workspace_id = :ws
              AND d.name = :name
              AND d.is_active = 1
            LIMIT 1
            """,
            {"ws": ws, "name": name},
        )
        if not rows:
            raise ForgeError("Domain not found", status_code=404)

        row = rows[0]
        return {
            "domain_id": int(row["domain_id"]),
            "column_name_policy": row.get("column_name_policy"),
        }

    def list_workspace_tables(
        self,
        *,
        workspace_id: str,
        q: Optional[str] = None,
        schema_name: Optional[str] = None,
        catalog_name: Optional[str] = None,
        only_exists_in_dbx: Optional[bool] = True,
        limit: int = 500,
        offset: int = 0,
        mapped: int = 0,
        ensure_snapshot: bool = True,
        min_fresh_age_minutes: int = 15,
    ) -> List[Dict[str, Any]]:
        schema = (schema_name or "").strip() or "asset"
        catalog = (catalog_name or "").strip() or None

        if ensure_snapshot:
            WorkspaceSnapshotEnsureService().ensure(
                workspace_id=workspace_id,
                schema_name=schema,
                min_fresh_age_minutes=int(min_fresh_age_minutes),
            )

        params: Dict[str, Any] = {
            "ws": workspace_id,
            "q": (q or "").strip() or None,
            "schema": schema,
            "catalog": catalog,
            "only_dbx": 1 if only_exists_in_dbx is True else 0,
            "mapped": None if mapped is None else (1 if mapped else 0),
            "limit": int(limit),
            "offset": int(offset),
        }

        rows = self._sql.execute_query_mappings(
            """
            SELECT
              wt.id               AS workspace_table_id,
              wt.model_table_id,
              mt.name             AS model_table_name,
              wt.catalog_name,
              wt.schema_name,
              wt.table_name,
              wt.full_name,
              wt.variant_code,
              wt.is_qe,
              wt.exists_in_dbx,
              wt.last_seen_at
            FROM workspace_table wt
            LEFT JOIN model_table mt ON mt.id = wt.model_table_id
            WHERE wt.workspace_id = :ws
              AND (:schema IS NULL OR wt.schema_name = :schema)
              AND (:catalog IS NULL OR wt.catalog_name = :catalog)
              AND (
                :q IS NULL OR
                wt.full_name LIKE CONCAT('%', :q, '%') OR
                wt.table_name LIKE CONCAT('%', :q, '%') OR
                mt.name LIKE CONCAT('%', :q, '%')
              )
              AND (:only_dbx = 0 OR wt.exists_in_dbx = 1)
              AND (
                :mapped IS NULL OR
                (:mapped = 1 AND wt.model_table_id IS NOT NULL) OR
                (:mapped = 0 AND wt.model_table_id IS NULL)
              )
            ORDER BY COALESCE(mt.name, wt.table_name), wt.full_name
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        return serialize_result_rows([dict(row) for row in rows])
