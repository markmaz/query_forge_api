from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime, time as dt_time, timezone
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.tenancy.tenancy_admin import (
    DatasourceCreateRequest,
    DatasourceUpdateRequest,
    OrganizationCreateRequest,
    OrganizationMembershipCreateRequest,
    OrganizationMembershipUpdateRequest,
    OrganizationUpdateRequest,
    WorkspaceCreateRequest,
    WorkspaceBindingUpdateRequest,
    WorkspaceMembershipCreateRequest,
    WorkspaceMembershipUpdateRequest,
    normalize_slug,
)
from app.ports.sql_executor import ForgeQueryPort
from app.services.analytics.executor_factory import ExecutorFactory
from app.services.analytics.metadata_provider_factory import MetadataProviderFactory
from app.services.tenancy.datasource_config_crypto import (
    decrypt_datasource_config,
    encrypt_datasource_config,
    mask_datasource_config,
)
from app.services.tenancy.secret_resolver import SecretResolver

_SUPPORTED_DATASOURCE_TYPES = {"databricks", "snowflake", "mysql", "postgres", "bigquery"}
TENANCY_ADMIN_FALLBACK_ERRORS = (ForgeError, OSError, RuntimeError, ValueError)
JSON_PARSE_ERRORS = (json.JSONDecodeError,)

_ORGANIZATION_MEMBERSHIP_SELECT = """
            SELECT
              om.id,
              om.organization_id,
              om.user_id,
              om.role,
              COALESCE(om.is_active, 1) AS is_active,
              om.created_at,
              om.updated_at,
              u.username,
              u.email,
              u.first_name,
              u.last_name,
              CONCAT_WS(' ', NULLIF(u.first_name, ''), NULLIF(u.last_name, '')) AS display_name
            FROM organization_membership om
            LEFT JOIN users u ON u.user_id = om.user_id
"""

_WORKSPACE_MEMBERSHIP_SELECT = """
            SELECT
              wm.id,
              wm.workspace_id,
              wm.user_id,
              wm.role,
              COALESCE(wm.is_active, 1) AS is_active,
              COALESCE(wm.is_default, 0) AS is_default,
              wm.created_at,
              wm.updated_at,
              u.username,
              u.email,
              u.first_name,
              u.last_name,
              CONCAT_WS(' ', NULLIF(u.first_name, ''), NULLIF(u.last_name, '')) AS display_name
            FROM workspace_membership wm
            LEFT JOIN users u ON u.user_id = wm.user_id
"""


