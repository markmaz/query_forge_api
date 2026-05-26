from __future__ import annotations

from flask import g, request
from flask_restx import Namespace, Resource, fields

from app.api_config import NAME, VERSION, build_url
from app.decorators.rbac import require_admin
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.services.mcp_oauth import MCP_APP_PRINCIPAL_ALLOWED_TOOLS, MCPAppPrincipalService

mcp_app_principals_ns = Namespace(
    "mcp-app-principals",
    description=(
        "Workspace-admin API for non-human QueryForge MCP app principals. "
        "These endpoints create OAuth client_credentials credentials and the explicit "
        "workspace grant rows required by the MCP runtime."
    ),
)

_grant_model = mcp_app_principals_ns.model(
    "MCPAppPrincipalGrant",
    {
        "enabled": fields.Boolean(required=True, description="Whether the app principal grant is active."),
        "allowed_tools": fields.List(
            fields.String,
            required=True,
            description="Allowed MCP tool names. An empty list means all currently supported MCP tools.",
            example=["search_domains", "plan_query", "preview_query"],
        ),
        "allowed_domain_keys": fields.List(
            fields.String,
            required=True,
            description="Allowed domain keys. An empty list means all domains visible to the workspace grant.",
            example=["attendance", "students"],
        ),
        "can_preview": fields.Boolean(required=True, description="Whether preview execution tools can return rows."),
        "preview_row_limit": fields.Integer(required=True, description="Maximum preview rows allowed for this principal."),
        "expires_at": fields.String(required=False, description="Grant expiration timestamp, or null."),
        "revoked_at": fields.String(required=False, description="Grant revocation timestamp, or null."),
        "updated_at": fields.String(required=False, description="Last grant update timestamp, or null."),
    },
)

_principal_model = mcp_app_principals_ns.model(
    "MCPAppPrincipal",
    {
        "client_id": fields.String(required=True, description="OAuth client id used with the client_credentials grant."),
        "display_name": fields.String(required=True, description="Human-readable principal name."),
        "description": fields.String(required=False, description="Operational description for admins."),
        "owning_workspace_id": fields.String(required=True, description="Workspace that owns this principal."),
        "owner_user_id": fields.String(required=False, description="Optional user owner for operational accountability."),
        "created_by": fields.String(required=False, description="User id that created the principal."),
        "created_at": fields.String(required=False, description="Creation timestamp."),
        "last_used_at": fields.String(required=False, description="Most recent successful token exchange timestamp."),
        "expires_at": fields.String(required=False, description="Client expiration timestamp, or null."),
        "revoked_at": fields.String(required=False, description="Client revocation timestamp, or null."),
        "rotation_required_at": fields.String(required=False, description="Secret rotation deadline, or null."),
        "grant": fields.Nested(_grant_model, required=True, description="Workspace grant enforced by MCP runtime."),
    },
)

_list_model = mcp_app_principals_ns.model(
    "MCPAppPrincipalListResponse",
    {
        "workspace_id": fields.String(required=True),
        "items": fields.List(fields.Nested(_principal_model), required=True),
    },
)

_create_request_model = mcp_app_principals_ns.model(
    "MCPAppPrincipalCreateRequest",
    {
        "display_name": fields.String(required=True, description="Human-readable app principal name.", example="District SIS Agent"),
        "description": fields.String(required=False, description="Operational description shown to workspace admins."),
        "owner_user_id": fields.String(required=False, description="Optional QueryForge user id accountable for this app principal."),
        "allowed_tools": fields.List(
            fields.String,
            required=False,
            description=(
                "Allowed MCP tools. Omit or send an empty list for all supported tools. "
                f"Supported values: {', '.join(MCP_APP_PRINCIPAL_ALLOWED_TOOLS)}."
            ),
            example=["search_domains", "plan_query", "preview_query"],
        ),
        "allowed_domain_keys": fields.List(
            fields.String,
            required=False,
            description="Optional domain-key allow-list. Omit or send an empty list for all domains visible to the grant.",
            example=["attendance"],
        ),
        "can_preview": fields.Boolean(
            required=False,
            description="Whether this app principal can call preview tools. Defaults to false.",
            example=True,
        ),
        "preview_row_limit": fields.Integer(
            required=False,
            description="Preview row cap for this app principal. Must be between 1 and 500. Defaults to 100.",
            example=100,
        ),
        "expires_at": fields.String(
            required=False,
            description="Optional client and grant expiration timestamp accepted by MySQL.",
            example="2026-12-31 23:59:59",
        ),
    },
)

