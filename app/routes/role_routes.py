from __future__ import annotations

from flask import request
from flask_restx import Namespace, fields
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.services.role_service import RoleService

role_ns = Namespace("roles", description="Role management")

role_model = role_ns.model(
    "role",
    {
        "role_id": fields.String(required=True, description="The unique identifier of the role"),
        "name": fields.String(require=True, description="The name of the role"),
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
    def get(self):
        return _service().get_roles()

    @token_required
    def post(self):
        payload = request.get_json(silent=True) or {}
        return _service().add_role(payload["role_name"]), 201


@role_ns.route("/<string:role_id>")
class RoleDetails(ForgeResource):
    @token_required
    def delete(self, role_id: str):
        return _service().delete_role(role_id)

    @token_required
    def get(self, role_id: str):
        return _service().get_role(role_id)
