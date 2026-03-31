from __future__ import annotations

import logging

from flask import jsonify, request
from flask_restx import Namespace, Resource
from pydantic import ValidationError

from app.decorators.rbac import require_admin
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.users.schemas import build_user_parser, register_user_models
from app.features.users.service import users_feature_service
from app.models.tenancy.user import User
from app.models.tenancy.user_workspace import UserInvitation
from app.routes.request_helpers import extract_workspace_id
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

qf_user_ns = Namespace("users", description="User management operations")
MODELS = register_user_models(qf_user_ns)
qf_user_parser = build_user_parser()
user_model = MODELS["user_model"]
mapping_model = MODELS["mapping_model"]
user_role_add_model = MODELS["user_role_add_model"]
user_role_replace_model = MODELS["user_role_replace_model"]
user_role_update_model = MODELS["user_role_update_model"]
pagination_response = MODELS["pagination_response"]


def _public_user_payload(user: User) -> dict:
    return users_feature_service.public_user_payload(user)


def _admin_user_scope_workspace_id() -> str | None:
    return users_feature_service.admin_user_scope_workspace_id()


@qf_user_ns.route("/")
class UserList(Resource):
    @qf_user_ns.response(201, "User invite created")
    @qf_user_ns.doc(security="BearerAuth")
    @token_required
    @require_admin()
    def post(self):
        try:
            payload = UserInvitation(**request.json)
        except ValidationError as e:
            return {"error": e.errors()}, 400

        result = users_feature_service.build_user_service(user_service_factory=UserService).create_invite(payload)
        return result, 201

    @token_required
    @require_admin()
    def get(self):
        args = qf_user_parser.parse_args()
        workspace_id = _admin_user_scope_workspace_id()
        logger.info("Parsed args: %s", args)
        logger.info(args["status"])
        try:
            users, next_cursor, prev_cursor, total_count = users_feature_service.build_user_service(
                user_service_factory=UserService
            ).get_users(
                status=args["status"],
                cursor=args["cursor"],
                limit=args["limit"],
                direction=args["direction"],
                username=args["q"],
                workspace_id=workspace_id,
            )
            return {
                "users": [_public_user_payload(user) for user in users],
                "next_cursor": next_cursor,
                "prev_cursor": prev_cursor,
                "total_count": total_count,
            }, 200
        except Exception as e:
            qf_user_ns.abort(500, f"Error fetching users: {str(e)}")


@qf_user_ns.route("/<string:user_id>")
@qf_user_ns.param("user_id", "The user identifier")
class UserUpdates(Resource):
    @qf_user_ns.response(200, "User updated")
    @qf_user_ns.doc(security="BearerAuth")
    @token_required
    @require_admin()
    def put(self, user_id):
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            raise ForgeError("Invalid JSON body", status_code=400)

        user = User(**body)
        result = users_feature_service.build_user_service(user_service_factory=UserService).update_user(
            user_id=user_id,
            update_data=user,
            workspace_id=_admin_user_scope_workspace_id(),
        )
        return jsonify(_public_user_payload(result))

    @qf_user_ns.response(200, "User deleted")
    @qf_user_ns.doc(security="BearerAuth")
    @token_required
    @require_admin()
    def delete(self, user_id):
        result = users_feature_service.build_user_service(user_service_factory=UserService).delete_user(user_id)
        return result

    @token_required
    @require_admin()
    def get(self, user_id):
        result = users_feature_service.build_user_service(user_service_factory=UserService).get_user(
            user_id,
            workspace_id=_admin_user_scope_workspace_id(),
        )
        return jsonify(_public_user_payload(result))

    def options(self, user_id):
        return {}, 200


@qf_user_ns.route("/<string:user_id>/workspaces")
class UserWorkspaces(Resource):
    @token_required
    @require_admin()
    def get(self, user_id):
        results = users_feature_service.build_user_service(user_service_factory=UserService).get_user_workspaces(user_id)
        return results