_create_response_model = mcp_app_principals_ns.model(
    "MCPAppPrincipalCreateResponse",
    {
        "workspace_id": fields.String(required=True),
        "client_secret": fields.String(
            required=True,
            description="One-time plaintext client secret. Store it immediately; QueryForge only persists the SHA-256 hash.",
        ),
        "item": fields.Nested(_principal_model, required=True),
    },
)

_revoke_response_model = mcp_app_principals_ns.model(
    "MCPAppPrincipalRevokeResponse",
    {
        "workspace_id": fields.String(required=True),
        "item": fields.Nested(_principal_model, required=True),
    },
)


def _service() -> MCPAppPrincipalService:
    return MCPAppPrincipalService()


def _assert_workspace_context(workspace_id: str) -> None:
    header_workspace = str(getattr(g, "workspace_id", "") or "").strip()
    if header_workspace and header_workspace != str(workspace_id or "").strip():
        raise ForgeError("Workspace route does not match X-Workspace-Id.", status_code=400)


@mcp_app_principals_ns.route("/<string:workspace_id>/mcp/app-principals")
@mcp_app_principals_ns.param("workspace_id", "Workspace id that owns the MCP app principal records.")
class MCPAppPrincipalCollection(Resource):
    @mcp_app_principals_ns.doc(
        summary="List MCP app principals for a workspace",
        description=(
            "Returns non-human MCP app principals owned by the workspace and the explicit app grant "
            "used by the MCP runtime. Client secrets and secret hashes are never returned."
        ),
        responses={
            200: "Workspace app principals returned.",
            401: "Authentication required.",
            403: "Workspace admin access required.",
        },
    )
    @mcp_app_principals_ns.marshal_with(_list_model, code=200)
    @token_required
    @require_admin()
    def get(self, workspace_id: str):
        try:
            _assert_workspace_context(workspace_id)
            return _service().list_principals(workspace_id=workspace_id), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @mcp_app_principals_ns.doc(
        summary="Create an MCP app principal and workspace grant",
        description=(
            "Creates an OAuth client_credentials principal for server-to-server MCP access. "
            "The response includes the plaintext client secret exactly once; admins must copy it "
            "before leaving the screen. The created grant is workspace-scoped and may be narrowed "
            "by allowed tools and domain keys."
        ),
        responses={
            201: "App principal created and secret returned once.",
            400: "Invalid display name, preview limit, workspace context, or unsupported tool.",
            401: "Authentication required.",
            403: "Workspace admin access required.",
        },
    )
    @mcp_app_principals_ns.expect(_create_request_model, validate=False)
    @mcp_app_principals_ns.marshal_with(_create_response_model, code=201)
    @token_required
    @require_admin()
    def post(self, workspace_id: str):
        try:
            _assert_workspace_context(workspace_id)
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_principal(
                    workspace_id=workspace_id,
                    actor_user_id=str(getattr(g, "user_id", "") or ""),
                    payload=payload,
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@mcp_app_principals_ns.route("/<string:workspace_id>/mcp/app-principals/<string:client_id>")
@mcp_app_principals_ns.param("workspace_id", "Workspace id that owns the MCP app principal record.")
@mcp_app_principals_ns.param("client_id", "OAuth client id for the MCP app principal.")
class MCPAppPrincipalItem(Resource):
    @mcp_app_principals_ns.doc(
        summary="Revoke an MCP app principal",
        description=(
            "Revokes the app client and disables its workspace grant. Existing short-lived MCP access "
            "tokens may remain valid until expiry; future client_credentials exchanges and runtime grant "
            "checks are blocked."
        ),
        responses={
            200: "App principal revoked.",
            401: "Authentication required.",
            403: "Workspace admin access required.",
            404: "App principal not found in this workspace.",
        },
    )
    @mcp_app_principals_ns.marshal_with(_revoke_response_model, code=200)
    @token_required
    @require_admin()
    def delete(self, workspace_id: str, client_id: str):
        try:
            _assert_workspace_context(workspace_id)
            return _service().revoke_principal(workspace_id=workspace_id, client_id=client_id), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


def register(api) -> None:
    api.add_namespace(mcp_app_principals_ns, path=build_url("/", NAME, VERSION, "workspaces"))


__all__ = ["mcp_app_principals_ns", "register"]
