from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_admin, require_role
from app.decorators.security import token_required
from app.models.tenancy.tenancy_admin import (
    DatasourceCreateRequest,
    DatasourceUpdateRequest,
    OrganizationCreateRequest,
    OrganizationMembershipCreateRequest,
    OrganizationMembershipUpdateRequest,
    OrganizationUpdateRequest,
    TenancyBootstrapRequest,
    WorkspaceBindingUpdateRequest,
    WorkspaceCreateRequest,
    WorkspaceMembershipCreateRequest,
    WorkspaceMembershipUpdateRequest,
)
from app.services.tenancy.tenancy_bootstrap_service import BootstrapInput

from .base import admin_ns
from .deps import tenancy_admin_service, tenancy_bootstrap_service
from .helpers import (
    _as_bool,
    _assert_workspace_admin_datasource_access,
    _assert_workspace_admin_organization_access,
    _current_workspace_binding,
    _is_super_admin_request,
    _matches_scoped_organization_row,
    _matches_scoped_workspace_row,
    _paged_rows,
    _require_admin,
)
from .models import (
    datasource_create_model,
    datasource_update_model,
    organization_create_model,
    organization_membership_create_model,
    organization_membership_update_model,
    organization_update_model,
    tenancy_bootstrap_model,
    workspace_binding_update_model,
    workspace_create_model,
    workspace_membership_create_model,
    workspace_membership_update_model,
)


@admin_ns.route("/tenancy/bootstrap")
class TenancyBootstrap(Resource):
    @token_required
    @require_role("system:admin")
    @admin_ns.expect(tenancy_bootstrap_model, validate=False)
    def post(self):
        _require_admin()
        req = TenancyBootstrapRequest(**(request.get_json(silent=True) or {}))
        result = tenancy_bootstrap_service().bootstrap(
            BootstrapInput(
                workspace_id=req.workspace_id,
                organization_name=req.organization_name,
                organization_id=req.organization_id,
                organization_slug=req.organization_slug,
                organization_description=req.organization_description,
                datasource_name=req.datasource_name,
                datasource_type=req.datasource_type,
                datasource_slug=req.datasource_slug,
                datasource_description=req.datasource_description,
                datasource_secret_ref=req.datasource_secret_ref,
                datasource_config_json=req.datasource_config_json,
                default_catalog=req.default_catalog,
                default_schema=req.default_schema,
                admin_user_id=req.admin_user_id,
            )
        )
        return {"result": result}, 200


@admin_ns.route("/organizations")
class OrganizationListCreate(Resource):
    @token_required
    @require_admin()
    def get(self):
        _require_admin()
        include_inactive = _as_bool(
            request.args.get("include_inactive"),
            default=False,
        )
        q = str(request.args.get("q") or "").strip() or None
        limit = request.args.get("limit", default=100, type=int) or 100
        offset = request.args.get("offset", default=0, type=int) or 0
        service = tenancy_admin_service()
        if _is_super_admin_request():
            return service.list_organizations(
                include_inactive=include_inactive,
                q=q,
                limit=limit,
                offset=offset,
            ), 200

        scoped_binding = _current_workspace_binding(service)
        organization_id = str(scoped_binding.get("organization_id") or "").strip()
        if not organization_id:
            return _paged_rows([], limit=limit, offset=offset), 200

        organization = service.get_organization(organization_id)
        rows = (
            [organization]
            if _matches_scoped_organization_row(
                organization,
                include_inactive=include_inactive,
                q=q,
            )
            else []
        )
        return _paged_rows(rows, limit=limit, offset=offset), 200

    @token_required
    @require_role("system:admin")
    @admin_ns.expect(organization_create_model, validate=False)
    def post(self):
        _require_admin()
        req = OrganizationCreateRequest(**(request.get_json(silent=True) or {}))
        result = tenancy_admin_service().create_organization(req)
        return result, 201


@admin_ns.route("/organizations/<string:organization_id>")
class OrganizationDetail(Resource):
    @token_required
    @require_role("system:admin")
    @admin_ns.expect(organization_update_model, validate=False)
    def patch(self, organization_id: str):
        _require_admin()
        req = OrganizationUpdateRequest(**(request.get_json(silent=True) or {}))
        result = tenancy_admin_service().update_organization(organization_id, req)
        return result, 200

    @token_required
    @require_role("system:admin")
    def delete(self, organization_id: str):
        _require_admin()
        hard = _as_bool(request.args.get("hard"), default=False)
        result = tenancy_admin_service().delete_organization(
            organization_id,
            hard=hard,
        )
        return result, 200


