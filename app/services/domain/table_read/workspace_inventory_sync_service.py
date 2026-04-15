from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import current_app, has_app_context

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)


def sync_workspace_inventory_from_registry(
    *,
    sql: ForgeQueryPort,
    workspace_id: str,
    schema_name: str,
    catalog_name: Optional[str],
    metadata_provider: Any,
) -> None:
    if not has_app_context():
        return

    tables = metadata_provider.list_tables(catalog_name, schema_name)
    table_names = sorted(
        {
            str(row.get("table_name") or "").strip()
            for row in tables
            if str(row.get("table_name") or "").strip()
        }
    )
    columns = metadata_provider.list_columns(catalog_name, schema_name, table_names or None)

    now = datetime.now(timezone.utc)
    catalog_value = (catalog_name or "").strip()

    with sql.transaction() as tx:
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
            full_name = f"{catalog_value}.{schema_name}.{table_name}" if catalog_value else f"{schema_name}.{table_name}"
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


def resolve_metadata_provider(
    *,
    sql: ForgeQueryPort,
    workspace_id: str,
    schema_name: str,
    catalog_name: Optional[str],
    datasource_resolver_cls: Any,
    secret_resolver_cls: Any,
    executor_factory: Any,
    metadata_provider_factory: Any,
):
    resolved = datasource_resolver_cls(sql=sql).resolve_for_workspace(
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
        secrets = secret_resolver_cls()
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

        executor = executor_factory.create(ds_type, config)
        return metadata_provider_factory.create(ds_type, executor)

    registry = current_app.extensions.get("analytics_registry")
    if registry is None:
        raise RuntimeError("Analytics datasource registry is not available")

    executor = registry.get("primary")
    return metadata_provider_factory.create(executor.get_dialect(), executor)
