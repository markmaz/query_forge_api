from __future__ import annotations

from flask import g

from app.exceptions.forge_error import ForgeError
from app.services.tenancy.tenancy_admin_service import TenancyAdminService


def _require_admin() -> None:
    effective_roles = getattr(g, "effective_roles", set()) or set()
    if (
        bool(getattr(g, "is_admin", False))
        or "super_admin" in effective_roles
        or "workspace_admin" in effective_roles
    ):
        return
    raise ForgeError("Admin access required", status_code=403)


def _is_super_admin_request() -> bool:
    effective_roles = getattr(g, "effective_roles", set()) or set()
    return "super_admin" in effective_roles


def _current_workspace_binding(service: TenancyAdminService) -> dict:
    workspace_id = str(getattr(g, "workspace_id", "") or "").strip()
    if not workspace_id:
        raise ForgeError(
            "X-Workspace-Id header is required for workspace-scoped admin access",
            status_code=400,
        )
    return service.get_workspace_binding(workspace_id)


def _assert_workspace_admin_organization_access(
    service: TenancyAdminService,
    organization_id: str,
) -> None:
    if _is_super_admin_request():
        return
    scoped_binding = _current_workspace_binding(service)
    scoped_org_id = str(scoped_binding.get("organization_id") or "").strip()
    requested_org_id = str(organization_id or "").strip()
    if not scoped_org_id or requested_org_id != scoped_org_id:
        raise ForgeError(
            "Workspace admin access is limited to the current workspace organization",
            status_code=403,
        )


def _assert_workspace_admin_workspace_access(
    service: TenancyAdminService,
    workspace_id: str,
) -> None:
    if _is_super_admin_request():
        return
    scoped_binding = _current_workspace_binding(service)
    scoped_workspace_id = str(scoped_binding.get("workspace_id") or "").strip()
    requested_workspace_id = str(workspace_id or "").strip()
    if not scoped_workspace_id or requested_workspace_id != scoped_workspace_id:
        raise ForgeError(
            "Workspace admin access is limited to the current workspace",
            status_code=403,
        )


def _assert_workspace_admin_datasource_access(
    service: TenancyAdminService,
    datasource_id: int,
) -> dict:
    if _is_super_admin_request():
        return {}
    row = service.get_datasource(int(datasource_id))
    _assert_workspace_admin_organization_access(
        service,
        str(row.get("organization_id") or ""),
    )
    return row


def _paged_rows(rows: list[dict], *, limit: int, offset: int) -> dict:
    page_limit = max(1, int(limit or 1))
    page_offset = max(0, int(offset or 0))
    paged = rows[page_offset : page_offset + page_limit]
    return {
        "rows": paged,
        "count": len(paged),
        "total": len(rows),
        "limit": page_limit,
        "offset": page_offset,
    }


def _matches_scoped_organization_row(
    row: dict,
    *,
    include_inactive: bool,
    q: str | None,
) -> bool:
    if not include_inactive and not bool(row.get("is_active", True)):
        return False
    if not q:
        return True
    query = str(q or "").strip().lower()
    name = str(row.get("name") or "").strip().lower()
    slug = str(row.get("slug") or "").strip().lower()
    return query in name or query in slug


def _matches_scoped_workspace_row(
    row: dict,
    *,
    include_inactive: bool,
    organization_id: str | None,
) -> bool:
    if not include_inactive and not bool(row.get("workspace_is_active", True)):
        return False
    if organization_id and str(row.get("organization_id") or "").strip() != str(
        organization_id
    ).strip():
        return False
    return True


def _as_bool(value, *, default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default