@admin_ns.route("/organizations/<string:organization_id>/memberships")
class OrganizationMembershipListCreate(Resource):
    @token_required
    @require_role("system:admin")
    def get(self, organization_id: str):
        _require_admin()
        include_inactive = _as_bool(
            request.args.get("include_inactive"),
            default=False,
        )
        limit = request.args.get("limit", default=200, type=int) or 200
        offset = request.args.get("offset", default=0, type=int) or 0
        result = tenancy_admin_service().list_organization_memberships(
            organization_id=organization_id,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )
        return result, 200

    @token_required
    @require_role("system:admin")
    @admin_ns.expect(organization_membership_create_model, validate=False)
    def post(self, organization_id: str):
        _require_admin()
        req = OrganizationMembershipCreateRequest(**(request.get_json(silent=True) or {}))
        result = tenancy_admin_service().upsert_organization_membership(
            organization_id=organization_id,
            req=req,
        )
        return result, 201


@admin_ns.route("/organizations/<string:organization_id>/memberships/<int:membership_id>")
class OrganizationMembershipDetail(Resource):
    @token_required
    @require_role("system:admin")
    @admin_ns.expect(organization_membership_update_model, validate=False)
    def patch(self, organization_id: str, membership_id: int):
        _require_admin()
        req = OrganizationMembershipUpdateRequest(**(request.get_json(silent=True) or {}))
        result = tenancy_admin_service().update_organization_membership(
            organization_id=organization_id,
            membership_id=membership_id,
            req=req,
        )
        return result, 200

    @token_required
    @require_role("system:admin")
    def delete(self, organization_id: str, membership_id: int):
        _require_admin()
        result = tenancy_admin_service().delete_organization_membership(
            organization_id=organization_id,
            membership_id=membership_id,
        )
        return result, 200


@admin_ns.route("/organizations/<string:organization_id>/datasources")
class OrganizationDatasourceListCreate(Resource):
    @token_required
    @require_admin()
    def get(self, organization_id: str):
        _require_admin()
        service = tenancy_admin_service()
        _assert_workspace_admin_organization_access(service, organization_id)
        include_inactive = _as_bool(
            request.args.get("include_inactive"),
            default=False,
        )
        limit = request.args.get("limit", default=100, type=int) or 100
        offset = request.args.get("offset", default=0, type=int) or 0
        result = service.list_datasources(
            organization_id=organization_id,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )
        return result, 200

    @token_required
    @require_admin()
    @admin_ns.expect(datasource_create_model, validate=False)
    def post(self, organization_id: str):
        _require_admin()
        service = tenancy_admin_service()
        _assert_workspace_admin_organization_access(service, organization_id)
        req = DatasourceCreateRequest(**(request.get_json(silent=True) or {}))
        result = service.create_datasource(organization_id=organization_id, req=req)
        return result, 201


@admin_ns.route("/datasources/<int:datasource_id>")
class DatasourceDetail(Resource):
    @token_required
    @require_admin()
    @admin_ns.expect(datasource_update_model, validate=False)
    def patch(self, datasource_id: int):
        _require_admin()
        service = tenancy_admin_service()
        _assert_workspace_admin_datasource_access(service, datasource_id)
        req = DatasourceUpdateRequest(**(request.get_json(silent=True) or {}))
        result = service.update_datasource(datasource_id=datasource_id, req=req)
        return result, 200

    @token_required
    @require_admin()
    def delete(self, datasource_id: int):
        _require_admin()
        service = tenancy_admin_service()
        _assert_workspace_admin_datasource_access(service, datasource_id)
        hard = _as_bool(request.args.get("hard"), default=False)
        result = service.delete_datasource(datasource_id=datasource_id, hard=hard)
        return result, 200


@admin_ns.route("/datasources/<int:datasource_id>/test")
class DatasourceConnectionTest(Resource):
    @token_required
    @require_admin()
    def post(self, datasource_id: int):
        _require_admin()
        service = tenancy_admin_service()
        _assert_workspace_admin_datasource_access(service, datasource_id)
        result = service.test_datasource(datasource_id=datasource_id)
        return {"result": result}, 200


@admin_ns.route("/datasources/<int:datasource_id>/namespaces")
class DatasourceNamespaces(Resource):
    @token_required
    @require_admin()
    def get(self, datasource_id: int):
        _require_admin()
        service = tenancy_admin_service()
        _assert_workspace_admin_datasource_access(service, datasource_id)
        result = service.list_datasource_namespaces(
            datasource_id=datasource_id,
            catalog=(request.args.get("catalog") or "").strip() or None,
        )
        return result, 200


