from __future__ import annotations

from types import SimpleNamespace

import app.routes.otp_routes as otp_routes


def test_otp_verify_requires_challenge_id_and_otp(client):
    resp = client.post("/api/v1/otp/verify", json={"otp": "123456"})
    assert resp.status_code == 400
    assert resp.json["error"] == "challenge_id and otp are required"


def test_otp_generate_route_is_not_exposed(client):
    resp = client.get("/api/v1/otp/generate/u1")
    assert resp.status_code == 404


def test_otp_verify_invalid_challenge(client, monkeypatch):
    monkeypatch.setattr(otp_routes, "verify_otp_challenge", lambda **_kwargs: None)

    resp = client.post(
        "/api/v1/otp/verify",
        json={"challenge_id": "ch-1", "otp": "123456"},
    )
    assert resp.status_code == 401
    assert resp.json["error"] == "Invalid code or expired challenge"


def test_otp_verify_success(client, monkeypatch):
    monkeypatch.setattr(
        otp_routes,
        "verify_otp_challenge",
        lambda **_kwargs: SimpleNamespace(user_id="u1"),
    )
    monkeypatch.setattr(
        otp_routes.AuthService,
        "issue_tokens",
        lambda self, user: {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_in": 900,
        },
    )
    monkeypatch.setattr(otp_routes.AuthService, "refresh_ttl_seconds", 1209600, raising=False)

    resp = client.post(
        "/api/v1/otp/verify",
        json={"challenge_id": "ch-1", "otp": "123456"},
    )
    assert resp.status_code == 200
    assert resp.json["access_token"] == "access-1"
    assert "refresh_token=" in (resp.headers.get("Set-Cookie") or "")
