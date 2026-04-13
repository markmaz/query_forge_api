from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.analytics.executor_factory import ExecutorFactory
from app.services.analytics.metadata_provider_factory import MetadataProviderFactory
from app.services.domain.table_read.domain_table_row_serializer import serialize_workspace_table_rows
from app.services.domain.table_read.workspace_inventory_sync_service import (
    resolve_metadata_provider,
    sync_workspace_inventory_from_registry,
)
from app.services.metadata.mode import effective_metadata_mode, normalize_metadata_mode
from app.services.tenancy.datasource_resolver_service import WorkspaceDatasourceResolverService
from app.services.tenancy.secret_resolver import SecretResolver

logger = logging.getLogger(__name__)
INVENTORY_SYNC_FALLBACK_ERRORS = (ForgeError, OSError, RuntimeError, TypeError, ValueError)


class DomainTableReadService:
    """Read domain/workspace table mappings and workspace table inventory."""

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, metadata_mode: Optional[str] = None) -> None:
        self._configured_metadata_mode = normalize_metadata_mode(metadata_mode)
        self._effective_metadata_mode = effective_metadata_mode(metadata_mode)
        self._sql = sql or ForgeMetaSQL()

    def list_domain_tables(self, *, workspace_id: str, domain_id: int) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              wt.id               AS workspace_table_id,
              COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name) AS table_label,
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
        return serialize_workspace_table_rows(rows)

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

        if ensure_snapshot and schema and self._should_refresh_snapshot(
            workspace_id=workspace_id,
            schema_name=schema,
            catalog_name=catalog,
            min_fresh_age_minutes=min_fresh_age_minutes,
        ):
            try:
                self._sync_workspace_inventory_from_registry(
                    workspace_id=workspace_id,
                    schema_name=schema,
                    catalog_name=catalog,
                )
            except INVENTORY_SYNC_FALLBACK_ERRORS:
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
              COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name) AS table_label,
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
        return serialize_workspace_table_rows(rows)

    def _should_refresh_snapshot(
        self,
        *,
        workspace_id: str,
        schema_name: str,
        catalog_name: Optional[str],
        min_fresh_age_minutes: int,
    ) -> bool:
        try:
            freshness_minutes = int(min_fresh_age_minutes)
        except (TypeError, ValueError):
            freshness_minutes = 15
        if freshness_minutes <= 0:
            return True

        rows = self._sql.execute_query_mappings(
            """
            SELECT MAX(last_seen_at) AS last_seen_at
            FROM workspace_table
            WHERE workspace_id = :ws
              AND schema_name = :schema
              AND (:catalog IS NULL OR catalog_name = :catalog)
            """,
            {
                "ws": workspace_id,
                "schema": schema_name,
                "catalog": catalog_name,
            },
        )
        latest_raw = ((rows[0] if rows else {}) or {}).get("last_seen_at")
        latest_seen = _coerce_utc_datetime(latest_raw)
        if latest_seen is None:
            return True
        age_limit = datetime.now(timezone.utc) - timedelta(minutes=freshness_minutes)
        return latest_seen < age_limit

    def _sync_workspace_inventory_from_registry(
        self,
        *,
        workspace_id: str,
        schema_name: str,
        catalog_name: Optional[str],
    ) -> None:
        provider = self._resolve_metadata_provider(
            workspace_id=workspace_id,
            schema_name=schema_name,
            catalog_name=catalog_name,
        )
        sync_workspace_inventory_from_registry(
            sql=self._sql,
            workspace_id=workspace_id,
            schema_name=schema_name,
            catalog_name=catalog_name,
            metadata_provider=provider,
        )

    def _resolve_metadata_provider(
        self,
        *,
        workspace_id: str,
        schema_name: str,
        catalog_name: Optional[str],
    ):
        return resolve_metadata_provider(
            sql=self._sql,
            workspace_id=workspace_id,
            schema_name=schema_name,
            catalog_name=catalog_name,
            datasource_resolver_cls=WorkspaceDatasourceResolverService,
            secret_resolver_cls=SecretResolver,
            executor_factory=ExecutorFactory,
            metadata_provider_factory=MetadataProviderFactory,
        )


def _coerce_utc_datetime(value: object) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
