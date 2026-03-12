from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.exceptions.forge_error import ForgeError
from app.models.tenancy_admin import (
    DatasourceCreateRequest,
    OrganizationCreateRequest,
    OrganizationMembershipCreateRequest,
    WorkspaceBindingUpdateRequest,
    WorkspaceMembershipCreateRequest,
    normalize_slug,
)
from app.services.tenancy.tenancy_admin_service import TenancyAdminService


@dataclass(frozen=True)
class BootstrapInput:
    workspace_id: str
    organization_name: str
    datasource_name: str
    datasource_type: str
    organization_id: Optional[str] = None
    organization_slug: Optional[str] = None
    organization_description: Optional[str] = None
    datasource_slug: Optional[str] = None
    datasource_description: Optional[str] = None
    datasource_secret_ref: Optional[str] = None
    datasource_config_json: Optional[Dict[str, Any]] = None
    default_catalog: Optional[str] = None
    default_schema: Optional[str] = None
    admin_user_id: Optional[str] = None


class TenancyBootstrapService:
    """Idempotent first-run tenancy bootstrap.

    Creates organization/datasource if missing, binds workspace to both, and
    optionally grants org/workspace admin membership to a user.
    """

    def __init__(self, *, admin: Optional[TenancyAdminService] = None) -> None:
        self._admin = admin or TenancyAdminService()

    def bootstrap(self, req: BootstrapInput) -> Dict[str, Any]:
        ws = str(req.workspace_id or "").strip()
        if not ws:
            raise ForgeError("workspace_id is required", status_code=400)

        org = self._resolve_or_create_org(req)
        datasource = self._resolve_or_create_datasource(req=req, organization_id=str(org["id"]))

        binding = self._admin.update_workspace_binding(
            workspace_id=ws,
            req=WorkspaceBindingUpdateRequest(
                organization_id=str(org["id"]),
                datasource_id=int(datasource["id"]),
                default_catalog=req.default_catalog,
                default_schema=req.default_schema,
                is_active=True,
            ),
        )

        memberships = {}
        admin_user_id = str(req.admin_user_id or "").strip()
        if admin_user_id:
            org_member = self._admin.upsert_organization_membership(
                organization_id=str(org["id"]),
                req=OrganizationMembershipCreateRequest(
                    user_id=admin_user_id,
                    role="org_admin",
                    is_active=True,
                ),
            )
            ws_member = self._admin.upsert_workspace_membership(
                workspace_id=ws,
                req=WorkspaceMembershipCreateRequest(
                    user_id=admin_user_id,
                    role="admin",
                    is_active=True,
                ),
            )
            memberships = {
                "organization_membership": org_member,
                "workspace_membership": ws_member,
            }

        return {
            "workspace_id": ws,
            "organization": org,
            "datasource": datasource,
            "workspace_binding": binding,
            "memberships": memberships,
        }

    def _resolve_or_create_org(self, req: BootstrapInput) -> Dict[str, Any]:
        explicit_id = str(req.organization_id or "").strip() or None
        if explicit_id:
            try:
                return self._admin.get_organization(explicit_id)
            except ForgeError as exc:
                if exc.status_code != 404:
                    raise

        slug = str(req.organization_slug or "").strip() or normalize_slug(req.organization_name)
        rows = self._admin.list_organizations(include_inactive=True, q=slug, limit=200, offset=0).get("rows", [])
        for row in rows:
            row_slug = str(row.get("slug") or "").strip().lower()
            row_name = str(row.get("name") or "").strip().lower()
            if row_slug == slug.lower() or row_name == req.organization_name.strip().lower():
                return row

        return self._admin.create_organization(
            OrganizationCreateRequest(
                id=explicit_id,
                name=req.organization_name,
                slug=slug,
                description=req.organization_description,
                is_active=True,
            )
        )

    def _resolve_or_create_datasource(self, *, req: BootstrapInput, organization_id: str) -> Dict[str, Any]:
        slug = str(req.datasource_slug or "").strip() or normalize_slug(req.datasource_name)
        rows = self._admin.list_datasources(
            organization_id=organization_id,
            include_inactive=True,
            limit=500,
            offset=0,
        ).get("rows", [])
        for row in rows:
            row_slug = str(row.get("slug") or "").strip().lower()
            row_name = str(row.get("name") or "").strip().lower()
            if row_slug == slug.lower() or row_name == req.datasource_name.strip().lower():
                return row

        return self._admin.create_datasource(
            organization_id=organization_id,
            req=DatasourceCreateRequest(
                name=req.datasource_name,
                slug=slug,
                type=req.datasource_type.strip().lower(),
                description=req.datasource_description,
                is_active=True,
                secret_ref=req.datasource_secret_ref,
                config_json=req.datasource_config_json or {},
            ),
        )
