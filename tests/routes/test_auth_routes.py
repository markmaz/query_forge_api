from __future__ import annotations

from typing import Any, Dict

import app.routes.auth_routes as auth_routes
from app.decorators import security
from app.exceptions.forge_error import ForgeError
from app.models.user import User


def test_login_success(client, monkeypatch):
    def _auth(self, username: str, password: str) -> Dict[str, Any]:
        return {
            "user_id": "u1",
            "requires_otp": True,
            "email": "u1@example.com",
            "workspace_id": "ws-1",
            "workspaceId": "ws-1",
        }

    monkeypatch.setattr(auth_routes.AuthService, "authenticate", _auth)
    monkeypatch.setattr(auth_routes.TotpService, "is_totp_enabled", lambda self, _uid: False)
    monkeypatch.setattr(auth_routes, "issue_otp_challenge", lambda **_kwargs: "ch-123")

    resp = client.post("/api/v1/auth/login", json={"username": "u", "password": "p"})
    assert resp.status_code == 200
    assert resp.json["requires_otp"] is True
    assert resp.json["challenge_id"] == "ch-123"
    assert resp.json["workspace_id"] == "ws-1"
    assert resp.json["workspaceId"] == "ws-1"
    assert "access_token" not in resp.json


def test_login_invalid_credentials(client, monkeypatch):
    def _auth(self, username: str, password: str):
        return None

    monkeypatch.setattr(auth_routes.AuthService, "authenticate", _auth)

    resp = client.post("/api/v1/auth/login", json={"username": "u", "password": "p"})
    assert resp.status_code == 401
    assert resp.json["message"] == "Invalid username or password"


def test_login_totp_enabled_returns_mfa_challenge(client, monkeypatch):
    monkeypatch.setattr(
        auth_routes.AuthService,
        "authenticate",
        lambda self, username, password: {"user_id": "u1"},
    )
    monkeypatch.setattr(auth_routes.TotpService, "is_totp_enabled", lambda self, _uid: True)
    monkeypatch.setattr(auth_routes.LoginChallengeService, "create_challenge", lambda self, _uid: "totp-ch-1")

    resp = client.post("/api/v1/auth/login", json={"username": "u", "password": "p"})
    assert resp.status_code == 200
    assert resp.json["mfa_required"] is True
    assert resp.json["mfa_type"] == "totp"
    assert resp.json["challenge_id"] == "totp-ch-1"


def test_totp_verify_success(client, monkeypatch):
    monkeypatch.setattr(auth_routes.RateLimitService, "enforce", lambda self, **_kwargs: None)
    monkeypatch.setattr(auth_routes.LoginChallengeService, "consume_challenge", lambda self, _cid: "u1")
    monkeypatch.setattr(auth_routes.TotpService, "verify_totp_code", lambda self, _uid, _code: True)
    monkeypatch.setattr(
        auth_routes.AuthService,
        "issue_tokens",
        lambda self, _user: {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_in": 900,
        },
    )
    monkeypatch.setattr(auth_routes.AuthService, "qf_refresh_ttl", 1209600, raising=False)

    resp = client.post(
        "/api/v1/auth/mfa/totp/verify",
        json={"challenge_id": "ch-1", "code": "123456"},
    )
    assert resp.status_code == 200
    assert resp.json["access_token"] == "access-1"
    assert resp.json["mfa_type"] == "totp"
    assert "refresh_token=" in (resp.headers.get("Set-Cookie") or "")


def test_totp_verify_invalid_challenge(client, monkeypatch):
    monkeypatch.setattr(auth_routes.RateLimitService, "enforce", lambda self, **_kwargs: None)
    monkeypatch.setattr(auth_routes.LoginChallengeService, "consume_challenge", lambda self, _cid: None)

    resp = client.post(
        "/api/v1/auth/mfa/totp/verify",
        json={"challenge_id": "ch-1", "code": "123456"},
    )
    assert resp.status_code == 401
    assert resp.json["error"] == "Invalid code or expired challenge"


def test_totp_start_confirm_disable_success(client, monkeypatch):
    monkeypatch.setattr(security.auth_service, "verify_token", lambda _token: {"sub": "u1"})
    monkeypatch.setattr(auth_routes.RateLimitService, "enforce", lambda self, **_kwargs: None)
    monkeypatch.setattr(
        auth_routes.TotpService,
        "start_totp_enrollment",
        lambda self, _uid: {"otpauth_uri": "uri", "qr_svg": "<svg />", "manual_secret_masked": "AB****YZ"},
    )
    monkeypatch.setattr(auth_routes.TotpService, "confirm_totp_enrollment", lambda self, _uid, _code: {"enabled": True})
    monkeypatch.setattr(auth_routes.TotpService, "disable_totp", lambda self, _uid, _pw, _code: {"enabled": False})
    headers = {"Authorization": "Bearer token"}

    start = client.post("/api/v1/auth/mfa/totp/start", headers=headers)
    assert start.status_code == 200
    assert start.json["otpauth_uri"] == "uri"

    confirm = client.post(
        "/api/v1/auth/mfa/totp/confirm",
        headers=headers,
        json={"code": "123456"},
    )
    assert confirm.status_code == 200
    assert confirm.json["enabled"] is True

    disable = client.post(
        "/api/v1/auth/mfa/totp/disable",
        headers=headers,
        json={"password": "pw", "code": "123456"},
    )
    assert disable.status_code == 200
    assert disable.json["enabled"] is False


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
        raise ForgeError("User not found", 404)

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
