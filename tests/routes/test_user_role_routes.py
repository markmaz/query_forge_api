from __future__ import annotations

from typing import Any, Dict

import app.decorators.security as security
import app.routes.user_routes as user_routes


def _headers(monkeypatch) -> Dict[str, str]:
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "username": "user-1", "is_admin": True},
    )
    return {"Authorization": "Bearer token-1"}


def test_user_roles_get_success(client, monkeypatch):
    class _Svc:
        def get_user_direct_roles(self, user_id: str):
            assert user_id == "u1"
            return [{"role_id": "admin", "role_name": "Admin"}]

        def get_user_effective_roles(self, user_id: str):
            assert user_id == "u1"
            return [{"role_id": "admin", "role_name": "Admin"}]

    monkeypatch.setattr(user_routes, "UserService", _Svc)
    resp = client.get("/api/v1/users/u1/roles", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["user_id"] == "u1"
    assert resp.json["direct_roles"][0]["role_id"] == "admin"


def test_user_roles_post_validation(client, monkeypatch):
    resp = client.post("/api/v1/users/u1/roles", headers=_headers(monkeypatch), json={})
    assert resp.status_code == 400
    assert resp.json["error"] == "role_id is required"


def test_user_roles_post_success(client, monkeypatch):
    class _Svc:
        def add_user_direct_role(self, user_id: str, role_id: str):
            return {"user_id": user_id, "role_id": role_id, "created": True}

    monkeypatch.setattr(user_routes, "UserService", _Svc)
    resp = client.post("/api/v1/users/u1/roles", headers=_headers(monkeypatch), json={"role_id": "admin"})
    assert resp.status_code == 200
    assert resp.json["mapping"]["created"] is True


def test_user_roles_put_success(client, monkeypatch):
    class _Svc:
        def replace_user_direct_roles(self, user_id: str, role_ids: list[str]):
            assert role_ids == ["admin", "viewer"]
            return {"user_id": user_id, "roles": [{"role_id": "admin"}, {"role_id": "viewer"}], "count": 2}

    monkeypatch.setattr(user_routes, "UserService", _Svc)
    resp = client.put(
        "/api/v1/users/u1/roles",
        headers=_headers(monkeypatch),
        json={"role_ids": ["admin", "viewer"]},
    )
    assert resp.status_code == 200
    assert resp.json["count"] == 2


def test_user_role_patch_success(client, monkeypatch):
    class _Svc:
        def update_user_direct_role(self, user_id: str, old_role_id: str, new_role_id: str):
            return {
                "user_id": user_id,
                "old_role_id": old_role_id,
                "new_role_id": new_role_id,
                "created": True,
            }

    monkeypatch.setattr(user_routes, "UserService", _Svc)
    resp = client.patch(
        "/api/v1/users/u1/roles/viewer",
        headers=_headers(monkeypatch),
        json={"role_id": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json["new_role_id"] == "admin"


def test_user_role_delete_success(client, monkeypatch):
    class _Svc:
        def remove_user_direct_role(self, user_id: str, role_id: str):
            return {"user_id": user_id, "role_id": role_id, "deleted": True}

    monkeypatch.setattr(user_routes, "UserService", _Svc)
    resp = client.delete("/api/v1/users/u1/roles/admin", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["deleted"] is True

