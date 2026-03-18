"""
app/decorators/ownership.py

Ownership and sharing decorator for QueryForge route protection.

Usage:

    # Shared read, owned write (saved queries)
    @token_required
    @require_access("query_studio")
    @require_ownership("SavedQuery", "query_id", "query_studio:admin")
    def put(self, query_id):
        query = g.owned_object   # already loaded — no extra DB call
        ...

    # Private read + write (skills, unless shared)
    @token_required
    @require_access("skills")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    def get(self, skill_id):
        skill = g.owned_object
        ...

Decorator stores loaded object in g.owned_object — route handler
uses it without a second DB query.

For shared objects (check_read=False, default):
  GET  → allowed if is_shared=True or owner or admin
  POST/PUT/PATCH/DELETE → owner or admin only

For private objects (check_read=True):
  ALL methods → owner or admin only (unless is_shared=True)

Seam notes:
  SavedQuery — app.models.query.saved_query (minimal ownership read model)
  QuerySkill — app.models.query.skills
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import g, request
from flask_restx import abort

logger = logging.getLogger(__name__)

# Model registry — maps string names to (module_path, class_name)
_MODEL_REGISTRY: dict[str, tuple[str, str]] = {
    "SavedQuery": ("app.models.query.saved_query", "SavedQuery"),
    "QuerySkill": ("app.models.query.skills", "QuerySkill"),
}


def _load_model(model_name: str, object_id: str, workspace_id: str):
    if model_name not in _MODEL_REGISTRY:
        raise ValueError(
            f"Unknown model: {model_name!r}. "
            f"Add to _MODEL_REGISTRY in app/decorators/ownership.py"
        )
    module_path, class_name = _MODEL_REGISTRY[model_name]
    import importlib
    cls = getattr(importlib.import_module(module_path), class_name)
    return cls.query.filter_by(id=object_id, workspace_id=workspace_id).first()


def require_ownership(
    model: str,
    id_param: str,
    admin_role: str,
    check_read: bool = False,
):
    """
    Check ownership or sharing before allowing access.

    Args:
        model:      Key in _MODEL_REGISTRY (e.g. "SavedQuery")
        id_param:   URL kwarg name for the object ID (e.g. "query_id")
        admin_role: Role that overrides ownership (e.g. "query_studio:admin")
        check_read: If True, ownership/sharing checked on GET too (private objects).
                    If False (default), GET is allowed when is_shared=True (shared objects).

    Stores loaded object in g.owned_object.
    Returns 403 if access denied, 404 if object not found.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = getattr(g, "user_id", None)
            workspace_id = getattr(g, "workspace_id", None)

            if not user_id:
                abort(401, "Authentication required.")
            if not workspace_id:
                abort(503, "Workspace context not available.")

            object_id = kwargs.get(id_param)
            if object_id is None:
                abort(500, f"Route misconfiguration: id_param {id_param!r} not found.")

            obj = _load_model(model, object_id, workspace_id)
            if obj is None:
                abort(404, "Object not found.")

            g.owned_object = obj

            # Global admins bypass all ownership checks
            effective_roles = getattr(g, "effective_roles", set())
            if "super_admin" in effective_roles or "workspace_admin" in effective_roles:
                return fn(*args, **kwargs)

            is_shared = bool(getattr(obj, "is_shared", False))
            created_by = getattr(obj, "created_by", None)
            is_get = request.method == "GET"

            # For shared objects, GET is always allowed when is_shared=True
            if not check_read and is_get and is_shared:
                return fn(*args, **kwargs)

            from app.services.ownership_service import can_read_object, can_modify_object

            if is_get and not check_read:
                # Shared object read path — allow if shared, owned, or admin
                allowed = can_read_object(created_by, is_shared, user_id, admin_role, workspace_id)
            elif is_get and check_read:
                # Private object read path — same rules as modify
                allowed = can_read_object(created_by, is_shared, user_id, admin_role, workspace_id)
            else:
                # All write operations — sharing grants no write access
                allowed = can_modify_object(created_by, user_id, admin_role, workspace_id)

            if not allowed:
                abort(403, "You do not have permission to perform this action.")

            return fn(*args, **kwargs)
        return wrapper
    return decorator
