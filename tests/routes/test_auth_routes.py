from __future__ import annotations

from typing import Any, Dict

import app.routes.auth_routes as auth_routes
from app.exceptions.service_error import ServiceError
from app.models.user import User


def test_login_success(client, monkeypatch):
    def _auth(self, username: str, password: str) -> Dict[str, Any]:
        return {"user_id": "u1", "requires_otp": True, "email": "u1@example.com"}

    monkeypatch.setattr(auth_routes.AuthService, "authenticate", _auth)
    monkeypatch.setattr(auth_routes, "issue_otp_challenge", lambda **_kwargs: "ch-123")

    resp = client.post("/api/v1/auth/login", json={"username": "u", "password": "p"})
    assert resp.status_code == 200
    assert resp.json["requires_otp"] is True
    assert resp.json["challenge_id"] == "ch-123"
    assert "access_token" not in resp.json


def test_login_invalid_credentials(client, monkeypatch):
    def _auth(self, username: str, password: str):
        return None

    monkeypatch.setattr(auth_routes.AuthService, "authenticate", _auth)

    resp = client.post("/api/v1/auth/login", json={"username": "u", "password": "p"})
    assert resp.status_code == 401
    assert resp.json["message"] == "Invalid username or password"


def test_reset_validate_missing_token(client):
    resp = client.post("/api/v1/auth/reset/validate", json={"token": ""})
    assert resp.status_code == 400


def test_invite_validate_returns_generic_error_when_token_invalid(client, monkeypatch):
    monkeypatch.setattr(auth_routes, "validate_token", lambda _token: (_ for _ in ()).throw(Exception("bad token")))

    resp = client.get("/api/v1/auth/invite/validate/bad")
    assert resp.status_code == 400
    assert resp.json == {"error": "Invalid or expired token"}


def test_invite_validate_returns_generic_error_when_user_missing(client, monkeypatch):
    monkeypatch.setattr(auth_routes, "validate_token", lambda _token: "u-missing")

    def _raise_not_found(self, _user_id: str):
        raise ServiceError("User not found", 404)

    monkeypatch.setattr(auth_routes.UserService, "get_user", _raise_not_found)

    resp = client.get("/api/v1/auth/invite/validate/some-token")
    assert resp.status_code == 400
    assert resp.json == {"error": "Invalid or expired token"}


def test_invite_accept_success(client, monkeypatch):
    monkeypatch.setattr(auth_routes, "validate_token", lambda _token: "u1")

    class _Svc:
        def get_user(self, user_id: str):
            assert user_id == "u1"
            return User(user_id="u1", email="u1@example.com", status="Invited")

        def update_user(self, user_id: str, update_data: User):
            assert user_id == "u1"
            assert update_data.status == "Active"
            assert update_data.password
            assert update_data.tos_accepted is True
            assert update_data.eula_accepted is True
            assert update_data.two_factor_preference == "Email"
            return User(user_id="u1", email="u1@example.com", status="Active")

    monkeypatch.setattr(auth_routes, "UserService", lambda: _Svc())
    resp = client.post(
        "/api/v1/auth/invite/accept?token=tok-1",
        json={
            "first_name": "Mark",
            "last_name": "Maslakowski",
            "password": "Oscar0875sera!!",
            "email": "u1@example.com",
        },
    )
    assert resp.status_code == 200
    assert resp.json["user_id"] == "u1"
    assert resp.json["status"] == "Active"


def test_invite_accept_missing_token(client):
    resp = client.post(
        "/api/v1/auth/invite/accept",
        json={"password": "Oscar0875sera!!"},
    )
    assert resp.status_code == 400
    assert resp.json["error"] == "Missing token"


def test_invite_accept_invalid_token(client, monkeypatch):
    monkeypatch.setattr(auth_routes, "validate_token", lambda _token: (_ for _ in ()).throw(Exception("bad token")))
    resp = client.post(
        "/api/v1/auth/invite/accept",
        json={"token": "bad", "password": "Oscar0875sera!!"},
    )
    assert resp.status_code == 400
    assert resp.json["error"] == "Invalid or expired token"


def test_invite_accept_email_mismatch_rejected(client, monkeypatch):
    monkeypatch.setattr(auth_routes, "validate_token", lambda _token: "u1")

    class _Svc:
        def get_user(self, user_id: str):
            return User(user_id="u1", email="invited@example.com", status="Invited")

        def update_user(self, user_id: str, update_data: User):
            return User(user_id="u1", email="invited@example.com", status="Active")

    monkeypatch.setattr(auth_routes, "UserService", lambda: _Svc())
    resp = client.post(
        "/api/v1/auth/invite/accept?token=tok-1",
        json={"password": "Oscar0875sera!!", "email": "different@example.com"},
    )
    assert resp.status_code == 403
    assert resp.json["error"] == "Email does not match invited account"


def test_invite_accept_already_active_returns_conflict(client, monkeypatch):
    monkeypatch.setattr(auth_routes, "validate_token", lambda _token: "u1")

    class _Svc:
        def get_user(self, user_id: str):
            return User(user_id="u1", email="u1@example.com", status="Active")

        def update_user(self, user_id: str, update_data: User):
            return User(user_id="u1", email="u1@example.com", status="Active")

    monkeypatch.setattr(auth_routes, "UserService", lambda: _Svc())
    resp = client.post(
        "/api/v1/auth/invite/accept?token=tok-1",
        json={"password": "Oscar0875sera!!"},
    )
    assert resp.status_code == 409
    assert resp.json["error"] == "Invite already accepted or inactive"
