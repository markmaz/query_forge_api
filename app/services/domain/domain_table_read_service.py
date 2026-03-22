from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import current_app, has_app_context
from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.analytics.executor_factory import ExecutorFactory
from app.services.analytics.metadata_provider_factory import MetadataProviderFactory
from app.services.shared.jsonify import serialize_result_rows
from app.services.tenancy.datasource_resolver_service import WorkspaceDatasourceResolverService
from app.services.tenancy.secret_resolver import SecretResolver

logger = logging.getLogger(__name__)


class DomainTableReadService:
    """Read domain/workspace table mappings and workspace table inventory."""

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, metadata_mode: Optional[str] = None) -> None:
        del metadata_mode
        self._sql = sql or ForgeMetaSQL()

    def list_domain_tables(self, *, workspace_id: str, domain_id: int) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              wt.id               AS workspace_table_id,
              NULL                AS model_table_id,
              COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name) AS model_table_name,
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
            WHERE d.workspace_id = :ws
              AND d.id = :did
            ORDER BY COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name, ''), wt.full_name
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
        schema = (schema_name or "").strip() or None
        catalog = (catalog_name or "").strip() or None

        if ensure_snapshot and schema:
            try:
                self._sync_workspace_inventory_from_registry(
                    workspace_id=workspace_id,
                    schema_name=schema,
                    catalog_name=catalog,
                )
            except Exception:
                logger.exception(
                    "Workspace inventory sync skipped ws=%s schema=%s catalog=%s",
                    workspace_id,
                    schema,
                    catalog,
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
              NULL                AS model_table_id,
              COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name) AS model_table_name,
              wt.catalog_name,
              wt.schema_name,
              wt.table_name,
              wt.full_name,
              wt.variant_code,
              wt.is_qe,
              wt.exists_in_dbx,
              wt.last_seen_at
            FROM workspace_table wt
            WHERE wt.workspace_id = :ws
              AND (:schema IS NULL OR wt.schema_name = :schema)
              AND (:catalog IS NULL OR wt.catalog_name = :catalog)
              AND (
                :q IS NULL OR
                wt.full_name LIKE CONCAT('%', :q, '%') OR
                wt.table_name LIKE CONCAT('%', :q, '%') OR
                wt.source_table_name LIKE CONCAT('%', :q, '%')
              )
              AND (:only_dbx = 0 OR wt.exists_in_dbx = 1)
              AND (
                :mapped IS NULL OR
                (:mapped = 1 AND EXISTS (
                  SELECT 1
                  FROM domain_workspace_table dwt
                  JOIN domain d ON d.id = dwt.domain_id
                  WHERE dwt.workspace_table_id = wt.id
                    AND d.workspace_id = :ws
                    AND d.is_active = 1
                )) OR
                (:mapped = 0 AND NOT EXISTS (
                  SELECT 1
                  FROM domain_workspace_table dwt
                  JOIN domain d ON d.id = dwt.domain_id
                  WHERE dwt.workspace_table_id = wt.id
                    AND d.workspace_id = :ws
                    AND d.is_active = 1
                ))
              )
            ORDER BY COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name), wt.full_name
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        return serialize_result_rows([dict(row) for row in rows])

    def _sync_workspace_inventory_from_registry(
        self,
        *,
        workspace_id: str,
        schema_name: str,
        catalog_name: Optional[str],
    ) -> None:
        if not has_app_context():
            return

        provider = self._resolve_metadata_provider(
            workspace_id=workspace_id,
            schema_name=schema_name,
            catalog_name=catalog_name,
        )

        tables = provider.list_tables(catalog_name, schema_name)
        table_names = sorted(
            {
                str(row.get("table_name") or "").strip()
                for row in tables
                if str(row.get("table_name") or "").strip()
            }
        )
        columns = provider.list_columns(catalog_name, schema_name, table_names or None)

        now = datetime.now(timezone.utc)
        catalog_value = (catalog_name or "").strip()

        with self._sql.transaction() as tx:
            tx.execute_write(
                "INSERT INTO workspace (id) VALUES (:id) ON DUPLICATE KEY UPDATE id=id",
                {"id": workspace_id},
            )

            tx.execute_write(
                """
                UPDATE workspace_table
                SET exists_in_dbx = 0, updated_at = CURRENT_TIMESTAMP
                WHERE workspace_id = :ws
                  AND schema_name = :schema
                """,
                {"ws": workspace_id, "schema": schema_name},
            )
            tx.execute_write(
                """
                UPDATE workspace_column wc
                JOIN workspace_table wt ON wt.id = wc.workspace_table_id
                SET wc.exists_in_dbx = 0, wc.updated_at = CURRENT_TIMESTAMP
                WHERE wt.workspace_id = :ws
                  AND wt.schema_name = :schema
                """,
                {"ws": workspace_id, "schema": schema_name},
            )

            table_payload: List[Dict[str, Any]] = []
            for table_name in table_names:
                full_name = (
                    f"{catalog_value}.{schema_name}.{table_name}"
                    if catalog_value
                    else f"{schema_name}.{table_name}"
                )
                table_payload.append(
                    {
                        "workspace_id": workspace_id,
                        "catalog_name": catalog_value,
                        "schema_name": schema_name,
                        "table_name": table_name,
                        "full_name": full_name,
                        "variant_code": None,
                        "is_qe": 0,
                        "last_seen_at": now,
                    }
                )

            if table_payload:
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
                    table_payload,
                )

            current_rows = tx.execute_query_mappings(
                """
                SELECT id, table_name
                FROM workspace_table
                WHERE workspace_id = :ws
                  AND schema_name = :schema
                  AND exists_in_dbx = 1
                """,
                {"ws": workspace_id, "schema": schema_name},
            )
            workspace_table_id_by_name = {
                str(row.get("table_name") or ""): int(row["id"])
                for row in current_rows
                if row.get("table_name") is not None
            }

            column_payload: List[Dict[str, Any]] = []
            for column in columns:
                table_name = str(column.get("table_name") or "").strip()
                workspace_table_id = workspace_table_id_by_name.get(table_name)
                if workspace_table_id is None:
                    continue
                column_name = str(column.get("column_name") or "").strip()
                if not column_name:
                    continue
                column_payload.append(
                    {
                        "workspace_table_id": workspace_table_id,
                        "column_name": column_name,
                        "data_type": str(column.get("data_type") or ""),
                        "nullable": 1 if bool(column.get("is_nullable", True)) else 0,
                        "ordinal_position": int(column.get("ordinal_position") or 0),
                        "last_seen_at": now,
                    }
                )

            if column_payload:
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
                    column_payload,
                )

    def _resolve_metadata_provider(
        self,
        *,
        workspace_id: str,
        schema_name: str,
        catalog_name: Optional[str],
    ):
        resolved = WorkspaceDatasourceResolverService(sql=self._sql).resolve_for_workspace(
            workspace_id=workspace_id,
            require_active=True,
        )
        if resolved is not None:
            ds_type = str(resolved.datasource_type or "").strip().lower()
            if ds_type not in {"databricks", "snowflake", "mysql"}:
                raise ForgeError(
                    f"Workspace '{workspace_id}' datasource type '{ds_type}' does not support metadata sync",
                    status_code=400,
                )

            config = dict(resolved.config_json or {})
            secrets = SecretResolver()
            if ds_type == "databricks":
                auth_method = str(config.get("auth_method") or "").strip().lower()
                if auth_method != "oauth_client_credentials":
                    config = secrets.inject_if_missing(config, secret_ref=resolved.secret_ref, key="token")
                config.setdefault("host", config.get("workspace_url") or config.get("server"))
                config.setdefault("http_path", config.get("http_path"))
                config.setdefault("workspace_id", workspace_id)
                config.setdefault("_workspace_id", workspace_id)
            elif ds_type in {"snowflake", "mysql"}:
                config = secrets.inject_if_missing(config, secret_ref=resolved.secret_ref, key="password")

            if catalog_name and not config.get("catalog"):
                config["catalog"] = catalog_name
            if schema_name and not config.get("schema"):
                config["schema"] = schema_name
            config.setdefault("type", ds_type)

            executor = ExecutorFactory.create(ds_type, config)
            return MetadataProviderFactory.create(ds_type, executor)

        registry = current_app.extensions.get("analytics_registry")
        if registry is None:
            raise RuntimeError("Analytics datasource registry is not available")

        executor = registry.get("primary")
        return MetadataProviderFactory.create(executor.get_dialect(), executor)
