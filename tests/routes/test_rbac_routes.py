from __future__ import annotations

from typing import Any, Dict

import app.decorators.security as security
import app.routes.rbac_routes as rbac_routes
import app.services.rbac_service as rbac_service


def _headers(monkeypatch, *, actor_id: str = "admin-1", roles: set[str] | None = None) -> Dict[str, str]:
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": actor_id, "username": actor_id, "is_admin": True},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(
        rbac_service,
        "get_effective_roles",
        lambda user_id, workspace_id=None: set(roles or {"super_admin"}),
    )
    monkeypatch.setattr(
        rbac_routes,
        "get_effective_roles",
        lambda user_id, workspace_id=None: set(roles or {"super_admin"}),
    )
    return {"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-1"}


class _RoleRow:
    def __init__(self, role_id: int, name: str, feature_key: str | None = None) -> None:
        self.id = role_id
        self.name = name
        self.feature_key = feature_key

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.name.replace("_", " ").title(),
            "description": None,
            "feature_key": self.feature_key,
            "is_system": True,
        }


class _UserRoleRow:
    def __init__(
        self,
        assignment_id: int,
        role_id: int,
        role_name: str,
        feature_key: str | None = None,
        granted_by: str = "admin-1",
        granted_at: str = "2026-03-19T00:00:00",
        workspace_id: str | None = "ws-1",
    ) -> None:
        self.id = assignment_id
        self.role_id = role_id
        self.role = _RoleRow(role_id, role_name, feature_key)
        self.granted_by = granted_by
        self.workspace_id = workspace_id
        self.granted_at = type("_GrantedAt", (), {"isoformat": lambda self: granted_at})()