class TenancyAdminService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._secrets = SecretResolver()

    # ------------------------------------------------------------------
    # Organization
    # ------------------------------------------------------------------
    def list_organizations(
        self,
        *,
        include_inactive: bool = False,
        q: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        page_limit = max(1, min(int(limit or 100), 500))
        page_offset = max(0, int(offset or 0))
        q_text = str(q or "").strip() or None
        params = {
            "include_inactive": 1 if include_inactive else 0,
            "q": q_text,
            "limit": page_limit,
            "offset": page_offset,
        }
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, name, slug, description, COALESCE(is_active, 1) AS is_active, created_at, updated_at
            FROM organization
            WHERE (:include_inactive = 1 OR COALESCE(is_active, 1) = 1)
              AND (:q IS NULL OR name LIKE CONCAT('%', :q, '%') OR slug LIKE CONCAT('%', :q, '%'))
            ORDER BY name, id
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._sql.execute_query_mappings(
            """
            SELECT COUNT(*) AS total
            FROM organization
            WHERE (:include_inactive = 1 OR COALESCE(is_active, 1) = 1)
              AND (:q IS NULL OR name LIKE CONCAT('%', :q, '%') OR slug LIKE CONCAT('%', :q, '%'))
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        return {
            "rows": [_normalize_bool_flags(dict(r), ("is_active", "is_default")) for r in rows],
            "count": len(rows),
            "total": int((total_rows[0] or {}).get("total") or 0) if total_rows else 0,
            "limit": page_limit,
            "offset": page_offset,
        }

    def get_organization(self, organization_id: str) -> Dict[str, Any]:
        oid = _required_text(organization_id, "organization_id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, name, slug, description, COALESCE(is_active, 1) AS is_active, created_at, updated_at
            FROM organization
            WHERE id = :id
            LIMIT 1
            """,
            {"id": oid},
        )
        if not rows:
            raise ForgeError("Organization not found", status_code=404, details={"organization_id": oid})
        return _normalize_bool_flags(dict(rows[0]), ("is_active", "is_default"))

    def create_organization(self, req: OrganizationCreateRequest) -> Dict[str, Any]:
        org_id = _optional_text(req.id) or f"org_{uuid.uuid4().hex[:24]}"
        slug = _optional_text(req.slug) or normalize_slug(req.name)
        if not slug:
            raise ForgeError("organization slug is required", status_code=400)
        self._assert_organization_unique(org_id=org_id, slug=slug, exclude_id=None)
        self._sql.execute_write(
            """
            INSERT INTO organization (id, name, slug, description, is_active)
            VALUES (:id, :name, :slug, :description, :is_active)
            """,
            {
                "id": org_id,
                "name": req.name.strip(),
                "slug": slug,
                "description": _optional_text(req.description),
                "is_active": 1 if req.is_active else 0,
            },
        )
        return self.get_organization(org_id)

    def update_organization(self, organization_id: str, req: OrganizationUpdateRequest) -> Dict[str, Any]:
        oid = _required_text(organization_id, "organization_id")
        existing = self.get_organization(oid)
        name = _optional_text(req.name) or str(existing.get("name") or "")
        slug = _optional_text(req.slug) or str(existing.get("slug") or "")
        if not name:
            raise ForgeError("organization name is required", status_code=400)
        if not slug:
            raise ForgeError("organization slug is required", status_code=400)
        self._assert_organization_unique(org_id=oid, slug=slug, exclude_id=oid)
        self._sql.execute_write(
            """
            UPDATE organization
            SET name = :name,
                slug = :slug,
                description = :description,
                is_active = :is_active
            WHERE id = :id
            """,
            {
                "id": oid,
                "name": name,
                "slug": slug,
                "description": req.description if req.description is not None else existing.get("description"),
                "is_active": (1 if req.is_active else 0) if req.is_active is not None else (1 if existing.get("is_active") else 0),
            },
        )
        return self.get_organization(oid)

    def delete_organization(self, organization_id: str, *, hard: bool = False) -> Dict[str, Any]:
        oid = _required_text(organization_id, "organization_id")
        self.get_organization(oid)
        if hard:
            self._sql.execute_write("DELETE FROM organization WHERE id = :id", {"id": oid})
            return {"organization_id": oid, "deleted": True, "mode": "hard"}
        self._sql.execute_write(
            "UPDATE organization SET is_active = 0 WHERE id = :id",
            {"id": oid},
        )
        return {"organization_id": oid, "deleted": True, "mode": "soft"}

    # ------------------------------------------------------------------
    # Organization membership
    # ------------------------------------------------------------------
    def list_organization_memberships(
        self,
        *,
        organization_id: str,
        include_inactive: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        oid = _required_text(organization_id, "organization_id")
        self.get_organization(oid)
        page_limit = max(1, min(int(limit or 200), 500))
        page_offset = max(0, int(offset or 0))
        params = {
            "organization_id": oid,
            "include_inactive": 1 if include_inactive else 0,
            "limit": page_limit,
            "offset": page_offset,
        }
        rows = self._sql.execute_query_mappings(
            _ORGANIZATION_MEMBERSHIP_SELECT
            + """
            WHERE om.organization_id = :organization_id
              AND (:include_inactive = 1 OR COALESCE(om.is_active, 1) = 1)
            ORDER BY om.id DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._sql.execute_query_mappings(
            """
            SELECT COUNT(*) AS total
            FROM organization_membership
            WHERE organization_id = :organization_id
              AND (:include_inactive = 1 OR COALESCE(is_active, 1) = 1)
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        return {
            "rows": [_normalize_bool_flags(dict(r), ("is_active",)) for r in rows],
            "count": len(rows),
            "total": int((total_rows[0] or {}).get("total") or 0) if total_rows else 0,
            "limit": page_limit,
            "offset": page_offset,
        }

    def upsert_organization_membership(
        self,
        *,
        organization_id: str,
        req: OrganizationMembershipCreateRequest,
    ) -> Dict[str, Any]:
        oid = _required_text(organization_id, "organization_id")
        self.get_organization(oid)
        uid = _required_text(req.user_id, "user_id")
        role = _required_text(req.role, "role")
        self._sql.execute_write(
            """
            INSERT INTO organization_membership (organization_id, user_id, role, is_active)
            VALUES (:organization_id, :user_id, :role, :is_active)
            ON DUPLICATE KEY UPDATE
              role = VALUES(role),
              is_active = VALUES(is_active),
              updated_at = CURRENT_TIMESTAMP
            """,
            {
                "organization_id": oid,
                "user_id": uid,
                "role": role,
                "is_active": 1 if req.is_active else 0,
            },
        )
        rows = self._sql.execute_query_mappings(
            _ORGANIZATION_MEMBERSHIP_SELECT
            + """
            WHERE om.organization_id = :organization_id AND om.user_id = :user_id
            LIMIT 1
            """,
            {"organization_id": oid, "user_id": uid},
        )
        if not rows:
            raise ForgeError("Failed to load organization membership", status_code=500)
        return _normalize_bool_flags(dict(rows[0]), ("is_active", "is_default"))

    def update_organization_membership(
        self,
        *,
        organization_id: str,
        membership_id: int,
        req: OrganizationMembershipUpdateRequest,
    ) -> Dict[str, Any]:
        row = self._get_org_membership(organization_id=organization_id, membership_id=membership_id)
        role = _optional_text(req.role) or str(row.get("role") or "member")
        is_active = (1 if req.is_active else 0) if req.is_active is not None else (1 if row.get("is_active") else 0)
        self._sql.execute_write(
            """
            UPDATE organization_membership
            SET role = :role, is_active = :is_active
            WHERE id = :id AND organization_id = :organization_id
            """,
            {"id": membership_id, "organization_id": organization_id, "role": role, "is_active": is_active},
        )
        return self._get_org_membership(organization_id=organization_id, membership_id=membership_id)

    def delete_organization_membership(self, *, organization_id: str, membership_id: int) -> Dict[str, Any]:
        row = self._get_org_membership(organization_id=organization_id, membership_id=membership_id)
        self._sql.execute_write(
            "DELETE FROM organization_membership WHERE id = :id AND organization_id = :organization_id",
            {"id": membership_id, "organization_id": organization_id},
        )
        return {"id": int(row["id"]), "organization_id": organization_id, "deleted": True}

    # ------------------------------------------------------------------
    # Datasource
    # ------------------------------------------------------------------
    def list_datasources(
        self,
        *,
        organization_id: str,
        include_inactive: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        oid = _required_text(organization_id, "organization_id")
        self.get_organization(oid)
        page_limit = max(1, min(int(limit or 100), 500))
        page_offset = max(0, int(offset or 0))
        params = {
            "organization_id": oid,
            "include_inactive": 1 if include_inactive else 0,
            "limit": page_limit,
            "offset": page_offset,
        }
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id, organization_id, name, slug, type, description, COALESCE(is_active, 1) AS is_active,
              secret_ref, config_json, last_tested_at, last_test_status, last_test_message, created_at, updated_at
            FROM datasource
            WHERE organization_id = :organization_id
              AND (:include_inactive = 1 OR COALESCE(is_active, 1) = 1)
            ORDER BY name, id
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._sql.execute_query_mappings(
            """
            SELECT COUNT(*) AS total
            FROM datasource
            WHERE organization_id = :organization_id
              AND (:include_inactive = 1 OR COALESCE(is_active, 1) = 1)
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        out_rows = [_coerce_datasource_row(dict(r)) for r in rows]
        return {
            "rows": out_rows,
            "count": len(out_rows),
            "total": int((total_rows[0] or {}).get("total") or 0) if total_rows else 0,
            "limit": page_limit,
            "offset": page_offset,
        }

    def get_datasource(self, datasource_id: int) -> Dict[str, Any]:
        row = self._get_datasource_row(int(datasource_id))
        return _coerce_datasource_row(row, public=True)

    def create_datasource(self, *, organization_id: str, req: DatasourceCreateRequest) -> Dict[str, Any]:
        oid = _required_text(organization_id, "organization_id")
        self.get_organization(oid)
        name = _required_text(req.name, "name")
        slug = _optional_text(req.slug) or normalize_slug(name)
        if not slug:
            raise ForgeError("datasource slug is required", status_code=400)
        dtype = _normalize_datasource_type(req.type)
        self._assert_datasource_unique(organization_id=oid, name=name, slug=slug, exclude_id=None)
        insert_result = self._sql.execute_insert(
            """
            INSERT INTO datasource (
              organization_id, name, slug, type, description, is_active, secret_ref, config_json
            ) VALUES (
              :organization_id, :name, :slug, :type, :description, :is_active, :secret_ref, :config_json
            )
            """,
            {
                "organization_id": oid,
                "name": name,
                "slug": slug,
                "type": dtype,
                "description": _optional_text(req.description),
                "is_active": 1 if req.is_active else 0,
                "secret_ref": _optional_text(req.secret_ref),
                "config_json": _json_dumps(encrypt_datasource_config(dtype, req.config_json)),
            },
        )
        datasource_id = int(insert_result.lastrowid or 0)
        if datasource_id <= 0:
            raise ForgeError("Failed to create datasource", status_code=500)
        return self.get_datasource(datasource_id)

    def update_datasource(self, *, datasource_id: int, req: DatasourceUpdateRequest) -> Dict[str, Any]:
        did = int(datasource_id)
        existing = self._get_datasource_row(did)
        existing_config = _json_loads(existing.get("config_json"))
        if not isinstance(existing_config, dict):
            existing_config = {}
        name = _optional_text(req.name) or str(existing.get("name") or "")
        slug = _optional_text(req.slug) or str(existing.get("slug") or "")
        dtype = _normalize_datasource_type(req.type or str(existing.get("type") or ""))
        self._assert_datasource_unique(
            organization_id=str(existing.get("organization_id") or ""),
            name=name,
            slug=slug,
            exclude_id=did,
        )
        self._sql.execute_write(
            """
            UPDATE datasource
            SET name = :name,
                slug = :slug,
                type = :type,
                description = :description,
                is_active = :is_active,
                secret_ref = :secret_ref,
                config_json = :config_json
            WHERE id = :id
            """,
            {
                "id": did,
                "name": name,
                "slug": slug,
                "type": dtype,
                "description": req.description if req.description is not None else existing.get("description"),
                "is_active": (1 if req.is_active else 0) if req.is_active is not None else (1 if existing.get("is_active") else 0),
                "secret_ref": req.secret_ref if req.secret_ref is not None else existing.get("secret_ref"),
                "config_json": (
                    _json_dumps(
                        encrypt_datasource_config(
                            dtype,
                            req.config_json,
                            existing_config=existing_config,
                        )
                    )
                    if req.config_json is not None
                    else existing.get("config_json")
                ),
            },
        )
        return self.get_datasource(did)

    def delete_datasource(self, *, datasource_id: int, hard: bool = False) -> Dict[str, Any]:
        did = int(datasource_id)
        self.get_datasource(did)
        if hard:
            self._sql.execute_write("DELETE FROM datasource WHERE id = :id", {"id": did})
            return {"datasource_id": did, "deleted": True, "mode": "hard"}
        self._sql.execute_write(
            "UPDATE datasource SET is_active = 0 WHERE id = :id",
            {"id": did},
        )
        return {"datasource_id": did, "deleted": True, "mode": "soft"}

    def test_datasource(self, *, datasource_id: int) -> Dict[str, Any]:
        row = _coerce_datasource_row(self._get_datasource_row(datasource_id), public=False)
        ds_type = _normalize_datasource_type(row.get("type"))
        config_json = self._build_executor_config(row=row, datasource_type=ds_type)

        start = time.perf_counter()
        status = "ok"
        message = "connection ok"
        try:
            executor = ExecutorFactory.create(ds_type, config_json)
            executor.test_connection()
        except TENANCY_ADMIN_FALLBACK_ERRORS as exc:
            status = "error"
            message = str(exc)
        latency_ms = int((time.perf_counter() - start) * 1000)
        self._sql.execute_write(
            """
            UPDATE datasource
            SET last_tested_at = :last_tested_at,
                last_test_status = :last_test_status,
                last_test_message = :last_test_message
            WHERE id = :id
            """,
            {
                "id": int(row["id"]),
                "last_tested_at": datetime.now(timezone.utc).replace(tzinfo=None),
                "last_test_status": status,
                "last_test_message": message[:1000],
            },
        )
        return {
            "datasource_id": int(row["id"]),
            "type": ds_type,
            "status": status,
            "latency_ms": latency_ms,
            "message": message,
        }

    def list_datasource_namespaces(
        self,
        *,
        datasource_id: int,
        catalog: Optional[str] = None,
    ) -> Dict[str, Any]:
        row = _coerce_datasource_row(self._get_datasource_row(datasource_id), public=False)
        ds_type = _normalize_datasource_type(row.get("type"))
        config_json = self._build_executor_config(row=row, datasource_type=ds_type)

        configured_catalog = _optional_text(
            config_json.get("catalog")
            or config_json.get("database")
        )
        configured_schema = _optional_text(config_json.get("schema"))
        requested_catalog = _optional_text(catalog)

        catalogs = self._list_catalog_options(
            datasource_type=ds_type,
            config_json=config_json,
            configured_catalog=configured_catalog,
        )
        current_catalog = requested_catalog or configured_catalog or (catalogs[0] if catalogs else None)

        schemas = self._list_schema_options(
            datasource_type=ds_type,
            config_json=config_json,
            catalog=current_catalog,
            configured_schema=configured_schema,
        )
        current_schema = configured_schema if configured_schema in schemas else (schemas[0] if schemas else configured_schema)

        return {
            "datasource_id": int(row["id"]),
            "datasource_type": ds_type,
            "catalogs": catalogs,
            "schemas": schemas,
            "current_catalog": current_catalog,
            "current_schema": current_schema,
        }

    # ------------------------------------------------------------------
    # Workspace binding (workspace -> organization -> datasource)
    # ------------------------------------------------------------------
    def list_workspace_bindings(
        self,
        *,
        organization_id: Optional[str] = None,
        include_inactive: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        oid = _optional_text(organization_id)
        if oid:
            self.get_organization(oid)
        page_limit = max(1, min(int(limit or 200), 500))
        page_offset = max(0, int(offset or 0))
        params = {
            "organization_id": oid,
            "include_inactive": 1 if include_inactive else 0,
            "limit": page_limit,
            "offset": page_offset,
        }
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              w.id AS workspace_id,
              w.name AS workspace_name,
              w.description AS workspace_description,
              COALESCE(w.is_active, 1) AS workspace_is_active,
              w.default_catalog,
              w.default_schema,
              w.organization_id,
              o.name AS organization_name,
              COALESCE(o.is_active, 1) AS organization_is_active,
              w.datasource_id,
              d.name AS datasource_name,
              d.slug AS datasource_slug,
              d.type AS datasource_type,
              COALESCE(d.is_active, 1) AS datasource_is_active,
              w.created_at,
              w.updated_at
            FROM workspace w
            LEFT JOIN organization o ON o.id = w.organization_id
            LEFT JOIN datasource d ON d.id = w.datasource_id
            WHERE (:organization_id IS NULL OR w.organization_id = :organization_id)
              AND (:include_inactive = 1 OR COALESCE(w.is_active, 1) = 1)
            ORDER BY w.id
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._sql.execute_query_mappings(
            """
            SELECT COUNT(*) AS total
            FROM workspace w
            WHERE (:organization_id IS NULL OR w.organization_id = :organization_id)
              AND (:include_inactive = 1 OR COALESCE(w.is_active, 1) = 1)
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        out_rows = [_coerce_workspace_binding_row(dict(r)) for r in rows]
        return {
            "rows": out_rows,
            "count": len(out_rows),
            "total": int((total_rows[0] or {}).get("total") or 0) if total_rows else 0,
            "limit": page_limit,
            "offset": page_offset,
        }

    def _build_executor_config(self, *, row: Dict[str, Any], datasource_type: str) -> Dict[str, Any]:
        config_json = dict(row.get("config_json") or {})
        secret_ref = _optional_text(row.get("secret_ref"))
        auth_method = str(config_json.get("auth_method") or "").strip().lower()

        if datasource_type == "databricks":
            if auth_method != "oauth_client_credentials":
                return self._secrets.inject_if_missing(config_json, secret_ref=secret_ref, key="token")
            return config_json
        if datasource_type in {"snowflake", "mysql", "postgres", "bigquery"}:
            return self._secrets.inject_if_missing(config_json, secret_ref=secret_ref, key="password")
        return config_json

    def _list_catalog_options(
        self,
        *,
        datasource_type: str,
        config_json: Dict[str, Any],
        configured_catalog: Optional[str],
    ) -> list[str]:
        fallback = _dedupe_namespace_values([configured_catalog])
        if datasource_type not in {"databricks", "snowflake", "mysql"}:
            return fallback

        executor = ExecutorFactory.create(datasource_type, config_json)
        try:
            if datasource_type == "databricks":
                rows = executor.execute("SHOW CATALOGS")
                values = [
                    row.get("catalog")
                    or row.get("catalog_name")
                    or row.get("name")
                    for row in rows
                ]
                return _dedupe_namespace_values([*values, configured_catalog])
            if datasource_type == "snowflake":
                rows = executor.execute("SHOW DATABASES")
                values = [row.get("name") or row.get("database_name") for row in rows]
                return _dedupe_namespace_values([*values, configured_catalog])
            rows = executor.execute("SHOW DATABASES")
            values = [row.get("Database") or row.get("database") or row.get("name") for row in rows]
            return _dedupe_namespace_values([*values, configured_catalog])
        except TENANCY_ADMIN_FALLBACK_ERRORS:
            return fallback

    def _list_schema_options(
        self,
        *,
        datasource_type: str,
        config_json: Dict[str, Any],
        catalog: Optional[str],
        configured_schema: Optional[str],
    ) -> list[str]:
        fallback = _dedupe_namespace_values([configured_schema])
        if datasource_type not in {"databricks", "snowflake", "mysql"}:
            return fallback

        executor = ExecutorFactory.create(datasource_type, config_json)
        try:
            provider = MetadataProviderFactory.create(datasource_type, executor)
            values = provider.list_schemas(catalog)
            return _dedupe_namespace_values([*values, configured_schema])
        except TENANCY_ADMIN_FALLBACK_ERRORS:
            return fallback

    def create_workspace(self, req: WorkspaceCreateRequest) -> Dict[str, Any]:
        organization_id = _required_text(req.organization_id, "organization_id")
        self.get_organization(organization_id)

        datasource_id = req.datasource_id
        datasource_row = None
        if datasource_id is not None:
            datasource_row = self.get_datasource(int(datasource_id))
            datasource_org = _optional_text(datasource_row.get("organization_id"))
            if datasource_org and datasource_org != organization_id:
                raise ForgeError(
                    "Workspace organization_id must match datasource organization_id",
                    status_code=400,
                    details={
                        "organization_id": organization_id,
                        "datasource_id": datasource_id,
                        "datasource_organization_id": datasource_org,
                    },
                )

        workspace_id = _optional_text(req.workspace_id) or f"ws_{uuid.uuid4().hex[:24]}"
        existing = self._sql.execute_query_mappings(
            "SELECT id FROM workspace WHERE id = :id LIMIT 1",
            {"id": workspace_id},
        )
        if existing:
            raise ForgeError(
                "Workspace already exists",
                status_code=409,
                details={"workspace_id": workspace_id},
            )

        self._sql.execute_write(
            "INSERT INTO workspace (id) VALUES (:id)",
            {"id": workspace_id},
        )
        self._sql.execute_write(
            """
            UPDATE workspace
            SET organization_id = :organization_id,
                datasource_id = :datasource_id,
                name = :name,
                description = :description,
                is_active = :is_active,
                default_catalog = :default_catalog,
                default_schema = :default_schema
            WHERE id = :workspace_id
            """,
            {
                "workspace_id": workspace_id,
                "organization_id": organization_id,
                "datasource_id": int(datasource_id) if datasource_id is not None else None,
                "name": _optional_text(req.name),
                "description": req.description,
                "is_active": 1 if req.is_active else 0,
                "default_catalog": _optional_text(req.default_catalog),
                "default_schema": _optional_text(req.default_schema),
            },
        )
        return self.get_workspace_binding(workspace_id)

    def delete_workspace(self, *, workspace_id: str, hard: bool = False) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        self.get_workspace_binding(ws)
        if hard:
            self._sql.execute_write("DELETE FROM workspace WHERE id = :id", {"id": ws})
            return {"workspace_id": ws, "deleted": True, "mode": "hard"}
        self._sql.execute_write(
            "UPDATE workspace SET is_active = 0 WHERE id = :id",
            {"id": ws},
        )
        return {"workspace_id": ws, "deleted": True, "mode": "soft"}

    def get_workspace_binding(self, workspace_id: str) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              w.id AS workspace_id,
              w.name AS workspace_name,
              w.description AS workspace_description,
              COALESCE(w.is_active, 1) AS workspace_is_active,
              w.default_catalog,
              w.default_schema,
              w.organization_id,
              o.name AS organization_name,
              COALESCE(o.is_active, 1) AS organization_is_active,
              w.datasource_id,
              d.name AS datasource_name,
              d.slug AS datasource_slug,
              d.type AS datasource_type,
              COALESCE(d.is_active, 1) AS datasource_is_active,
              w.created_at,
              w.updated_at
            FROM workspace w
            LEFT JOIN organization o ON o.id = w.organization_id
            LEFT JOIN datasource d ON d.id = w.datasource_id
            WHERE w.id = :workspace_id
            LIMIT 1
            """,
            {"workspace_id": ws},
        )
        if not rows:
            raise ForgeError("Workspace not found", status_code=404, details={"workspace_id": ws})
        return _coerce_workspace_binding_row(dict(rows[0]))

    def update_workspace_binding(self, *, workspace_id: str, req: WorkspaceBindingUpdateRequest) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        existing = self.get_workspace_binding(ws)

        organization_id = _optional_text(req.organization_id) or _optional_text(existing.get("organization_id"))
        datasource_id = req.datasource_id if req.datasource_id is not None else existing.get("datasource_id")
        datasource_row = None

        if organization_id:
            self.get_organization(organization_id)

        if datasource_id is not None:
            datasource_row = self.get_datasource(int(datasource_id))
            datasource_org = _optional_text(datasource_row.get("organization_id"))
            if organization_id and datasource_org and organization_id != datasource_org:
                raise ForgeError(
                    "Workspace organization_id must match datasource organization_id",
                    status_code=400,
                    details={
                        "workspace_id": ws,
                        "organization_id": organization_id,
                        "datasource_id": datasource_id,
                        "datasource_organization_id": datasource_org,
                    },
                )
            if not organization_id:
                organization_id = datasource_org

        name = req.name if req.name is not None else existing.get("workspace_name")
        description = req.description if req.description is not None else existing.get("workspace_description")
        is_active = (1 if req.is_active else 0) if req.is_active is not None else (1 if existing.get("workspace_is_active") else 0)
        default_catalog = req.default_catalog if req.default_catalog is not None else existing.get("default_catalog")
        default_schema = req.default_schema if req.default_schema is not None else existing.get("default_schema")

        self._sql.execute_write(
            """
            UPDATE workspace
            SET organization_id = :organization_id,
                datasource_id = :datasource_id,
                name = :name,
                description = :description,
                is_active = :is_active,
                default_catalog = :default_catalog,
                default_schema = :default_schema
            WHERE id = :workspace_id
            """,
            {
                "workspace_id": ws,
                "organization_id": organization_id,
                "datasource_id": int(datasource_id) if datasource_id is not None else None,
                "name": _optional_text(name),
                "description": description,
                "is_active": is_active,
                "default_catalog": _optional_text(default_catalog),
                "default_schema": _optional_text(default_schema),
            },
        )
        return self.get_workspace_binding(ws)

    # ------------------------------------------------------------------
    # Workspace membership
    # ------------------------------------------------------------------
    def list_workspace_memberships(
        self,
        *,
        workspace_id: str,
        include_inactive: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        self._assert_workspace_exists(ws)
        page_limit = max(1, min(int(limit or 200), 500))
        page_offset = max(0, int(offset or 0))
        params = {
            "workspace_id": ws,
            "include_inactive": 1 if include_inactive else 0,
            "limit": page_limit,
            "offset": page_offset,
        }
        rows = self._sql.execute_query_mappings(
            _WORKSPACE_MEMBERSHIP_SELECT
            + """
            WHERE wm.workspace_id = :workspace_id
              AND (:include_inactive = 1 OR COALESCE(wm.is_active, 1) = 1)
            ORDER BY wm.id DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total_rows = self._sql.execute_query_mappings(
            """
            SELECT COUNT(*) AS total
            FROM workspace_membership
            WHERE workspace_id = :workspace_id
              AND (:include_inactive = 1 OR COALESCE(is_active, 1) = 1)
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        return {
            "rows": [_normalize_bool_flags(dict(r), ("is_active",)) for r in rows],
            "count": len(rows),
            "total": int((total_rows[0] or {}).get("total") or 0) if total_rows else 0,
            "limit": page_limit,
            "offset": page_offset,
        }

    def upsert_workspace_membership(
        self,
        *,
        workspace_id: str,
        req: WorkspaceMembershipCreateRequest,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        self._assert_workspace_exists(ws)
        uid = _required_text(req.user_id, "user_id")
        role = _required_text(req.role, "role")
        is_default = 1 if bool(req.is_default) else 0
        if is_default:
            self._sql.execute_write(
                "UPDATE workspace_membership SET is_default = 0 WHERE user_id = :user_id",
                {"user_id": uid},
            )
        self._sql.execute_write(
            """
            INSERT INTO workspace_membership (workspace_id, user_id, role, is_active, is_default)
            VALUES (:workspace_id, :user_id, :role, :is_active, :is_default)
            ON DUPLICATE KEY UPDATE
              role = VALUES(role),
              is_active = VALUES(is_active),
              is_default = VALUES(is_default),
              updated_at = CURRENT_TIMESTAMP
            """,
            {
                "workspace_id": ws,
                "user_id": uid,
                "role": role,
                "is_active": 1 if req.is_active else 0,
                "is_default": is_default,
            },
        )
        rows = self._sql.execute_query_mappings(
            _WORKSPACE_MEMBERSHIP_SELECT
            + """
            WHERE wm.workspace_id = :workspace_id AND wm.user_id = :user_id
            LIMIT 1
            """,
            {"workspace_id": ws, "user_id": uid},
        )
        if not rows:
            raise ForgeError("Failed to load workspace membership", status_code=500)
        return _normalize_bool_flags(dict(rows[0]), ("is_active",))

    def update_workspace_membership(
        self,
        *,
        workspace_id: str,
        membership_id: int,
        req: WorkspaceMembershipUpdateRequest,
    ) -> Dict[str, Any]:
        row = self._get_workspace_membership(workspace_id=workspace_id, membership_id=membership_id)
        role = _optional_text(req.role) or str(row.get("role") or "member")
        is_active = (1 if req.is_active else 0) if req.is_active is not None else (1 if row.get("is_active") else 0)
        is_default = (1 if req.is_default else 0) if req.is_default is not None else (1 if row.get("is_default") else 0)
        if is_default:
            self._sql.execute_write(
                "UPDATE workspace_membership SET is_default = 0 WHERE user_id = :user_id",
                {"user_id": str(row.get("user_id") or "")},
            )
        self._sql.execute_write(
            """
            UPDATE workspace_membership
            SET role = :role, is_active = :is_active, is_default = :is_default
            WHERE id = :id AND workspace_id = :workspace_id
            """,
            {
                "id": membership_id,
                "workspace_id": workspace_id,
                "role": role,
                "is_active": is_active,
                "is_default": is_default,
            },
        )
        return self._get_workspace_membership(workspace_id=workspace_id, membership_id=membership_id)

    def delete_workspace_membership(self, *, workspace_id: str, membership_id: int) -> Dict[str, Any]:
        row = self._get_workspace_membership(workspace_id=workspace_id, membership_id=membership_id)
        self._sql.execute_write(
            "DELETE FROM workspace_membership WHERE id = :id AND workspace_id = :workspace_id",
            {"id": membership_id, "workspace_id": workspace_id},
        )
        return {"id": int(row["id"]), "workspace_id": workspace_id, "deleted": True}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _assert_organization_unique(self, *, org_id: str, slug: str, exclude_id: Optional[str]) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, slug
            FROM organization
            WHERE (id = :id OR slug = :slug)
              AND (:exclude_id IS NULL OR id <> :exclude_id)
            LIMIT 1
            """,
            {"id": org_id, "slug": slug, "exclude_id": exclude_id},
        )
        if rows:
            raise ForgeError(
                "Organization id or slug already exists",
                status_code=409,
                details={"organization_id": org_id, "slug": slug},
            )

    def _assert_datasource_unique(
        self,
        *,
        organization_id: str,
        name: str,
        slug: str,
        exclude_id: Optional[int],
    ) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM datasource
            WHERE organization_id = :organization_id
              AND (name = :name OR slug = :slug)
              AND (:exclude_id IS NULL OR id <> :exclude_id)
            LIMIT 1
            """,
            {
                "organization_id": organization_id,
                "name": name,
                "slug": slug,
                "exclude_id": exclude_id,
            },
        )
        if rows:
            raise ForgeError(
                "Datasource name or slug already exists in organization",
                status_code=409,
                details={"organization_id": organization_id, "name": name, "slug": slug},
            )

    def _assert_workspace_exists(self, workspace_id: str) -> None:
        rows = self._sql.execute_query_mappings(
            "SELECT id FROM workspace WHERE id = :id LIMIT 1",
            {"id": workspace_id},
        )
        if not rows:
            raise ForgeError("Workspace not found", status_code=404, details={"workspace_id": workspace_id})

    def _get_datasource_row(self, datasource_id: int) -> Dict[str, Any]:
        did = int(datasource_id)
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id, organization_id, name, slug, type, description, COALESCE(is_active, 1) AS is_active,
              secret_ref, config_json, last_tested_at, last_test_status, last_test_message, created_at, updated_at
            FROM datasource
            WHERE id = :id
            LIMIT 1
            """,
            {"id": did},
        )
        if not rows:
            raise ForgeError("Datasource not found", status_code=404, details={"datasource_id": did})
        return dict(rows[0])

    def _get_org_membership(self, *, organization_id: str, membership_id: int) -> Dict[str, Any]:
        oid = _required_text(organization_id, "organization_id")
        mid = int(membership_id)
        rows = self._sql.execute_query_mappings(
            _ORGANIZATION_MEMBERSHIP_SELECT
            + """
            WHERE om.id = :id AND om.organization_id = :organization_id
            LIMIT 1
            """,
            {"id": mid, "organization_id": oid},
        )
        if not rows:
            raise ForgeError("Organization membership not found", status_code=404, details={"id": mid, "organization_id": oid})
        return _normalize_bool_flags(dict(rows[0]), ("is_active",))

    def _get_workspace_membership(self, *, workspace_id: str, membership_id: int) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        mid = int(membership_id)
        rows = self._sql.execute_query_mappings(
            _WORKSPACE_MEMBERSHIP_SELECT
            + """
            WHERE wm.id = :id AND wm.workspace_id = :workspace_id
            LIMIT 1
            """,
            {"id": mid, "workspace_id": ws},
        )
        if not rows:
            raise ForgeError("Workspace membership not found", status_code=404, details={"id": mid, "workspace_id": ws})
        return _normalize_bool_flags(dict(rows[0]), ("is_active",))


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ForgeError(f"{field_name} is required", status_code=400)
    return text


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_datasource_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text not in _SUPPORTED_DATASOURCE_TYPES:
        raise ForgeError(
            "Unsupported datasource type",
            status_code=400,
            details={"type": text, "allowed": sorted(_SUPPORTED_DATASOURCE_TYPES)},
        )
    return text


def _json_dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _json_loads(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except JSON_PARSE_ERRORS:
            return value
    return value


def _normalize_bool_flags(row: Dict[str, Any], fields: tuple[str, ...]) -> Dict[str, Any]:
    out = dict(row)
    for field in fields:
        if field in out:
            out[field] = bool(int(out[field] or 0))
    for key, value in list(out.items()):
        out[key] = _json_safe_value(value)
    return out


def _coerce_datasource_row(row: Dict[str, Any], *, public: bool = True) -> Dict[str, Any]:
    out = _normalize_bool_flags(row, ("is_active",))
    datasource_type = str(out.get("type") or "").strip().lower()
    config = _json_loads(out.get("config_json"))
    if not isinstance(config, dict):
        config = {}
    config = decrypt_datasource_config(datasource_type, config)
    out["config_json"] = mask_datasource_config(datasource_type, config) if public else config
    return out


def _coerce_workspace_binding_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = _normalize_bool_flags(
        row,
        ("workspace_is_active", "organization_is_active", "datasource_is_active"),
    )
    return out


def _dedupe_namespace_values(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = _optional_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(v) for v in value]
    return value