@admin_ns.route("/workspaces")
class WorkspaceBindingList(Resource):
    @token_required
    @require_admin()
    def get(self):
        _require_admin()
        include_inactive = _as_bool(
            request.args.get("include_inactive"),
            default=False,
        )
        organization_id = str(request.args.get("organization_id") or "").strip() or None
        limit = request.args.get("limit", default=200, type=int) or 200
        offset = request.args.get("offset", default=0, type=int) or 0
        service = tenancy_admin_service()
        if _is_super_admin_request():
            result = service.list_workspace_bindings(
                organization_id=organization_id,
                include_inactive=include_inactive,
                limit=limit,
                offset=offset,
            )
            return result, 200

        scoped_binding = _current_workspace_binding(service)
        rows = (
            [scoped_binding]
            if _matches_scoped_workspace_row(
                scoped_binding,
                include_inactive=include_inactive,
                organization_id=organization_id,
            )
            else []
        )
        return _paged_rows(rows, limit=limit, offset=offset), 200

    @token_required
    @require_role("system:admin")
    @admin_ns.expect(workspace_create_model, validate=False)
    def post(self):
        _require_admin()
        req = WorkspaceCreateRequest(**(request.get_json(silent=True) or {}))
        result = tenancy_admin_service().create_workspace(req)
        return result, 201


@admin_ns.route("/workspaces/<string:workspace_id>/binding")
class WorkspaceBindingDetail(Resource):
    @token_required
    @require_role("system:admin")
    def get(self, workspace_id: str):
        _require_admin()
        return tenancy_admin_service().get_workspace_binding(workspace_id), 200

    @token_required
    @require_role("system:admin")
    @admin_ns.expect(workspace_binding_update_model, validate=False)
    def patch(self, workspace_id: str):
        _require_admin()
        req = WorkspaceBindingUpdateRequest(**(request.get_json(silent=True) or {}))
        result = tenancy_admin_service().update_workspace_binding(
            workspace_id=workspace_id,
            req=req,
        )
        return result, 200


@admin_ns.route("/workspaces/<string:workspace_id>")
class WorkspaceDetail(Resource):
    @token_required
    @require_role("system:admin")
    def delete(self, workspace_id: str):
        _require_admin()
        hard = _as_bool(request.args.get("hard"), default=False)
        result = tenancy_admin_service().delete_workspace(
            workspace_id=workspace_id,
            hard=hard,
        )
        return result, 200


@admin_ns.route("/workspaces/<string:workspace_id>/memberships")
class WorkspaceMembershipListCreate(Resource):
    @token_required
    @require_role("system:admin")
    def get(self, workspace_id: str):
        _require_admin()
        include_inactive = _as_bool(
            request.args.get("include_inactive"),
            default=False,
        )
        limit = request.args.get("limit", default=200, type=int) or 200
        offset = request.args.get("offset", default=0, type=int) or 0
        result = tenancy_admin_service().list_workspace_memberships(
            workspace_id=workspace_id,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )
        return result, 200

    @token_required
    @require_role("system:admin")
    @admin_ns.expect(workspace_membership_create_model, validate=False)
    def post(self, workspace_id: str):
        _require_admin()
        req = WorkspaceMembershipCreateRequest(**(request.get_json(silent=True) or {}))
        result = tenancy_admin_service().upsert_workspace_membership(
            workspace_id=workspace_id,
            req=req,
        )
        return result, 201


@admin_ns.route("/workspaces/<string:workspace_id>/memberships/<int:membership_id>")
class WorkspaceMembershipDetail(Resource):
    @token_required
    @require_role("system:admin")
    @admin_ns.expect(workspace_membership_update_model, validate=False)
    def patch(self, workspace_id: str, membership_id: int):
        _require_admin()
        req = WorkspaceMembershipUpdateRequest(**(request.get_json(silent=True) or {}))
        result = tenancy_admin_service().update_workspace_membership(
            workspace_id=workspace_id,
            membership_id=membership_id,
            req=req,
        )
        return result, 200

    @token_required
    @require_role("system:admin")
    def delete(self, workspace_id: str, membership_id: int):
        _require_admin()
        result = tenancy_admin_service().delete_workspace_membership(
            workspace_id=workspace_id,
            membership_id=membership_id,
        )
        return result, 200
