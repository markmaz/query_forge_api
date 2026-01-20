from __future__ import annotations

import app.routes.user_routes as user_routes


def test_users_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def get_users(self, **kwargs):
            return [], None, None, 0

    monkeypatch.setattr(user_routes, "UserService", _Svc)

    resp = client.get("/api/v1/users/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["total_count"] == 0


def test_users_post_validation_error(client, auth_headers):
    resp = client.post("/api/v1/users/", headers=auth_headers, json={"bad": "payload"})
    assert resp.status_code == 400


def test_users_requires_auth(client):
    resp = client.get("/api/v1/users/")
    assert resp.status_code == 403
