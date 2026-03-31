from __future__ import annotations

import app.features.vector.domain_profile_embeddings_api as routes


def _headers(monkeypatch):
    from app import factory
    from app.decorators import security
    from app.routes import request_helpers as route_helpers
    from app.services.workspace_inventory import workspace_context

    def _verify_token(_token):
        return {"sub": "user-1", "username": "user-1", "is_admin": True}

    def _allow_workspace_access(*, user_id, workspace_id):
        del user_id
        return workspace_id

    monkeypatch.setattr(security.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(factory.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(security.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(route_helpers.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
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


def test_generate_one_route(client, monkeypatch):
    class _FakeService:
        def generate_one(self, *, workspace_id, domain_id, force=False):
            assert workspace_id == "ws-1"
            assert domain_id == 5
            assert force is True
            return {"domain_id": 5, "status": "generated"}

    monkeypatch.setattr(routes, "DomainProfileEmbeddingService", _FakeService)
    resp = client.post(
        "/api/v1/domain-profiles/5/generate",
        json={"force": True},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["result"]["status"] == "generated"


def test_generate_batch_route(client, monkeypatch):
    class _FakeService:
        def generate_many(self, *, workspace_id, domain_ids, force=False):
            assert workspace_id == "ws-1"
            assert domain_ids == [5, 6]
            assert force is False
            return {"total": 2, "generated": 2, "failed": 0, "results": []}

    monkeypatch.setattr(routes, "DomainProfileEmbeddingService", _FakeService)
    resp = client.post(
        "/api/v1/domain-profiles/generate",
        json={"domain_ids": [5, 6]},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["total"] == 2


def test_generate_all_route(client, monkeypatch):
    class _FakeService:
        def generate_all(self, *, workspace_id, force=False, include_inactive=False):
            assert workspace_id == "ws-1"
            assert force is True
            assert include_inactive is True
            return {"total": 3, "generated": 3, "failed": 0, "results": []}

    monkeypatch.setattr(routes, "DomainProfileEmbeddingService", _FakeService)
    resp = client.post(
        "/api/v1/domain-profiles/generate-all",
        json={"force": True, "include_inactive": True},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["generated"] == 3


def test_routes_require_admin(client, monkeypatch):
    from app import factory
    from app.decorators import security
    from app.routes import request_helpers as route_helpers
    from app.services.workspace_inventory import workspace_context

    def _verify_token(_token):
        return {"sub": "user-1", "username": "user-1", "is_admin": False}

    def _allow_workspace_access(*, user_id, workspace_id):
        return workspace_id

    monkeypatch.setattr(security.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(factory.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(security.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(route_helpers.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(
        workspace_context.WorkspaceAccessService,
        "assert_workspace_access",
        lambda self, *, user_id, workspace_id: workspace_id,
    )

    resp = client.post(
        "/api/v1/domain-profiles/generate-all",
        json={},
        headers={"Authorization": "Bearer test-token", "X-Workspace-Id": "ws-1", "X-User-Id": "user-1"},
    )
    assert resp.status_code == 403