def test_rbac_roles_get_success(client, monkeypatch):
    monkeypatch.setattr(rbac_routes, "ensure_system_roles", lambda: [])
    monkeypatch.setattr(
        rbac_routes,
        "_list_roles",
        lambda: [
            _RoleRow(1, "skills:user", "skills"),
            _RoleRow(2, "super_admin", None),
            _RoleRow(3, "library_admin", None),
        ],
    )

    resp = client.get("/api/v1/rbac/roles", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert [row["name"] for row in resp.json["roles"]] == ["skills:user", "super_admin", "library_admin"]


def test_rbac_roles_get_ensures_canonical_roles(client, monkeypatch):
    called = {"value": False}
    monkeypatch.setattr(rbac_routes, "ensure_system_roles", lambda: called.__setitem__("value", True) or [])
    monkeypatch.setattr(rbac_routes, "_list_roles", lambda: [])

    resp = client.get("/api/v1/rbac/roles", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert called["value"] is True


def test_rbac_user_roles_get_success(client, monkeypatch):
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-7")
    monkeypatch.setattr(
        rbac_routes,
        "_list_user_role_rows",
        lambda user_id, workspace_id: [
            _UserRoleRow(3, 5, "skills:user", "skills", workspace_id=workspace_id),
            _UserRoleRow(4, 6, "library_admin", None, workspace_id=None),
        ],
    )

    resp = client.get("/api/v1/rbac/users/u-42/roles", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["workspace_id"] == "ws-7"
    assert resp.json["roles"][0]["role_name"] == "skills:user"
    assert resp.json["roles"][0]["feature_key"] == "skills"
    assert resp.json["roles"][1]["role_name"] == "library_admin"


def test_rbac_user_roles_post_requires_role_name(client, monkeypatch):
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")

    resp = client.post("/api/v1/rbac/users/u-42/roles", headers=_headers(monkeypatch), json={})
    assert resp.status_code == 400
    assert resp.json["error"] == "role_name is required"


def test_rbac_user_roles_post_rejects_global_role_for_workspace_admin(client, monkeypatch):
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(rbac_routes, "_find_role_by_name", lambda role_name: _RoleRow(2, role_name, None))

    resp = client.post(
        "/api/v1/rbac/users/u-42/roles",
        headers=_headers(monkeypatch, roles={"workspace_admin"}),
        json={"role_name": "super_admin"},
    )
    assert resp.status_code == 403


def test_rbac_user_roles_post_rejects_library_admin_for_workspace_admin(client, monkeypatch):
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(rbac_routes, "_find_role_by_name", lambda role_name: _RoleRow(2, role_name, None))

    resp = client.post(
        "/api/v1/rbac/users/u-42/roles",
        headers=_headers(monkeypatch, roles={"workspace_admin"}),
        json={"role_name": "library_admin"},
    )
    assert resp.status_code == 403


def test_rbac_user_roles_post_assigns_library_admin_globally(client, monkeypatch):
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(rbac_routes, "_find_role_by_name", lambda role_name: _RoleRow(5, role_name, None))
    monkeypatch.setattr(rbac_routes, "_find_existing_user_role", lambda user_id, role_id, workspace_id: None)
    captured = {}

    def _assign_role(**kwargs):
        captured.update(kwargs)
        return {
            "id": 9,
            "user_id": kwargs["user_id"],
            "role_id": 5,
            "role_name": kwargs["role_name"],
            "granted_by": kwargs["granted_by"],
            "granted_at": "2026-03-19T00:00:00",
        }

    monkeypatch.setattr(rbac_routes, "assign_role", _assign_role)

    resp = client.post(
        "/api/v1/rbac/users/u-42/roles",
        headers=_headers(monkeypatch),
        json={"role_name": "library_admin"},
    )
    assert resp.status_code == 201
    assert captured["workspace_id"] is None


def test_rbac_user_roles_post_returns_conflict_when_duplicate(client, monkeypatch):
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(rbac_routes, "_find_role_by_name", lambda role_name: _RoleRow(5, role_name, "skills"))
    monkeypatch.setattr(rbac_routes, "_find_existing_user_role", lambda user_id, role_id, workspace_id: object())

    resp = client.post(
        "/api/v1/rbac/users/u-42/roles",
        headers=_headers(monkeypatch),
        json={"role_name": "skills:user"},
    )
    assert resp.status_code == 409


def test_rbac_user_roles_post_success(client, monkeypatch):
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(rbac_routes, "_find_role_by_name", lambda role_name: _RoleRow(5, role_name, "skills"))
    monkeypatch.setattr(rbac_routes, "_find_existing_user_role", lambda user_id, role_id, workspace_id: None)
    monkeypatch.setattr(
        rbac_routes,
        "assign_role",
        lambda **kwargs: {
            "id": 9,
            "user_id": kwargs["user_id"],
            "role_id": 5,
            "role_name": kwargs["role_name"],
            "granted_by": kwargs["granted_by"],
            "granted_at": "2026-03-19T00:00:00",
        },
    )

    resp = client.post(
        "/api/v1/rbac/users/u-42/roles",
        headers=_headers(monkeypatch),
        json={"role_name": "skills:user"},
    )
    assert resp.status_code == 201
    assert resp.json["user_role"]["role_name"] == "skills:user"


def test_rbac_user_role_delete_prevents_self_demotion(client, monkeypatch):
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(
        rbac_routes,
        "_find_user_role_row",
        lambda user_id, user_role_id: _UserRoleRow(user_role_id, 1, "super_admin", None, workspace_id=None),
    )

    resp = client.delete(
        "/api/v1/rbac/users/admin-1/roles/11",
        headers=_headers(monkeypatch, actor_id="admin-1"),
    )
    assert resp.status_code == 403


def test_rbac_user_role_delete_success(client, monkeypatch):
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(
        rbac_routes,
        "_find_user_role_row",
        lambda user_id, user_role_id: _UserRoleRow(user_role_id, 5, "skills:user", "skills"),
    )
    monkeypatch.setattr(rbac_routes, "revoke_role_by_id", lambda **kwargs: True)

    resp = client.delete("/api/v1/rbac/users/u-42/roles/11", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json == {"revoked": True}


def test_rbac_user_role_delete_workspace_admin_self_revoke_is_allowed(client, monkeypatch):
    """workspace_admin is no longer a global role, so self-revocation is permitted."""
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(
        rbac_routes,
        "_find_user_role_row",
        lambda user_id, user_role_id: _UserRoleRow(user_role_id, 2, "workspace_admin", None, workspace_id="ws-1"),
    )
    monkeypatch.setattr(rbac_routes, "revoke_role_by_id", lambda **kwargs: True)

    resp = client.delete(
        "/api/v1/rbac/users/admin-1/roles/12",
        headers=_headers(monkeypatch, actor_id="admin-1", roles={"super_admin"}),
    )
    assert resp.status_code == 200
    assert resp.json == {"revoked": True}


def test_rbac_user_role_delete_prevents_library_admin_self_demotion(client, monkeypatch):
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(
        rbac_routes,
        "_find_user_role_row",
        lambda user_id, user_role_id: _UserRoleRow(user_role_id, 2, "library_admin", None, workspace_id=None),
    )

    resp = client.delete(
        "/api/v1/rbac/users/admin-1/roles/13",
        headers=_headers(monkeypatch, actor_id="admin-1", roles={"super_admin"}),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# workspace_admin grant/revoke workspace_admin permission tests
# ---------------------------------------------------------------------------


def test_workspace_admin_can_grant_workspace_admin(client, monkeypatch):
    """workspace_admin should now be permitted to grant workspace_admin within their workspace."""
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(rbac_routes, "_find_role_by_name", lambda role_name: _RoleRow(2, role_name, None))
    monkeypatch.setattr(rbac_routes, "_find_existing_user_role", lambda user_id, role_id, workspace_id: None)
    monkeypatch.setattr(
        rbac_routes,
        "assign_role",
        lambda **kwargs: {
            "id": 10,
            "user_id": kwargs["user_id"],
            "role_id": 2,
            "role_name": kwargs["role_name"],
            "granted_by": kwargs["granted_by"],
            "granted_at": "2026-03-23T00:00:00",
        },
    )

    resp = client.post(
        "/api/v1/rbac/users/u-99/roles",
        headers=_headers(monkeypatch, roles={"workspace_admin"}),
        json={"role_name": "workspace_admin"},
    )
    assert resp.status_code == 201
    assert resp.json["user_role"]["role_name"] == "workspace_admin"


def test_workspace_admin_cannot_grant_super_admin(client, monkeypatch):
    """workspace_admin must not be able to escalate to super_admin."""
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(rbac_routes, "_find_role_by_name", lambda role_name: _RoleRow(1, role_name, None))

    resp = client.post(
        "/api/v1/rbac/users/u-99/roles",
        headers=_headers(monkeypatch, roles={"workspace_admin"}),
        json={"role_name": "super_admin"},
    )
    assert resp.status_code == 403


def test_workspace_admin_cannot_grant_library_admin(client, monkeypatch):
    """workspace_admin must not be able to grant the global library_admin role."""
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(rbac_routes, "_find_role_by_name", lambda role_name: _RoleRow(3, role_name, None))

    resp = client.post(
        "/api/v1/rbac/users/u-99/roles",
        headers=_headers(monkeypatch, roles={"workspace_admin"}),
        json={"role_name": "library_admin"},
    )
    assert resp.status_code == 403


def test_super_admin_can_grant_workspace_admin(client, monkeypatch):
    """super_admin must still be able to grant workspace_admin after the permission change."""
    monkeypatch.setattr(rbac_routes, "extract_workspace_id", lambda: "ws-1")
    monkeypatch.setattr(rbac_routes, "_find_role_by_name", lambda role_name: _RoleRow(2, role_name, None))
    monkeypatch.setattr(rbac_routes, "_find_existing_user_role", lambda user_id, role_id, workspace_id: None)
    monkeypatch.setattr(
        rbac_routes,
        "assign_role",
        lambda **kwargs: {
            "id": 11,
            "user_id": kwargs["user_id"],
            "role_id": 2,
            "role_name": kwargs["role_name"],
            "granted_by": kwargs["granted_by"],
            "granted_at": "2026-03-23T00:00:00",
        },
    )

    resp = client.post(
        "/api/v1/rbac/users/u-99/roles",
        headers=_headers(monkeypatch, roles={"super_admin"}),
        json={"role_name": "workspace_admin"},
    )
    assert resp.status_code == 201
    assert resp.json["user_role"]["role_name"] == "workspace_admin"
