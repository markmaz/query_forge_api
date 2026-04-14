from __future__ import annotations

import app.routes.admin_routes as admin_routes


def _headers(monkeypatch, *, is_admin: bool = True):
    from app import factory
    from app.decorators import security
    from app.routes import request_helpers as _route_utils
    from app.services.workspace_inventory import workspace_context

    def _verify_token(_token):
        return {"sub": "user-1", "username": "user-1", "is_admin": is_admin}

    def _allow_workspace_access(*, user_id, workspace_id):
        del user_id
        return workspace_id

    monkeypatch.setattr(security.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(factory.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(security.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(_route_utils.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(
        workspace_context.WorkspaceAccessService,
        "assert_workspace_access",
        lambda self, *, user_id, workspace_id: workspace_id,
    )
    return {
        "Authorization": "Bearer test-token",
        "X-Workspace-Id": "ws-1",
        "X-User-Id": "user-1",
    }


def test_admin_domain_reindex_uses_workspace_header(client, monkeypatch):
    class _Svc:
        def reindex_domains(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            assert "vertical_norm" not in kwargs
            return {"upserted": 3}

    monkeypatch.setattr(admin_routes, "DomainVectorIndexService", _Svc)

    resp = client.post(
        "/api/v1/admin/vector/domains/reindex",
        json={"force": True},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["result"]["upserted"] == 3


def test_admin_domain_reindex_rejects_workspace_id_in_body(client, monkeypatch):
    resp = client.post(
        "/api/v1/admin/vector/domains/reindex",
        json={"workspace_id": "ws-2"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 400
    assert "X-Workspace-Id header" in str(resp.json.get("error") or "")


def test_admin_domain_reindex_returns_underlying_error_details(client, monkeypatch):
    class _Svc:
        def reindex_domains(self, **kwargs):
            del kwargs
            raise RuntimeError("qdrant unavailable")

    monkeypatch.setattr(admin_routes, "DomainVectorIndexService", _Svc)

    resp = client.post(
        "/api/v1/admin/vector/domains/reindex",
        json={},
        headers=_headers(monkeypatch),
    )

    assert resp.status_code == 500
    assert resp.json["error"] == "domain vector reindex failed"
    assert "qdrant unavailable" in str(resp.json.get("details") or "")
