from __future__ import annotations

from typing import Dict

import app.decorators.security as security
import app.routes.request_helpers as request_helpers
import app.services.rbac_service as rbac_service
import app.features.users.user_api as user_routes


def _headers(monkeypatch) -> Dict[str, str]:
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(
        request_helpers.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(
        rbac_service,
        "get_effective_roles",
        lambda user_id, workspace_id=None: {"workspace_admin"},
    )
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "username": "user-1", "is_admin": True},
    )
    return {"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-1"}


def test_user_roles_get_success(client, monkeypatch):
    class _Svc:
        def get_user_direct_roles(self, user_id: str, workspace_id: str | None = None):
            assert user_id == "u1"
            assert workspace_id == "ws-1"
            return [{"role_name": "admin"}]

        def get_user_effective_roles(self, user_id: str, workspace_id: str | None = None):
            assert user_id == "u1"
            assert workspace_id == "ws-1"
            return [{"role_name": "admin"}]

    monkeypatch.setattr(user_routes, "UserService", _Svc)
    resp = client.get("/api/v1/users/u1/roles", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["user_id"] == "u1"
    assert resp.json["workspace_id"] == "ws-1"
    assert resp.json["direct_roles"][0]["role_name"] == "admin"


def test_user_roles_post_validation(client, monkeypatch):
    resp = client.post("/api/v1/users/u1/roles", headers=_headers(monkeypatch), json={})
    assert resp.status_code == 400
    assert resp.json["error"] == "role_name is required"


def test_user_roles_post_success(client, monkeypatch):
    class _Svc:
        def add_user_direct_role(self, user_id: str, role_name: str, workspace_id: str | None = None):
            assert workspace_id == "ws-1"
            return {"user_id": user_id, "workspace_id": workspace_id, "role_name": role_name, "created": True}

    monkeypatch.setattr(user_routes, "UserService", _Svc)
    resp = client.post("/api/v1/users/u1/roles", headers=_headers(monkeypatch), json={"role_name": "admin"})
    assert resp.status_code == 200
    assert resp.json["mapping"]["created"] is True


def test_user_roles_put_success(client, monkeypatch):
    class _Svc:
        def replace_user_direct_roles(self, user_id: str, role_names: list[str], workspace_id: str | None = None):
            assert role_names == ["admin", "viewer"]
            assert workspace_id == "ws-1"
            return {"user_id": user_id, "workspace_id": workspace_id, "roles": [{"role_name": "admin"}, {"role_name": "viewer"}], "count": 2}

    monkeypatch.setattr(user_routes, "UserService", _Svc)
    resp = client.put(
        "/api/v1/users/u1/roles",
        headers=_headers(monkeypatch),
        json={"role_names": ["admin", "viewer"]},
    )
    assert resp.status_code == 200
    assert resp.json["count"] == 2


def test_user_role_patch_success(client, monkeypatch):
    class _Svc:
        def update_user_direct_role(self, user_id: str, old_role_name: str, new_role_name: str, workspace_id: str | None = None):
            assert workspace_id == "ws-1"
            return {
                "user_id": user_id,
                "workspace_id": workspace_id,
                "old_role_name": old_role_name,
                "new_role_name": new_role_name,
                "created": True,
            }

    monkeypatch.setattr(user_routes, "UserService", _Svc)
    resp = client.patch(
        "/api/v1/users/u1/roles/viewer",
        headers=_headers(monkeypatch),
        json={"role_name": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json["new_role_name"] == "admin"


def test_user_role_delete_success(client, monkeypatch):
    class _Svc:
        def remove_user_direct_role(self, user_id: str, role_name: str, workspace_id: str | None = None):
            assert workspace_id == "ws-1"
            return {"user_id": user_id, "workspace_id": workspace_id, "role_name": role_name, "deleted": True}

    monkeypatch.setattr(user_routes, "UserService", _Svc)
    resp = client.delete("/api/v1/users/u1/roles/admin", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["deleted"] is True
