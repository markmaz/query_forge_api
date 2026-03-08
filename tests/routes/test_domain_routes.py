from __future__ import annotations

import app.routes.domain_routes as domain_routes
from app.exceptions.forge_error import ForgeError


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


def test_domains_get_forbidden_workspace(client, monkeypatch):
    import app.decorators.security as security

    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "username": "user-1"},
    )

    def _deny_workspace_access(*, user_id: str, workspace_id: str) -> str:
        raise ForgeError("You do not have access to this workspace", status_code=403)

    monkeypatch.setattr(
        "app.decorators.security.workspace_access_service.assert_workspace_access",
        _deny_workspace_access,
    )

    resp = client.get(
        "/api/v1/domains/",
        headers={"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-2"},
    )
    assert resp.status_code == 403
    assert "workspace" in resp.json["error"].lower()


def test_domains_get_service_error(client, auth_headers, monkeypatch):
    class _Svc:
        def list_user_domains(self, *, workspace_id: str, user_id: str):
            raise ForgeError("nope", status_code=418)

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
