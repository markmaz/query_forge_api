import functools
from typing import Any, Dict, Tuple

from flask import g, make_response, request

from app.exceptions.service_error import ServiceError
from app.services.auth_service import AuthService

auth_service = AuthService()


def _extract_user_context(payload: Dict[str, Any]) -> Tuple[str, str, bool]:
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

    # Admin
    is_admin = bool(payload.get("is_admin") or payload.get("admin"))

    roles = payload.get("roles")
    if isinstance(roles, list) and any(str(r).lower() == "admin" for r in roles):
        is_admin = True

    groups = payload.get("groups")
    if isinstance(groups, list) and any(str(gr).lower() == "admin" for gr in groups):
        is_admin = True

    return str(user_id or "").strip(), str(display_name or "").strip(), is_admin


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
                raise ServiceError("Token is not formatted correctly", status_code=403)

        if not token:
            raise ServiceError("Token is missing", 403)

        payload = auth_service.verify_token(token)
        if not payload:
            raise ServiceError("Invalid or expired token!", 401)

        # Store full payload for backward compatibility
        g.user_data = payload

        # Store normalized user context for services
        user_id, display_name, is_admin = _extract_user_context(payload)
        if not user_id:
            raise ServiceError("Invalid token payload: missing user identity", status_code=401)

        g.user_id = user_id
        g.user_display_name = display_name
        g.is_admin = is_admin

        return f(*args, **kwargs)

    return decorated_function