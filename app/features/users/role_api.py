from __future__ import annotations

from flask import request
from flask_restx import Namespace, Resource

from app.decorators.rbac import require_admin
from app.decorators.security import token_required
from app.features.users.schemas import register_role_models
from app.features.users.service import users_feature_service
from app.services.role_service import RoleService

role_ns = Namespace("roles", description="Role management")
MODELS = register_role_models(role_ns)
role_model = MODELS["role_model"]
roles = MODELS["roles"]


def _service() -> RoleService:
    return users_feature_service.build_role_service(role_service_factory=RoleService)


@role_ns.route("")
@role_ns.response(200, "The list of roles", roles)
class RoleList(Resource):
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
class RoleDetails(Resource):
    @token_required
    @require_admin()
    def delete(self, role_name: str):
        return _service().delete_role(role_name)

    @token_required
    @require_admin()
    def get(self, role_name: str):
        return _service().get_role(role_name)
