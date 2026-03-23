import logging

from flask import g, jsonify, request
from flask_restx import Namespace, fields, reqparse
from app.routes.forge_resource import ForgeResource
from pydantic import ValidationError

from app.decorators.security import token_required
from app.decorators.rbac import require_admin
from app.exceptions.forge_error import ForgeError
from app.models.tenancy.user import User
from app.models.tenancy.user_workspace import UserInvitation
from app.routes.request_helpers import extract_workspace_id
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

qf_user_ns = Namespace("users", description="User management operations")
SENSITIVE_USER_FIELDS = {"password", "otp_secret"}
# Define parser globally
qf_user_parser = reqparse.RequestParser()
qf_user_parser.add_argument('status', type=str, default='All', help='Filter by status', action='store', location='args')  # Single value
qf_user_parser.add_argument('cursor', type=str, help='Cursor for pagination (user_id)', location='args')
qf_user_parser.add_argument('limit', type=int, default=10, help='Number of records per page', location='args')
qf_user_parser.add_argument('direction', type=str, default='forward', choices=['forward', 'backward'], help='Pagination direction', location='args')
qf_user_parser.add_argument('q', type=str, location='args')

user_model = qf_user_ns.model('User', {
    'user_id': fields.String(required=True, description='User ID'),
    'username': fields.String(required=True, description='Username'),
    'password': fields.String(required=True, description='Password'),
    'first_name': fields.String(required=True, description='First name'),
    'last_name': fields.String(required=True, description='Last name'),
    'display_name': fields.String(readonly=True, description='Computed display name'),
    'organization': fields.String(description='Organization', default=None),
    'email': fields.String(description='List of emails', default=None),
    'status': fields.String(description='Status', default='New', enum=['New', 'Active', 'Inactive', 'Pending']),
    'tos_accepted': fields.Boolean(description='Terms of service', default=False),
    'eula_accepted': fields.Boolean(description='EULA accepted', default=False),
    'otp_secret': fields.String(description='OTP secret', default=None),
})

mapping_model = qf_user_ns.model('UserWorkspaceMapping', {
    'user_id': fields.String(required=True, description='The ID of the user'),
    'workspace_id': fields.String(required=True, description='The ID of the workspace'),
})

user_role_add_model = qf_user_ns.model(
    "UserRoleAdd",
    {
        "role_name": fields.String(required=True, description="Canonical role name to assign directly to the user"),
    },
)

user_role_replace_model = qf_user_ns.model(
    "UserRoleReplace",
    {
        "role_names": fields.List(fields.String, required=True, description="Complete direct role name list"),
    },
)

user_role_update_model = qf_user_ns.model(
    "UserRoleUpdate",
    {
        "role_name": fields.String(required=True, description="Replacement role name"),
    },
)

pagination_response = qf_user_ns.model('PaginationResponse', {
    'users': fields.List(fields.Nested(user_model)),
    'next_cursor': fields.String(description='Cursor for next page', default=None),
    'prev_cursor': fields.String(description='Cursor for previous page', default=None),
    'total_count': fields.Integer(description='Total number of users'),
})


def _public_user_payload(user: User) -> dict:
    return user.model_dump(mode="json", exclude=SENSITIVE_USER_FIELDS)


@qf_user_ns.route("/")
class UserList(ForgeResource):
    @qf_user_ns.response(201, "User invite created")
    @qf_user_ns.doc(security='BearerAuth')
    @token_required
    @require_admin()
    def post(self):
        """
        Create a user record for an invitation
        """
        try:
            payload = UserInvitation(**request.json)
        except ValidationError as e:
            return {"error": e.errors()}, 400

        userService = UserService()
        result = userService.create_invite(payload)
        return result, 201
    
    @token_required
    @require_admin()
    # @qf_user_ns.marshal_with(pagination_response)
    def get(self):
        """List users with cursor-based pagination"""
        args = qf_user_parser.parse_args()
        workspace_id = (request.headers.get("X-Workspace-Id") or "").strip() or None
        # Super admins see all users across all workspaces
        if "super_admin" in getattr(g, "effective_roles", set()):
            workspace_id = None
        logger.info(f"Parsed args: {args}")  # Debug query parameters
        logger.info(args['status'])
        try:
            user_service = UserService()
            users, next_cursor, prev_cursor, total_count = user_service.get_users(
                status=args['status'],
                cursor=args['cursor'],
                limit=args['limit'],
                direction=args['direction'],
                username=args['q'],
                workspace_id=workspace_id,
            )
            return {
                'users': [_public_user_payload(user) for user in users],
                'next_cursor': next_cursor,
                'prev_cursor': prev_cursor,
                'total_count': total_count
            }, 200
        except Exception as e:
            qf_user_ns.abort(500, f"Error fetching users: {str(e)}")


