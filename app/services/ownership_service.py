"""
app/services/ownership_service.py

Ownership and sharing access control for QueryForge objects.

Permission model:
  saved_query:
    Read   → owner | is_shared=True (any query_studio:user) | query_studio:admin
    Write  → owner | query_studio:admin
    Share  → owner | query_studio:admin  (same as write)

  query_skills:
    Read   → owner | is_shared=True (any skills:user) | skills:admin
    Write  → owner | skills:admin
    Share  → owner | skills:admin  (same as write)

NULL created_by = system-owned legacy data → admin-only for all operations.

Seam notes:
  user_id / workspace_id — str (VARCHAR PKs)
  get_effective_roles(user_id, workspace_id)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _has_admin_access(
    requesting_user_id: str,
    admin_role: str,
    workspace_id: str,
) -> bool:
    """True if user has admin_role, workspace_admin, or super_admin."""
    from app.services.rbac_service import get_effective_roles
    roles = get_effective_roles(requesting_user_id, workspace_id=workspace_id)
    return (
        admin_role in roles
        or "workspace_admin" in roles
        or "super_admin" in roles
    )


def can_read_object(
    created_by: str | None,
    is_shared: bool,
    requesting_user_id: str,
    admin_role: str,
    workspace_id: str,
) -> bool:
    """
    Returns True if requesting_user_id can read an object.

    True when any of:
      - requesting_user_id == created_by (owner)
      - is_shared == True (shared with workspace — any feature user can read)
      - user has admin_role, workspace_admin, or super_admin
    """
    if created_by is not None and requesting_user_id == created_by:
        return True
    if is_shared:
        return True
    return _has_admin_access(requesting_user_id, admin_role, workspace_id)


def can_modify_object(
    created_by: str | None,
    requesting_user_id: str,
    admin_role: str,
    workspace_id: str,
) -> bool:
    """
    Returns True if requesting_user_id can modify (write/delete/share) an object.

    Sharing grants READ only — shared objects remain owner/admin-only for writes.

    True when:
      - requesting_user_id == created_by (owner)
      - user has admin_role, workspace_admin, or super_admin

    NULL created_by = system-owned → admin-only.
    """
    if created_by is not None and requesting_user_id == created_by:
        return True
    return _has_admin_access(requesting_user_id, admin_role, workspace_id)


# can_share_object is identical to can_modify_object — sharing is a write op
can_share_object = can_modify_object


# ---------------------------------------------------------------------------
# List filtering — used by list endpoints to scope results
# ---------------------------------------------------------------------------


def apply_ownership_filter(
    query,
    model_class,
    requesting_user_id: str,
    admin_role: str,
    workspace_id: str,
):
    """
    Filter a SQLAlchemy query to only return objects the user can read.

    Non-admins see: objects they own + objects marked is_shared=True
    Admins see:     all objects in the workspace

    Usage:
        q = QuerySkill.query.filter_by(workspace_id=workspace_id)
        q = apply_ownership_filter(q, QuerySkill, g.user_id, "skills:admin", workspace_id)
        skills = q.all()
    """
    if _has_admin_access(requesting_user_id, admin_role, workspace_id):
        return query

    from sqlalchemy import or_
    return query.filter(
        or_(
            model_class.created_by == requesting_user_id,
            model_class.is_shared == True,  # noqa: E712
        )
    )


# ---------------------------------------------------------------------------
# Object-specific service layer helpers (used for complex multi-object ops)
# ---------------------------------------------------------------------------


def assert_can_read_query(query_id: str, requesting_user_id: str, workspace_id: str) -> None:
    from app.models.query.saved_query import SavedQuery
    q = SavedQuery.query.filter_by(id=query_id, workspace_id=workspace_id, is_deleted=0).first()
    if not q:
        raise ValueError(f"Query {query_id} not found.")
    if not can_read_object(q.created_by, bool(q.is_shared), requesting_user_id, "query_studio:admin", workspace_id):
        raise PermissionError(f"User {requesting_user_id} cannot read query {query_id}.")


def assert_can_modify_query(query_id: str, requesting_user_id: str, workspace_id: str) -> None:
    from app.models.query.saved_query import SavedQuery
    q = SavedQuery.query.filter_by(id=query_id, workspace_id=workspace_id, is_deleted=0).first()
    if not q:
        raise ValueError(f"Query {query_id} not found.")
    if not can_modify_object(q.created_by, requesting_user_id, "query_studio:admin", workspace_id):
        raise PermissionError(f"User {requesting_user_id} cannot modify query {query_id}.")


def assert_can_read_skill(skill_id: str, requesting_user_id: str, workspace_id: str) -> None:
    from app.models.query.skills import QuerySkill
    skill = QuerySkill.query.filter_by(id=skill_id, workspace_id=workspace_id).first()
    if not skill:
        raise ValueError(f"Skill {skill_id} not found.")
    if not can_read_object(skill.created_by, bool(skill.is_shared), requesting_user_id, "skills:admin", workspace_id):
        raise PermissionError(f"User {requesting_user_id} cannot read skill {skill_id}.")


def assert_can_modify_skill(skill_id: str, requesting_user_id: str, workspace_id: str) -> None:
    from app.models.query.skills import QuerySkill
    skill = QuerySkill.query.filter_by(id=skill_id, workspace_id=workspace_id).first()
    if not skill:
        raise ValueError(f"Skill {skill_id} not found.")
    if not can_modify_object(skill.created_by, requesting_user_id, "skills:admin", workspace_id):
        raise PermissionError(f"User {requesting_user_id} cannot modify skill {skill_id}.")
