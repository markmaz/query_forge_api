from __future__ import annotations

from flask import request
from flask_restx import Namespace, fields
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.decorators.rbac import require_admin
from app.services.role_service import RoleService

role_ns = Namespace("roles", description="Role management")

role_model = role_ns.model(
    "role",
    {
        "role_name": fields.String(required=True, description="Canonical role name"),
        "display_name": fields.String(required=False, description="Human readable role name"),
        "description": fields.String(required=False, description="Role description"),
        "feature_key": fields.String(required=False, description="Owning feature key"),
        "is_system": fields.Boolean(required=False, description="True for system-managed roles"),
    },
)

roles = role_ns.model("role_list", {"roles": fields.List(fields.Nested(role_model))})


def _service() -> RoleService:
    return RoleService()


@role_ns.route("")
@role_ns.response(200, "The list of roles", roles)
class RoleList(ForgeResource):
    @role_ns.expect()
    @token_required
    @require_admin()
    def get(self):
        return _service().get_roles()

    @token_required
    @require_admin()
    def post(self):
        payload = request.get_json(silent=True) or {}
        return _service().add_role(payload["role_name"]), 201


@role_ns.route("/<string:role_name>")
class RoleDetails(ForgeResource):
    @token_required
    @require_admin()
    def delete(self, role_name: str):
        return _service().delete_role(role_name)

    @token_required
    @require_admin()
    def get(self, role_name: str):
        return _service().get_role(role_name)