@qf_user_ns.route("/<string:user_id>")
@qf_user_ns.param("user_id", "The user identifier")
class UserUpdates(ForgeResource):
    @qf_user_ns.response(200, "User updated")
    @qf_user_ns.doc(security='BearerAuth')
    @token_required
    @require_admin()
    def put(self, user_id):
        """
        Update an existing user
        """
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            raise ForgeError("Invalid JSON body", status_code=400)

        user = User(**body)
        userService = UserService()
        result = userService.update_user(
            user_id=user_id,
            update_data=user,
            workspace_id=(request.headers.get("X-Workspace-Id") or "").strip() or None,
        )
        
        return jsonify(_public_user_payload(result))

    @qf_user_ns.response(200, "User deleted")
    @qf_user_ns.doc(security='BearerAuth')
    @token_required
    @require_admin()
    def delete(self, user_id):
        """
        Delete a user
        """
        userService = UserService()
        result = userService.delete_user(user_id)
        return result
    
    # @qf_user_ns.response(200, "Success", user_model)
    # @qf_user_ns.marshal_with(user_model)
    @token_required
    @require_admin()
    def get(self, user_id):
        """
        Get a specific User
        """
        userService = UserService()
        result = userService.get_user(
            user_id,
            workspace_id=(request.headers.get("X-Workspace-Id") or "").strip() or None,
        )
        return jsonify(_public_user_payload(result))
    
    def options(self, user_id):
        return {}, 200

@qf_user_ns.route("/<string:user_id>/workspaces")
class UserWorkspaces(ForgeResource):
    @token_required
    @require_admin()
    def get(self, user_id):
        """
        Get all the workspace organizations for a given user
        """
        userService = UserService()
        results = userService.get_user_workspaces(user_id)
        return results


@qf_user_ns.route("/<string:user_id>/roles")
class UserDirectRoles(ForgeResource):
    @token_required
    @require_admin()
    def get(self, user_id):
        workspace_id = extract_workspace_id()
        user_service = UserService()
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
        user_service = UserService()
        mapping = user_service.add_user_direct_role(user_id, role_name, workspace_id=workspace_id)
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
        user_service = UserService()
        result = user_service.replace_user_direct_roles(user_id, role_names, workspace_id=workspace_id)
        return result, 200


@qf_user_ns.route("/<string:user_id>/roles/<string:role_name>")
class UserDirectRoleById(ForgeResource):
    @token_required
    @require_admin()
    @qf_user_ns.expect(user_role_update_model, validate=False)
    def patch(self, user_id, role_name):
        workspace_id = extract_workspace_id()
        data = request.get_json(silent=True) or {}
        new_role_name = str(data.get("role_name") or "").strip()
        if not new_role_name:
            return {"error": "role_name is required"}, 400
        user_service = UserService()
        result = user_service.update_user_direct_role(
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
        user_service = UserService()
        result = user_service.remove_user_direct_role(user_id, role_name, workspace_id=workspace_id)
        return result, 200

@qf_user_ns.route("/<string:user_id>/workspaces/<string:workspace_id>/dashboards/<string:dashboard_id>/embed")
class UserWorkspaceDashboard(ForgeResource):
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
        """
        Dashboard embedding is temporarily disabled.
        """
        return {"status": "ok"}, 200
    
    def options(self, user_id, workspace_id, dashboard_id):
        return {}, 200

@qf_user_ns.route("/counts")
class UserCounts(ForgeResource):
    @token_required
    @require_admin()
    def get(self):
        user_service = UserService()
        results = user_service.get_counts(
            workspace_id=(request.headers.get("X-Workspace-Id") or "").strip() or None,
        )

        return results, 200

@qf_user_ns.route("/resend-invite")
class ResentInvite(ForgeResource):
    @token_required
    @require_admin()
    def post(self):
        try:
            payload = UserInvitation(**request.json)
        except ValidationError as e:
            return {"error": e.errors()}, 400
        
        user_service = UserService()
        user_service.resend_invite(payload.user_id, payload.email)

@qf_user_ns.route("/bulk-invite")
class BulkInviteUsers(ForgeResource):
    @token_required
    @require_admin()
    def post(self):
        data = request.json

        service = UserService()
        return service.create_invite_bulk(data["emails"], data["workspaces"])
        
