from __future__ import annotations

import app.routes.user_routes as user_routes
from app.models.tenancy.user import User


def test_users_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def get_users(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            return [], None, None, 0

    monkeypatch.setattr(user_routes, "UserService", _Svc)

    resp = client.get("/api/v1/users/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["total_count"] == 0


def test_user_counts_scopes_to_workspace(client, auth_headers, monkeypatch):
    class _Svc:
        def get_counts(self, *, workspace_id=None):
            assert workspace_id == "ws-1"
            return {"All": 1, "Active": 1, "Inactive": 0, "Invited": 0}

    monkeypatch.setattr(user_routes, "UserService", _Svc)

    resp = client.get("/api/v1/users/counts", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["All"] == 1


def test_users_post_validation_error(client, auth_headers):
    resp = client.post("/api/v1/users/", headers=auth_headers, json={"bad": "payload"})
    assert resp.status_code == 400


def test_users_requires_auth(client):
    resp = client.get("/api/v1/users/")
    assert resp.status_code == 403


def test_users_get_redacts_sensitive_fields(client, monkeypatch):
    import app.decorators.security as security

    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "username": "user-1", "is_admin": True},
    )

    class _Svc:
        def get_users(self, **kwargs):
            user = User(
                user_id="u1",
                user_name="alice",
                password="hashed-secret",
                otp_secret="otp-secret",
                email="a@example.com",
            )
            return [user], None, None, 1

    monkeypatch.setattr(user_routes, "UserService", _Svc)

    resp = client.get("/api/v1/users/", headers={"Authorization": "Bearer token-1"})
    assert resp.status_code == 200
    payload = resp.json["users"][0]
    assert "password" not in payload
    assert "otp_secret" not in payload


def test_users_put_redacts_sensitive_fields(client, monkeypatch):
    import app.decorators.security as security

    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "username": "user-1", "is_admin": True},
    )

    class _Svc:
        def update_user(self, user_id: str, update_data: User, workspace_id: str | None = None):
            return User(
                user_id=user_id,
                first_name="Updated",
                password="hashed-secret",
                otp_secret="otp-secret",
                email="a@example.com",
            )

    monkeypatch.setattr(user_routes, "UserService", _Svc)

    resp = client.put(
        "/api/v1/users/u1",
        headers={"Authorization": "Bearer token-1"},
        json={"first_name": "Updated"},
    )
    assert resp.status_code == 200
    assert "password" not in resp.json
    assert "otp_secret" not in resp.json


def test_users_get_detail_redacts_sensitive_fields_and_scopes_workspace(client, auth_headers, monkeypatch):
    class _Svc:
        def get_user(self, user_id: str, workspace_id: str | None = None):
            assert user_id == "u1"
            assert workspace_id == "ws-1"
            return User(
                user_id=user_id,
                user_name="alice",
                first_name="Alice",
                password="hashed-secret",
                otp_secret="otp-secret",
                email="a@example.com",
            )

    monkeypatch.setattr(user_routes, "UserService", _Svc)

    resp = client.get("/api/v1/users/u1", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json["user_id"] == "u1"
    assert "password" not in resp.json
    assert "otp_secret" not in resp.json


def test_users_get_detail_ignores_workspace_scope_for_token_admin(client, monkeypatch):
    import app.decorators.security as security

    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "admin-1", "username": "admin-1", "is_admin": True},
    )

    class _Svc:
        def get_user(self, user_id: str, workspace_id: str | None = None):
            assert user_id == "u1"
            assert workspace_id is None
            return User(
                user_id=user_id,
                user_name="alice",
                first_name="Alice",
                email="a@example.com",
            )

    monkeypatch.setattr(user_routes, "UserService", _Svc)

    resp = client.get(
        "/api/v1/users/u1",
        headers={
          "Authorization": "Bearer admin-token",
          "X-Workspace-Id": "ws-admin",
        },
    )

    assert resp.status_code == 200
    assert resp.json["user_id"] == "u1"


def test_users_put_without_bearer_or_invite_token_rejected(client):
    resp = client.put("/api/v1/users/u1", json={"first_name": "Nope"})
    assert resp.status_code == 403
    assert "Token is missing" in str(resp.json.get("error") or "")


def test_users_put_with_invite_query_token_but_no_bearer_rejected(client):
    resp = client.put("/api/v1/users/u1?token=invite-token-1", json={"first_name": "Nope"})
    assert resp.status_code == 403
    assert "Token is missing" in str(resp.json.get("error") or "")


def test_super_admin_bypasses_workspace_filter(client, monkeypatch):
    """Super admins must receive workspace_id=None so they see all users."""
    import app.decorators.security as security
    import app.decorators.rbac as rbac
    from flask import g

    # Stub token verification so the request passes token_required.
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "super-1", "username": "super-1", "is_admin": True},
    )

    # Stub get_effective_roles to return super_admin explicitly.
    monkeypatch.setattr(
        rbac,
        "_ensure_roles_loaded",
        lambda: setattr(g, "effective_roles", {"super_admin"})
        if not hasattr(g, "effective_roles")
        else None,
    )

    received_workspace_ids: list = []

    class _Svc:
        def get_users(self, **kwargs):
            received_workspace_ids.append(kwargs.get("workspace_id"))
            return [], None, None, 0

    monkeypatch.setattr(user_routes, "UserService", _Svc)

    resp = client.get(
        "/api/v1/users/",
        headers={
            "Authorization": "Bearer super-token",
            "X-Workspace-Id": "ws-specific",
        },
    )
    assert resp.status_code == 200
    assert received_workspace_ids == [None], (
        f"Expected workspace_id=None for super_admin but got {received_workspace_ids}"
    )


def test_non_super_admin_scoped_to_workspace(client, auth_headers, monkeypatch):
    """Workspace admins (non super_admin) must still be scoped to their workspace."""
    import app.decorators.rbac as rbac
    from flask import g

    # Override effective_roles to be workspace_admin only (not super_admin).
    def _set_workspace_admin_roles():
        g.effective_roles = {"workspace_admin"}

    monkeypatch.setattr(rbac, "_ensure_roles_loaded", _set_workspace_admin_roles)

    received_workspace_ids: list = []

    class _Svc:
        def get_users(self, **kwargs):
            received_workspace_ids.append(kwargs.get("workspace_id"))
            return [], None, None, 0

    monkeypatch.setattr(user_routes, "UserService", _Svc)

    resp = client.get("/api/v1/users/", headers=auth_headers)
    assert resp.status_code == 200
    assert received_workspace_ids == ["ws-1"], (
        f"Expected workspace_id='ws-1' for workspace_admin but got {received_workspace_ids}"
    )
