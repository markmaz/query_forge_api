from __future__ import annotations

import app.routes.version_routes as version_routes
from app.exceptions.forge_error import ForgeError


def test_version_route_success(client, monkeypatch):
    class _Svc:
        def get_version_payload(self):
            return {"version": "1.2.3"}

    monkeypatch.setattr(version_routes, "VersionService", _Svc)
    resp = client.get("/api/v1/version/")
    assert resp.status_code == 200
    assert resp.json == {"version": "1.2.3"}


def test_version_route_service_error(client, monkeypatch):
    class _Svc:
        def get_version_payload(self):
            raise ForgeError("version.json not found", status_code=500)

    monkeypatch.setattr(version_routes, "VersionService", _Svc)
    resp = client.get("/api/v1/version/")
    assert resp.status_code == 500
    assert "version.json not found" in resp.json["error"]

