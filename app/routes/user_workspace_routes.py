from __future__ import annotations

from typing import Any
from urllib.parse import quote

from flask import request
from flask_restx import Namespace, fields, reqparse
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.decorators.rbac import require_admin
from app.services.user_service import UserService

_parser = reqparse.RequestParser()
_parser.add_argument("user_id", type=str, required=True, help="The user id", location="args")
_parser.add_argument("workspace_id", type=str, required=True, help="The workspace id", location="args")

user_workspace_ns = Namespace("user-workspaces", description="Manage the user to workspace relationship")

mapping_model = user_workspace_ns.model(
    "UserWorkspaceMapping",
    {
        "user_id": fields.String(required=True, description="The ID of the user"),
        "workspace_id": fields.String(required=True, description="The ID of the workspace"),
        "is_default": fields.Boolean(required=False, description="Is this the default workspace for the user."),
    },
)

connection_response = user_workspace_ns.model(
    "ConnectionResponse",
    {"message": fields.String(description="Success or error message")},
)


def _user_service() -> UserService:
    return UserService()


def _json_payload() -> dict[str, Any]:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


@user_workspace_ns.route("")
@user_workspace_ns.doc()
class UserWorkspaceMap(ForgeResource):
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
