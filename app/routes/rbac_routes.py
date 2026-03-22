from __future__ import annotations

from flask import g, request
from flask_restx import Namespace, abort

from app.decorators.rbac import require_admin
from app.decorators.security import token_required
from app.models.rbac import Role, UserRole
from app.routes.forge_resource import ForgeResource
from app.routes.request_helpers import extract_workspace_id
from app.services.rbac_service import assign_role, get_effective_roles, revoke_role_by_id

rbac_ns = Namespace("rbac", description="RBAC administration")


def _list_roles() -> list[Role]:
    return Role.query.order_by(Role.id.asc()).all()


def _list_user_role_rows(user_id: str, workspace_id: str) -> list[UserRole]:
    return (
        UserRole.query.join(Role)
        .filter(UserRole.user_id == user_id)
        .filter(
            ((UserRole.workspace_id == workspace_id) | ((UserRole.workspace_id.is_(None)) & (Role.name == "super_admin")))
        )
        .order_by(UserRole.id.asc())
        .all()
    )


def _find_role_by_name(role_name: str) -> Role | None:
    return Role.get_by_name(role_name)


def _normalize_role_workspace(role_name: str, workspace_id: str) -> str | None:
    if role_name == "super_admin":
        return None
    return workspace_id


def _find_existing_user_role(user_id: str, role_id: int, workspace_id: str | None) -> UserRole | None:
    query = UserRole.query.filter_by(user_id=user_id, role_id=role_id)
    if workspace_id is None:
        query = query.filter(UserRole.workspace_id.is_(None))
    else:
        query = query.filter(UserRole.workspace_id == workspace_id)
    return query.first()


def _find_user_role_row(user_id: str, user_role_id: int) -> UserRole | None:
    return (
        UserRole.query.filter_by(id=user_role_id, user_id=user_id)
        .join(Role)
        .first()
    )


def _role_to_assignment_payload(row: UserRole) -> dict[str, object | None]:
    role = row.role
    return {
        "id": row.id,
        "role_id": row.role_id,
        "role_name": role.name if role else None,
        "feature_key": role.feature_key if role else None,
        "granted_by": row.granted_by,
        "granted_at": row.granted_at.isoformat() if row.granted_at else None,
    }


def _read_role_name(body: object) -> str:
    if not isinstance(body, dict):
        return ""
    return str(body.get("role_name") or "").strip()


@rbac_ns.route("/roles")
class RbacRoleList(ForgeResource):
    @token_required
    @require_admin()
    def get(self):
        rows = _list_roles()
        return {"roles": [row.to_dict() for row in rows]}, 200


@rbac_ns.route("/users/<string:user_id>/roles")
class UserRoleList(ForgeResource):
    @token_required
    @require_admin()
    def get(self, user_id: str):
        workspace_id = extract_workspace_id()

        # Current schema stores direct roles globally. Keep workspace_id in the
        # contract so the route stays compatible if workspace-scoped user_roles
        # are added later.
        rows = _list_user_role_rows(user_id, workspace_id)
        return {
            "user_id": user_id,
            "workspace_id": workspace_id,
            "roles": [_role_to_assignment_payload(row) for row in rows],
        }, 200

    @token_required
    @require_admin()
    def post(self, user_id: str):
        workspace_id = extract_workspace_id()
        role_name = _read_role_name(request.get_json(silent=True) or {})
        if not role_name:
            return {"error": "role_name is required"}, 400

        role = _find_role_by_name(role_name)
        if not role:
            return {"error": f"Unknown role_name: {role_name}"}, 400

        current_roles = get_effective_roles(str(getattr(g, "user_id", "")), workspace_id=workspace_id)
        is_super = "super_admin" in current_roles
        if role_name in {"super_admin", "workspace_admin"} and not is_super:
            abort(403, "Only super_admin can assign admin roles.")

        existing = _find_existing_user_role(
            user_id,
            role.id,
            _normalize_role_workspace(role_name, workspace_id),
        )
        if existing:
            return {"error": "Role already assigned."}, 409

        created = assign_role(
            user_id=user_id,
            role_name=role_name,
            workspace_id=workspace_id,
            granted_by=str(getattr(g, "user_id", "") or ""),
        )
        return {"user_role": created}, 201


@rbac_ns.route("/users/<string:user_id>/roles/<int:user_role_id>")
class UserRoleDetails(ForgeResource):
    @token_required
    @require_admin()
    def delete(self, user_id: str, user_role_id: int):
        workspace_id = extract_workspace_id()
        row = _find_user_role_row(user_id, user_role_id)
        if not row:
            return {"error": "Role assignment not found."}, 404

        role_name = row.role.name if row.role else ""
        current_user_id = str(getattr(g, "user_id", "") or "")
        current_roles = get_effective_roles(current_user_id, workspace_id=workspace_id)
        is_super = "super_admin" in current_roles

        if role_name in {"super_admin", "workspace_admin"} and not is_super:
            abort(403, "Only super_admin can revoke admin roles.")

        if user_id == current_user_id and role_name in {"super_admin", "workspace_admin"}:
            abort(403, "Cannot revoke your own admin role.")

        revoked = revoke_role_by_id(
            user_id=user_id,
            user_role_id=user_role_id,
            workspace_id=workspace_id,
        )
        if not revoked:
            return {"error": "Role assignment not found."}, 404
        return {"revoked": True}, 200
