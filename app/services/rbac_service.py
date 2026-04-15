"""
app/services/rbac_service.py

Role resolution service for QueryForge RBAC.

Responsibilities:
  - Load and cache user roles (Valkey, 60s TTL)
  - Resolve effective permissions including implied roles
  - Invalidate cache on role change
  - Check feature entitlements (workspace_features table, Valkey cached)

Resolution rules:
  super_admin       → has_role() always True, has_feature() always True
  workspace_admin   → has_feature() always True + implies all feature :user roles
  feature:admin     → implies feature:user for the same feature
  feature:user      → explicit access only

Seam notes:
  user_id      — str (matches users.user_id VARCHAR PK)
  workspace_id — str (matches workspace.id VARCHAR PK)
  Valkey       — valkey.Valkey(...) matching app/skills/schedule_utils.py pattern
  DB queries   — db.session.query(Model) not Model.query (custom _DB shim)
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, or_, text
from valkey.exceptions import ValkeyError

from app.models.rbac import FEATURE_KEYS, GLOBAL_ROLES, ROLE_DEFINITIONS, Role, UserRole, WorkspaceFeature

logger = logging.getLogger(__name__)

ROLE_CACHE_TTL = 60       # seconds
FEATURE_CACHE_TTL = 120   # seconds — entitlements change less often
ROLE_CACHE_PREFIX = "qf:roles:user:"
FEATURE_CACHE_PREFIX = "qf:features:workspace:"
CACHE_BACKEND_ERRORS = (OSError, ValkeyError)


def _role_cache_key(user_id: str, workspace_id: str | None) -> str:
    scope = str(workspace_id or "__global__").strip() or "__global__"
    return f"{ROLE_CACHE_PREFIX}{user_id}:{scope}"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _valkey():
    import valkey
    from app.config import VALKEY_ADDRESS, VALKEY_PORT
    return valkey.Valkey(
        host=str(VALKEY_ADDRESS or "localhost"),
        port=int(VALKEY_PORT or 6379),
        db=0,
        decode_responses=True,
        socket_timeout=1.0,
    )


# ---------------------------------------------------------------------------
# Role loading
# ---------------------------------------------------------------------------


def get_user_roles(user_id: str, workspace_id: str | None = None) -> set[str]:
    """
    Return the set of role names assigned to a user.
    Cached in Valkey for ROLE_CACHE_TTL seconds.
    """
    cache_key = _role_cache_key(user_id, workspace_id)

    try:
        client = _valkey()
        cached = client.smembers(cache_key)
        if cached:
            return set(cached)
    except CACHE_BACKEND_ERRORS as exc:
        logger.debug("Role cache read failed (non-fatal): %s", exc)

    query = (
        UserRole.query.join(Role)
        .filter(UserRole.user_id == user_id)
    )
    if workspace_id:
        query = query.filter(
            or_(
                UserRole.workspace_id == workspace_id,
                and_(UserRole.workspace_id.is_(None), Role.name == "super_admin"),
            )
        )
    else:
        query = query.filter(
            and_(UserRole.workspace_id.is_(None), Role.name == "super_admin")
        )

    rows = query.all()
    roles = {r.role.name for r in rows if r.role}

    try:
        client = _valkey()
        if roles:
            client.sadd(cache_key, *roles)
        else:
            # Cache empty set with a placeholder so we don't hit DB again
            client.sadd(cache_key, "__empty__")
        client.expire(cache_key, ROLE_CACHE_TTL)
    except CACHE_BACKEND_ERRORS as exc:
        logger.debug("Role cache write failed (non-fatal): %s", exc)

    return roles


def invalidate_user_roles(user_id: str, workspace_id: str | None = None) -> None:
    """Call after any role assignment or revocation."""
    try:
        client = _valkey()
        if workspace_id:
            client.delete(_role_cache_key(user_id, workspace_id))
        pattern = f"{ROLE_CACHE_PREFIX}{user_id}:*"
        keys = list(client.keys(pattern))
        if keys:
            client.delete(*keys)
    except CACHE_BACKEND_ERRORS as exc:
        logger.debug("Role cache invalidation failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------


def get_effective_roles(user_id: str, workspace_id: str | None = None) -> set[str]:
    """
    Return the full set of effective role names for a user,
    including implied roles.

    Implied roles:
      workspace_admin  → adds all feature:user roles
      feature:admin    → adds feature:user for the same feature
    """
    assigned = get_user_roles(user_id, workspace_id=workspace_id)
    # Remove placeholder
    assigned.discard("__empty__")

    effective = set(assigned)

    if "super_admin" in assigned:
        # super_admin effectively has everything — add all roles
        for fk in FEATURE_KEYS:
            effective.add(f"{fk}:admin")
            effective.add(f"{fk}:user")
        effective.add("workspace_admin")
        return effective

    if "workspace_admin" in assigned and workspace_id:
        # workspace_admin implies all feature :user roles only inside its workspace
        for fk in FEATURE_KEYS:
            effective.add(f"{fk}:user")

    if "library_admin" in assigned:
        effective.add("query_studio:user")

    # feature:admin implies feature:user
    for fk in FEATURE_KEYS:
        if f"{fk}:admin" in assigned:
            effective.add(f"{fk}:user")

    return effective


def user_has_role(user_id: str, role_name: str, workspace_id: str | None = None) -> bool:
    """Check whether a user has an effective role."""
    return role_name in get_effective_roles(user_id, workspace_id=workspace_id)


# ---------------------------------------------------------------------------
# Feature entitlement
# ---------------------------------------------------------------------------


def get_workspace_features(workspace_id: str) -> set[str]:
    """
    Return the set of active feature keys for a workspace.
    Cached in Valkey for FEATURE_CACHE_TTL seconds.
    """
    cache_key = f"{FEATURE_CACHE_PREFIX}{workspace_id}"

    try:
        cached = _valkey().smembers(cache_key)
        if cached:
            features = set(cached)
            features.discard("__empty__")
            return features
    except CACHE_BACKEND_ERRORS as exc:
        logger.debug("Feature cache read failed (non-fatal): %s", exc)

    rows = WorkspaceFeature.query.filter_by(
        workspace_id=workspace_id, is_active=True
    ).all()
    features = {r.feature_key for r in rows}

    try:
        client = _valkey()
        if features:
            client.sadd(cache_key, *features)
        else:
            client.sadd(cache_key, "__empty__")
        client.expire(cache_key, FEATURE_CACHE_TTL)
    except CACHE_BACKEND_ERRORS as exc:
        logger.debug("Feature cache write failed (non-fatal): %s", exc)

    return features


def invalidate_workspace_features(workspace_id: str) -> None:
    """Call after any workspace feature entitlement change."""
    try:
        _valkey().delete(f"{FEATURE_CACHE_PREFIX}{workspace_id}")
    except CACHE_BACKEND_ERRORS as exc:
        logger.debug("Feature cache invalidation failed (non-fatal): %s", exc)


def workspace_has_feature(workspace_id: str, feature_key: str) -> bool:
    return feature_key in get_workspace_features(workspace_id)


# ---------------------------------------------------------------------------
# Bulk helpers (used by admin UI and role assignment API)
# ---------------------------------------------------------------------------


def assign_role(
    user_id: str,
    role_name: str,
    granted_by: str,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """
    Assign a role to a user. Invalidates cache.
    Returns the created UserRole dict or existing if already assigned.
    """
    from app.extensions import db
    from app.models.rbac import Role, UserRole

    role = Role.get_by_name(role_name)
    if not role:
        raise ValueError(f"Unknown role: {role_name!r}")

    request_workspace_id = str(workspace_id or "").strip() or None
    normalized_workspace_id = request_workspace_id
    if role_name in GLOBAL_ROLES:
        normalized_workspace_id = None
    elif not normalized_workspace_id:
        raise ValueError("workspace_id is required for non-global roles.")

    existing = db.session.query(UserRole).filter_by(
        user_id=user_id,
        workspace_id=normalized_workspace_id,
        role_id=role.id,
    ).first()
    if existing:
        return existing.to_dict()

    ur = UserRole(
        user_id=user_id,
        workspace_id=normalized_workspace_id,
        role_id=role.id,
        granted_by=granted_by,
    )
    db.session.add(ur)
    _ensure_workspace_membership_for_role(
        user_id=user_id,
        role_name=role_name,
        workspace_id=request_workspace_id,
    )
    db.session.commit()
    invalidate_user_roles(user_id, workspace_id=normalized_workspace_id)
    return ur.to_dict()


def _ensure_workspace_membership_for_role(
    *,
    user_id: str,
    role_name: str,
    workspace_id: str | None,
) -> None:
    """
    Keep workspace_membership aligned with workspace-scoped RBAC assignments.

    - workspace_admin => ensure membership.role = 'admin'
    - feature/global assignments made in a workspace context => ensure active
      membership exists, preserving any existing 'admin' role/default flag.
    """
    from app.extensions import db

    normalized_workspace_id = str(workspace_id or "").strip() or None
    if not normalized_workspace_id:
        return

    membership_role = "admin" if role_name == "workspace_admin" else "member"
    existing = db.session.execute(
        text(
            """
            SELECT id, role
            FROM workspace_membership
            WHERE user_id = :user_id
              AND workspace_id = :workspace_id
            LIMIT 1
            """
        ),
        {"user_id": user_id, "workspace_id": normalized_workspace_id},
    ).mappings().first()

    if existing:
        params: dict[str, Any] = {
            "membership_id": existing["id"],
            "role": membership_role,
        }
        if str(existing.get("role") or "").strip().lower() == "admin":
            params["role"] = "admin"
        db.session.execute(
            text(
                """
                UPDATE workspace_membership
                SET role = :role,
                    is_active = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :membership_id
                """
            ),
            params,
        )
        return

    existing_membership_count = db.session.execute(
        text(
            """
            SELECT COUNT(*) AS count
            FROM workspace_membership
            WHERE user_id = :user_id
              AND COALESCE(is_active, 1) = 1
            """
        ),
        {"user_id": user_id},
    ).scalar_one()

    db.session.execute(
        text(
            """
            INSERT INTO workspace_membership (workspace_id, user_id, role, is_active, is_default)
            VALUES (:workspace_id, :user_id, :role, 1, :is_default)
            """
        ),
        {
            "workspace_id": normalized_workspace_id,
            "user_id": user_id,
            "role": membership_role,
            "is_default": 1 if int(existing_membership_count or 0) == 0 else 0,
        },
    )


def revoke_role(user_id: str, role_name: str, workspace_id: str | None = None) -> bool:
    """
    Revoke a role from a user. Invalidates cache.
    Returns True if removed, False if not assigned.
    """
    from app.extensions import db
    from app.models.rbac import Role, UserRole

    role = Role.get_by_name(role_name)
    if not role:
        raise ValueError(f"Unknown role: {role_name!r}")

    normalized_workspace_id = str(workspace_id or "").strip() or None
    if role_name in GLOBAL_ROLES:
        normalized_workspace_id = None
    elif not normalized_workspace_id:
        raise ValueError("workspace_id is required for non-global roles.")

    ur = db.session.query(UserRole).filter_by(
        user_id=user_id,
        workspace_id=normalized_workspace_id,
        role_id=role.id,
    ).first()
    if not ur:
        return False

    db.session.delete(ur)
    db.session.commit()
    invalidate_user_roles(user_id, workspace_id=normalized_workspace_id)
    return True


def revoke_role_by_id(
    user_id: str,
    user_role_id: int,
    workspace_id: str | None = None,
) -> bool:
    """
    Revoke a direct role assignment by user_roles.id.

    Only super_admin may remain global (workspace_id NULL).
    """
    from app.extensions import db
    ur = db.session.query(UserRole).filter_by(id=user_role_id, user_id=user_id).first()
    if not ur:
        return False

    role_name = ur.role.name if ur.role else ""
    normalized_workspace_id = str(workspace_id or "").strip() or None
    if role_name in GLOBAL_ROLES:
        if ur.workspace_id is not None:
            return False
    elif ur.workspace_id != normalized_workspace_id:
        return False

    db.session.delete(ur)
    db.session.commit()
    invalidate_user_roles(user_id, workspace_id=ur.workspace_id)
    return True


def set_workspace_feature(
    workspace_id: str, feature_key: str, is_active: bool, granted_by: str
) -> dict[str, Any]:
    """Enable or disable a feature for a workspace. Invalidates cache."""
    from app.extensions import db
    from app.models.rbac import WorkspaceFeature

    wf = db.session.query(WorkspaceFeature).filter_by(
        workspace_id=workspace_id, feature_key=feature_key
    ).first()

    if wf:
        wf.is_active = is_active
        wf.granted_by = granted_by
    else:
        wf = WorkspaceFeature(
            workspace_id=workspace_id,
            feature_key=feature_key,
            is_active=is_active,
            granted_by=granted_by,
        )
        db.session.add(wf)

    db.session.commit()
    invalidate_workspace_features(workspace_id)
    return wf.to_dict()


def ensure_system_roles() -> list[dict[str, Any]]:
    """
    Ensure all canonical system RBAC roles exist.

    Safe to call repeatedly. Returns the created role rows, if any.
    """
    from app.extensions import db

    created: list[dict[str, Any]] = []
    existing = {
        row.name: row
        for row in db.session.query(Role).filter(
            Role.name.in_([definition["name"] for definition in ROLE_DEFINITIONS])
        ).all()
    }

    for definition in ROLE_DEFINITIONS:
        if definition["name"] in existing:
            continue
        role = Role(**definition)
        db.session.add(role)
        created.append(definition)

    if created:
        db.session.commit()

    return created
