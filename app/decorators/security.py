import functools
from typing import Any, Dict, List, Tuple

from flask import g, make_response, request

from app.exceptions.forge_error import ForgeError
from app.services.auth_service import AuthService
from app.services.workspace_access_service import WorkspaceAccessService
from app.utils.jwt_claims import claim_is_admin, get_roles_from_claim

auth_service = AuthService()
workspace_access_service = WorkspaceAccessService()


def _extract_user_context(payload: Dict[str, Any]) -> Tuple[str, str, bool, List[str]]:
    # Identity
    user_id = (
        payload.get("user_id")
        or payload.get("uid")
        or payload.get("sub")
        or payload.get("username")
        or payload.get("email")
    )

    display_name = (
        payload.get("display_name")
        or payload.get("name")
        or payload.get("preferred_username")
        or payload.get("username")
        or payload.get("email")
        or user_id
    )

    roles = get_roles_from_claim(payload)
    is_admin = claim_is_admin(payload)

    return str(user_id or "").strip(), str(display_name or "").strip(), is_admin, roles


def token_required(f):
    """Ensures methods that need to be secured are called with the proper tokens."""

    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == "OPTIONS":
            response = make_response()
            response.headers.add("Access-Control-Allow-Origin", "*")
            response.headers.add("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            # Include X-Workspace-ID since this app uses it.
            response.headers.add("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Workspace-ID")
            response.headers.add("Access-Control-Allow-Credentials", "true")
            return response, 200

        token = None

        if "Authorization" in request.headers:
            parts = request.headers["Authorization"].split(" ")
            if len(parts) > 1:
                token = parts[1]  # Extract the bearer token
            else:
                raise ForgeError("Token is not formatted correctly", status_code=403)

        if not token:
            raise ForgeError("Token is missing", 403)

        payload = auth_service.verify_token(token)
        if not payload:
            raise ForgeError("Invalid or expired token!", 401)

        # Store full payload for backward compatibility
        g.user_data = payload

        # Store normalized user context for services
        user_id, display_name, is_admin, roles = _extract_user_context(payload)
        if not user_id:
            raise ForgeError("Invalid token payload: missing user identity", status_code=401)

        g.user_id = user_id
        g.user_display_name = display_name
        g.is_admin = is_admin
        g.user_roles = roles

        workspace_id = (request.headers.get("X-Workspace-Id") or "").strip()
        if workspace_id:
            workspace_access_service.assert_workspace_access(
                user_id=user_id,
                workspace_id=workspace_id,
            )
        g.workspace_id = workspace_id or None

        # Pre-load effective roles — graceful: falls back to empty set on any error
        # (e.g., DB unavailable, tables not yet migrated in test env)
        try:
            from app.services.rbac_service import get_effective_roles
            g.effective_roles = get_effective_roles(user_id)
            # Backwards compat: token-level is_admin maps to super_admin when
            # DB has no RBAC rows yet (e.g. pre-migration or test environments)
            if is_admin and not g.effective_roles:
                g.effective_roles = {"super_admin"}
            # Maintain backwards compat: g.is_admin also true if DB roles say so
            g.is_admin = is_admin or (
                "super_admin" in g.effective_roles
                or "workspace_admin" in g.effective_roles
            )
        except Exception:
            # DB unavailable — fall back gracefully, preserving token-level claim
            g.effective_roles = {"super_admin"} if is_admin else set()
            g.is_admin = is_admin

        return f(*args, **kwargs)

    return decorated_function
