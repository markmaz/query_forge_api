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

from app.models.rbac import FEATURE_KEYS, UserRole, WorkspaceFeature

logger = logging.getLogger(__name__)

ROLE_CACHE_TTL = 60       # seconds
FEATURE_CACHE_TTL = 120   # seconds — entitlements change less often
ROLE_CACHE_PREFIX = "qf:roles:user:"
FEATURE_CACHE_PREFIX = "qf:features:workspace:"


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


def get_user_roles(user_id: str) -> set[str]:
    """
    Return the set of role names assigned to a user.
    Cached in Valkey for ROLE_CACHE_TTL seconds.
    """
    cache_key = f"{ROLE_CACHE_PREFIX}{user_id}"

    try:
        client = _valkey()
        cached = client.smembers(cache_key)
        if cached:
            return set(cached)
    except Exception as exc:
        logger.debug("Role cache read failed (non-fatal): %s", exc)

    # Cache miss — load from DB
    rows = UserRole.query.filter_by(user_id=user_id).all()
    roles = {r.role.name for r in rows if r.role}

    try:
        client = _valkey()
        if roles:
            client.sadd(cache_key, *roles)
        else:
            # Cache empty set with a placeholder so we don't hit DB again
            client.sadd(cache_key, "__empty__")
        client.expire(cache_key, ROLE_CACHE_TTL)
    except Exception as exc:
        logger.debug("Role cache write failed (non-fatal): %s", exc)

    return roles


def invalidate_user_roles(user_id: str) -> None:
    """Call after any role assignment or revocation."""
    try:
        _valkey().delete(f"{ROLE_CACHE_PREFIX}{user_id}")
    except Exception as exc:
        logger.debug("Role cache invalidation failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------


def get_effective_roles(user_id: str) -> set[str]:
    """
    Return the full set of effective role names for a user,
    including implied roles.

    Implied roles:
      workspace_admin  → adds all feature:user roles
      feature:admin    → adds feature:user for the same feature
    """
    assigned = get_user_roles(user_id)
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

    if "workspace_admin" in assigned:
        # workspace_admin implies all feature :user roles
        for fk in FEATURE_KEYS:
            effective.add(f"{fk}:user")

    # feature:admin implies feature:user
    for fk in FEATURE_KEYS:
        if f"{fk}:admin" in assigned:
            effective.add(f"{fk}:user")

    return effective


def user_has_role(user_id: str, role_name: str) -> bool:
    """Check whether a user has an effective role."""
    return role_name in get_effective_roles(user_id)


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
    except Exception as exc:
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
    except Exception as exc:
        logger.debug("Feature cache write failed (non-fatal): %s", exc)

    return features


def invalidate_workspace_features(workspace_id: str) -> None:
    """Call after any workspace feature entitlement change."""
    try:
        _valkey().delete(f"{FEATURE_CACHE_PREFIX}{workspace_id}")
    except Exception as exc:
        logger.debug("Feature cache invalidation failed (non-fatal): %s", exc)


def workspace_has_feature(workspace_id: str, feature_key: str) -> bool:
    return feature_key in get_workspace_features(workspace_id)


# ---------------------------------------------------------------------------
# Bulk helpers (used by admin UI and role assignment API)
# ---------------------------------------------------------------------------


def assign_role(user_id: str, role_name: str, granted_by: str) -> dict[str, Any]:
    """
    Assign a role to a user. Invalidates cache.
    Returns the created UserRole dict or existing if already assigned.
    """
    from app.extensions import db
    from app.models.rbac import Role, UserRole

    role = Role.get_by_name(role_name)
    if not role:
        raise ValueError(f"Unknown role: {role_name!r}")

    existing = db.session.query(UserRole).filter_by(user_id=user_id, role_id=role.id).first()
    if existing:
        return existing.to_dict()

    ur = UserRole(user_id=user_id, role_id=role.id, granted_by=granted_by)
    db.session.add(ur)
    db.session.commit()
    invalidate_user_roles(user_id)
    return ur.to_dict()


def revoke_role(user_id: str, role_name: str) -> bool:
    """
    Revoke a role from a user. Invalidates cache.
    Returns True if removed, False if not assigned.
    """
    from app.extensions import db
    from app.models.rbac import Role, UserRole

    role = Role.get_by_name(role_name)
    if not role:
        raise ValueError(f"Unknown role: {role_name!r}")

    ur = db.session.query(UserRole).filter_by(user_id=user_id, role_id=role.id).first()
    if not ur:
        return False

    db.session.delete(ur)
    db.session.commit()
    invalidate_user_roles(user_id)
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
