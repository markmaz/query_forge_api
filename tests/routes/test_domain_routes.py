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


def test_domain_profile_metrics_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def get_profile_metrics(self, *, workspace_id: str, user_id: str, domain_id: int):
            return {
                "domain_id": domain_id,
                "domain_name": "Sales Performance",
                "metrics": [{"metric_key": "total_net_amount", "agg": "sum"}],
                "has_profile": True,
                "can_edit": True,
            }

    monkeypatch.setattr(domain_routes, "DomainProfileMetricConfigService", _Svc)
    resp = client.get("/api/v1/domains/3/profile-metrics", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["domain_id"] == 3
    assert resp.json["metrics"][0]["metric_key"] == "total_net_amount"


def test_domain_profile_metrics_put_success(client, auth_headers, monkeypatch):
    class _Svc:
        def update_profile_metrics(self, *, workspace_id: str, user_id: str, domain_id: int, metrics_payload):
            assert isinstance(metrics_payload, list)
            return {
                "domain_id": domain_id,
                "domain_name": "Sales Performance",
                "metrics": metrics_payload,
                "has_profile": True,
                "can_edit": True,
            }

    monkeypatch.setattr(domain_routes, "DomainProfileMetricConfigService", _Svc)
    resp = client.put(
        "/api/v1/domains/3/profile-metrics",
        headers=auth_headers,
        json={
            "metrics": [
                {
                    "metric_key": "total_net_amount",
                    "label": "Total Net Amount",
                    "kind": "numeric",
                    "agg": "sum",
                    "column_key": "wt180.net_amount",
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json["metrics"][0]["agg"] == "sum"


def test_domain_profile_metrics_put_service_error(client, auth_headers, monkeypatch):
    class _Svc:
        def update_profile_metrics(self, *, workspace_id: str, user_id: str, domain_id: int, metrics_payload):
            raise ForgeError("'metrics' must be a list", status_code=400)

    monkeypatch.setattr(domain_routes, "DomainProfileMetricConfigService", _Svc)
    resp = client.put(
        "/api/v1/domains/3/profile-metrics",
        headers=auth_headers,
        json={"metrics": "bad"},
    )
    assert resp.status_code == 400
    assert "must be a list" in resp.json["error"]
