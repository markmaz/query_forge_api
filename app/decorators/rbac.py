"""
app/decorators/rbac.py

RBAC decorators for QueryForge route protection.

Usage:

    from app.decorators.security import token_required
    from app.decorators.rbac import require_feature, require_role

    @token_required
    @require_feature("forge_match")
    @require_role("forge_match:user")
    def my_route():
        ...

Decorator order matters:
  1. @token_required  — must be outermost, sets g.user_id and g.workspace_id
  2. @require_feature — checks workspace entitlement
  3. @require_role    — checks user role

Shortcut for the common case:

    @token_required
    @require_access("forge_match", role="user")
    def my_route():
        ...

super_admin bypasses all checks.
workspace_admin bypasses feature checks and implies all feature:user roles.

g.effective_roles is populated lazily on first access per request.
g.workspace_id must be set by @token_required (via X-Workspace-Id header).
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import g
from flask_restx import abort

from app.services.rbac_service import workspace_has_feature

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal: load roles once per request
# ---------------------------------------------------------------------------


def _ensure_roles_loaded() -> None:
    """
    Load effective roles into g.effective_roles if not already done.
    Called lazily by decorators so token_required stays unchanged.
    """
    if not hasattr(g, "effective_roles"):
        from app.services.rbac_service import get_effective_roles
        user_id = getattr(g, "user_id", None)
        if user_id:
            g.effective_roles = get_effective_roles(user_id)
        else:
            g.effective_roles = set()


def _is_super_admin() -> bool:
    _ensure_roles_loaded()
    return "super_admin" in g.effective_roles


def _is_workspace_admin() -> bool:
    _ensure_roles_loaded()
    return "workspace_admin" in g.effective_roles


# ---------------------------------------------------------------------------
# @require_feature
# ---------------------------------------------------------------------------


def require_feature(feature_key: str):
    """
    Decorator: require the current workspace to have feature_key active.

    Bypassed for super_admin and workspace_admin.
    Reads workspace_id from g (set by token_required via X-Workspace-Id header).

    Returns 403 if feature is not active for the workspace.
    Returns 503 if workspace_id is not available (misconfigured route).
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Global admins bypass feature checks
            if _is_super_admin() or _is_workspace_admin():
                return fn(*args, **kwargs)

            workspace_id = getattr(g, "workspace_id", None)
            if not workspace_id:
                logger.error(
                    "require_feature(%r) called but g.workspace_id is not set. "
                    "Ensure workspace_id is resolved before this decorator.",
                    feature_key,
                )
                abort(503, "Workspace context not available.")

            if not workspace_has_feature(workspace_id, feature_key):
                abort(403, f"Feature '{feature_key}' is not enabled for this workspace.")

            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# @require_role
# ---------------------------------------------------------------------------


def require_role(*role_names: str):
    """
    Decorator: require the current user to have at least one of the
    specified roles (effective roles, including implied roles).

    Bypassed for super_admin.

    Usage:
        @require_role("forge_match:user")           # single role
        @require_role("forge_match:admin", "super_admin")  # any of these

    Returns 403 if the user has none of the required roles.
    Returns 401 if no user is authenticated.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not getattr(g, "user_id", None):
                abort(401, "Authentication required.")

            if _is_super_admin():
                return fn(*args, **kwargs)

            _ensure_roles_loaded()
            if not any(r in g.effective_roles for r in role_names):
                required = " or ".join(f"'{r}'" for r in role_names)
                abort(403, f"Required role: {required}.")

            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# @require_access — convenience shortcut
# ---------------------------------------------------------------------------


def require_access(feature_key: str, role: str = "user"):
    """
    Shortcut combining require_feature + require_role for the common case.

    @require_access("forge_match")              → checks feature + forge_match:user
    @require_access("forge_match", role="admin") → checks feature + forge_match:admin

    Equivalent to:
        @require_feature("forge_match")
        @require_role("forge_match:user")
    """
    full_role = f"{feature_key}:{role}"

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Feature check (bypassed for super_admin / workspace_admin)
            if not _is_super_admin() and not _is_workspace_admin():
                workspace_id = getattr(g, "workspace_id", None)
                if workspace_id:
                    if not workspace_has_feature(workspace_id, feature_key):
                        abort(403, f"Feature '{feature_key}' is not enabled for this workspace.")

            # Role check (bypassed for super_admin only)
            if not _is_super_admin():
                _ensure_roles_loaded()
                if full_role not in g.effective_roles:
                    abort(403, f"Required role: '{full_role}'.")

            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# @public — marks a route as intentionally unauthenticated
# ---------------------------------------------------------------------------


def public(fn):
    """
    Marks a route as intentionally public — no authentication required.
    Documentation only — no runtime effect.
    """
    fn._is_public = True
    return fn


# ---------------------------------------------------------------------------
# @require_admin — convenience for workspace_admin or super_admin
# ---------------------------------------------------------------------------


def require_admin():
    """
    Require workspace_admin or super_admin.
    Use for workspace management routes that don't belong to a specific feature.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not getattr(g, "user_id", None):
                abort(401, "Authentication required.")
            _ensure_roles_loaded()
            if not (_is_super_admin() or _is_workspace_admin()):
                abort(403, "Workspace admin access required.")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