@qf_user_ns.route("/<string:user_id>/roles")
class UserDirectRoles(Resource):
    @token_required
    @require_admin()
    def get(self, user_id):
        workspace_id = extract_workspace_id()
        user_service = users_feature_service.build_user_service(user_service_factory=UserService)
        direct_roles = user_service.get_user_direct_roles(user_id, workspace_id=workspace_id)
        effective_roles = user_service.get_user_effective_roles(user_id, workspace_id=workspace_id)
        return {
            "user_id": user_id,
            "workspace_id": workspace_id,
            "direct_roles": direct_roles,
            "effective_roles": effective_roles,
        }, 200

    @token_required
    @require_admin()
    @qf_user_ns.expect(user_role_add_model, validate=False)
    def post(self, user_id):
        workspace_id = extract_workspace_id()
        data = request.get_json(silent=True) or {}
        role_name = str(data.get("role_name") or "").strip()
        if not role_name:
            return {"error": "role_name is required"}, 400
        mapping = users_feature_service.build_user_service(user_service_factory=UserService).add_user_direct_role(
            user_id, role_name, workspace_id=workspace_id
        )
        return {"mapping": mapping}, 200

    @token_required
    @require_admin()
    @qf_user_ns.expect(user_role_replace_model, validate=False)
    def put(self, user_id):
        workspace_id = extract_workspace_id()
        data = request.get_json(silent=True) or {}
        role_names = data.get("role_names")
        if not isinstance(role_names, list):
            return {"error": "role_names must be an array"}, 400
        result = users_feature_service.build_user_service(user_service_factory=UserService).replace_user_direct_roles(
            user_id, role_names, workspace_id=workspace_id
        )
        return result, 200


@qf_user_ns.route("/<string:user_id>/roles/<string:role_name>")
class UserDirectRoleById(Resource):
    @token_required
    @require_admin()
    @qf_user_ns.expect(user_role_update_model, validate=False)
    def patch(self, user_id, role_name):
        workspace_id = extract_workspace_id()
        data = request.get_json(silent=True) or {}
        new_role_name = str(data.get("role_name") or "").strip()
        if not new_role_name:
            return {"error": "role_name is required"}, 400
        result = users_feature_service.build_user_service(user_service_factory=UserService).update_user_direct_role(
            user_id,
            role_name,
            new_role_name,
            workspace_id=workspace_id,
        )
        return result, 200

    @token_required
    @require_admin()
    def delete(self, user_id, role_name):
        workspace_id = extract_workspace_id()
        result = users_feature_service.build_user_service(user_service_factory=UserService).remove_user_direct_role(
            user_id, role_name, workspace_id=workspace_id
        )
        return result, 200


@qf_user_ns.route("/<string:user_id>/workspaces/<string:workspace_id>/dashboards/<string:dashboard_id>/embed")
class UserWorkspaceDashboard(Resource):
    @token_required
    @qf_user_ns.doc(
        description=(
            "## User Organization Sigma Embed URL\n"
            "This endpoint allows clients to retrieve the embed URL for a given user's organization. The embed will switch the connection to the correct organization based on the given workspace id\n\n"
            "**Required URL Parameters:**\n"
            "- `user_id`: The id of the given user.\n"
            "- `workspace_id`: The ID of the organization's Databricks workspace\n\n"
            "- `dashboard_id`: The ID of the Sigma Dashboard\n\n"
            "**Response Codes:**\n"
            "- `201`: Example created successfully.\n"
            "- `400`: Validation error."
        )
    )
    def get(self, user_id, workspace_id, dashboard_id):
        return {"status": "ok"}, 200

    def options(self, user_id, workspace_id, dashboard_id):
        return {}, 200


@qf_user_ns.route("/counts")
class UserCounts(Resource):
    @token_required
    @require_admin()
    def get(self):
        results = users_feature_service.build_user_service(user_service_factory=UserService).get_counts(
            workspace_id=(request.headers.get("X-Workspace-Id") or "").strip() or None,
        )
        return results, 200


@qf_user_ns.route("/resend-invite")
class ResentInvite(Resource):
    @token_required
    @require_admin()
    def post(self):
        try:
            payload = UserInvitation(**request.json)
        except ValidationError as e:
            return {"error": e.errors()}, 400

        users_feature_service.build_user_service(user_service_factory=UserService).resend_invite(payload.user_id, payload.email)


@qf_user_ns.route("/bulk-invite")
class BulkInviteUsers(Resource):
    @token_required
    @require_admin()
    def post(self):
        data = request.json
        return users_feature_service.build_user_service(user_service_factory=UserService).create_invite_bulk(
            data["emails"], data["workspaces"]
        )
