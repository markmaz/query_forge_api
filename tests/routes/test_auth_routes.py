from __future__ import annotations

from typing import Any, Dict

import app.routes.auth_routes as auth_routes


def test_login_success(client, monkeypatch):
    def _auth(self, username: str, password: str) -> Dict[str, Any]:
        return {"token": "t"}

    monkeypatch.setattr(auth_routes.AuthService, "authenticate", _auth)

    resp = client.post("/api/v1/auth/login", json={"username": "u", "password": "p"})
    assert resp.status_code == 200
    assert resp.json["token"] == "t"


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
