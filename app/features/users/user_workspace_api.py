from __future__ import annotations

from typing import Any
from urllib.parse import quote

from flask import request
from flask_restx import Namespace, Resource

from app.decorators.rbac import require_admin
from app.decorators.security import token_required
from app.features.users.schemas import build_user_workspace_parser, register_user_workspace_models
from app.features.users.service import users_feature_service
from app.services.user_service import UserService

user_workspace_ns = Namespace("user-workspaces", description="Manage the user to workspace relationship")
MODELS = register_user_workspace_models(user_workspace_ns)
mapping_model = MODELS["mapping_model"]
connection_response = MODELS["connection_response"]
_parser = build_user_workspace_parser()


def _user_service() -> UserService:
    return users_feature_service.build_user_service(user_service_factory=UserService)


def _json_payload() -> dict[str, Any]:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


@user_workspace_ns.route("")
@user_workspace_ns.doc()
class UserWorkspaceMap(Resource):
    @token_required
    @require_admin()
    @user_workspace_ns.expect(mapping_model)
    @user_workspace_ns.response(201, "Mapping created successfully", connection_response)
    @user_workspace_ns.response(400, "Invalid input")
    def post(self):
        data = _json_payload()
        user_id = data.get("user_id")
        workspace_id = data.get("workspace_id")
        is_default = bool(data.get("is_default", False))

        if not user_id or not workspace_id:
            return {"error": "user_id and workspace_id are required"}, 400

        return _user_service().map_user_workspace(user_id, workspace_id, is_default)

    @token_required
    @require_admin()
    @user_workspace_ns.expect(_parser)
    @user_workspace_ns.response(200, "Mapping deleted successfully", connection_response)
    @user_workspace_ns.response(400, "Missing required query parameter")
    def delete(self):
        args = _parser.parse_args()
        user_id = args.get("user_id")
        workspace_id = args.get("workspace_id")

        if not user_id:
            return {"error": "Missing required query parameter 'user_id'"}, 400
        if not workspace_id:
            return {"error": "Missing required query parameter 'workspace_id'"}, 400

        return _user_service().delete_user_workspace(quote(user_id), quote(workspace_id))

    @token_required
    @require_admin()
    @user_workspace_ns.expect(_parser)
    @user_workspace_ns.response(200, "Connection retrieved successfully", connection_response)
    @user_workspace_ns.response(400, "Missing required query parameter")
    def put(self):
        data = _json_payload()
        user_id = data.get("user_id")
        workspace_id = data.get("workspace_id")
        is_default = bool(data.get("is_default", False))

        if not user_id or not workspace_id:
            return {"error": "user_id and workspace_id are required"}, 400

        return _user_service().set_workspace_default(user_id, workspace_id, is_default)
