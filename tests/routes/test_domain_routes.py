from __future__ import annotations

import app.routes.domain_routes as domain_routes
from app.exceptions.service_error import ServiceError


def test_domains_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def list_user_domains(self, *, workspace_id: str, user_id: str):
            return [{"id": 1, "name": "Domain"}]

    monkeypatch.setattr(domain_routes, "UserDomainReadService", _Svc)

    resp = client.get("/api/v1/domains/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["rows"][0]["name"] == "Domain"


def test_domains_get_missing_workspace(client, auth_headers):
    headers = {k: v for k, v in auth_headers.items() if k.lower() != "x-workspace-id"}
    resp = client.get("/api/v1/domains/", headers=headers)
    assert resp.status_code == 400
    assert "Missing X-Workspace-Id" in resp.json["error"]


def test_domains_get_service_error(client, auth_headers, monkeypatch):
    class _Svc:
        def list_user_domains(self, *, workspace_id: str, user_id: str):
            raise ServiceError("nope", status_code=418)

    monkeypatch.setattr(domain_routes, "UserDomainReadService", _Svc)

    resp = client.get("/api/v1/domains/", headers=auth_headers)
    assert resp.status_code == 418
    assert resp.json["error"] == "nope"


def test_domains_requires_auth(client):
    resp = client.get("/api/v1/domains/")
    assert resp.status_code == 403


def test_domains_invalid_token(client, invalid_auth_headers):
    resp = client.get("/api/v1/domains/", headers=invalid_auth_headers)
    assert resp.status_code == 401
