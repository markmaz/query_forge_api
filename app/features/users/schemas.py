from __future__ import annotations

from flask_restx import Namespace, fields, reqparse


def _register_model(namespace: Namespace, name: str, model_spec: dict):
    existing = namespace.models.get(name)
    if existing is not None:
        return existing
    return namespace.model(name, model_spec)


def build_user_parser() -> reqparse.RequestParser:
    parser = reqparse.RequestParser()
    parser.add_argument("status", type=str, default="All", help="Filter by status", action="store", location="args")
    parser.add_argument("cursor", type=str, help="Cursor for pagination (user_id)", location="args")
    parser.add_argument("limit", type=int, default=10, help="Number of records per page", location="args")
    parser.add_argument("direction", type=str, default="forward", choices=["forward", "backward"], help="Pagination direction", location="args")
    parser.add_argument("q", type=str, location="args")
    return parser


def build_user_workspace_parser() -> reqparse.RequestParser:
    parser = reqparse.RequestParser()
    parser.add_argument("user_id", type=str, required=True, help="The user id", location="args")
    parser.add_argument("workspace_id", type=str, required=True, help="The workspace id", location="args")
    return parser


def register_user_models(namespace: Namespace) -> dict[str, object]:
    user_model = _register_model(
        namespace,
        "User",
        {
            "user_id": fields.String(required=True, description="User ID"),
            "username": fields.String(required=True, description="Username"),
            "password": fields.String(required=True, description="Password"),
            "first_name": fields.String(required=True, description="First name"),
            "last_name": fields.String(required=True, description="Last name"),
            "display_name": fields.String(readonly=True, description="Computed display name"),
            "organization": fields.String(description="Organization", default=None),
            "email": fields.String(description="List of emails", default=None),
            "status": fields.String(description="Status", default="New", enum=["New", "Active", "Inactive", "Pending"]),
            "tos_accepted": fields.Boolean(description="Terms of service", default=False),
            "eula_accepted": fields.Boolean(description="EULA accepted", default=False),
            "otp_secret": fields.String(description="OTP secret", default=None),
        },
    )
    mapping_model = _register_model(
        namespace,
        "UserWorkspaceMapping",
        {
            "user_id": fields.String(required=True, description="The ID of the user"),
            "workspace_id": fields.String(required=True, description="The ID of the workspace"),
        },
    )
    user_role_add_model = _register_model(
        namespace,
        "UserRoleAdd",
        {"role_name": fields.String(required=True, description="Canonical role name to assign directly to the user")},
    )
    user_role_replace_model = _register_model(
        namespace,
        "UserRoleReplace",
        {"role_names": fields.List(fields.String, required=True, description="Complete direct role name list")},
    )
    user_role_update_model = _register_model(
        namespace,
        "UserRoleUpdate",
        {"role_name": fields.String(required=True, description="Replacement role name")},
    )
    pagination_response = _register_model(
        namespace,
        "PaginationResponse",
        {
            "users": fields.List(fields.Nested(user_model)),
            "next_cursor": fields.String(description="Cursor for next page", default=None),
            "prev_cursor": fields.String(description="Cursor for previous page", default=None),
            "total_count": fields.Integer(description="Total number of users"),
        },
    )
    return {
        "user_model": user_model,
        "mapping_model": mapping_model,
        "user_role_add_model": user_role_add_model,
        "user_role_replace_model": user_role_replace_model,
        "user_role_update_model": user_role_update_model,
        "pagination_response": pagination_response,
    }


def register_user_workspace_models(namespace: Namespace) -> dict[str, object]:
    mapping_model = _register_model(
        namespace,
        "UserWorkspaceMappingDetail",
        {
            "user_id": fields.String(required=True, description="The ID of the user"),
            "workspace_id": fields.String(required=True, description="The ID of the workspace"),
            "is_default": fields.Boolean(required=False, description="Is this the default workspace for the user."),
        },
    )
    connection_response = _register_model(
        namespace,
        "ConnectionResponse",
        {"message": fields.String(description="Success or error message")},
    )
    return {"mapping_model": mapping_model, "connection_response": connection_response}


def register_role_models(namespace: Namespace) -> dict[str, object]:
    role_model = _register_model(
        namespace,
        "role",
        {
            "role_name": fields.String(required=True, description="Canonical role name"),
            "display_name": fields.String(required=False, description="Human readable role name"),
            "description": fields.String(required=False, description="Role description"),
            "feature_key": fields.String(required=False, description="Owning feature key"),
            "is_system": fields.Boolean(required=False, description="True for system-managed roles"),
        },
    )
    roles = _register_model(namespace, "role_list", {"roles": fields.List(fields.Nested(role_model))})
    return {"role_model": role_model, "roles": roles}
