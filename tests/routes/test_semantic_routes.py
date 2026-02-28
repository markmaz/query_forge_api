from __future__ import annotations

import app.routes.semantic_mappings as semantic_mappings
import app.routes.semantic_registry as semantic_registry
import app.routes.semantic_relationships as semantic_relationships


def _headers(monkeypatch):
    from app import factory
    from app.decorators import security
    from app.routes import _route_utils
    from app.services.workspace_inventory import workspace_context

    def _verify_token(_token):
        return {"sub": "user-1", "username": "user-1", "is_admin": True}

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


def test_semantic_registry_list_route(client, monkeypatch):
    class _Svc:
        def list_entries(self, **_kwargs):
            return {"rows": [], "total": 0, "page": 1, "page_size": 25}

    monkeypatch.setattr(semantic_registry, "SemanticRegistryService", _Svc)

    resp = client.get("/api/v1/semantic/registry", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["total"] == 0


def test_semantic_registry_invalid_semantic_type_returns_400(client, monkeypatch):
    resp = client.get("/api/v1/semantic/registry?semantic_type=invalid_type", headers=_headers(monkeypatch))
    assert resp.status_code == 400
    assert "semantic_type" in resp.json["error"]


def test_semantic_mapping_create_route(client, monkeypatch):
    class _Svc:
        def create_mapping(self, payload):
            return {"id": 1, **payload}

    monkeypatch.setattr(semantic_mappings, "SemanticMappingService", _Svc)

    resp = client.post(
        "/api/v1/semantic/mappings",
        json={"semantic_registry_id": 7, "model_column_id": 8},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201
    assert resp.json["row"]["id"] == 1


def test_semantic_relationship_create_route(client, monkeypatch):
    class _Svc:
        def create_relationship(self, payload):
            return {"id": 2, **payload}

    monkeypatch.setattr(semantic_relationships, "SemanticRelationshipService", _Svc)

    resp = client.post(
        "/api/v1/semantic/relationships",
        json={"parent_concept_id": 1, "child_concept_id": 2, "relationship_type": "parent_of"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201
    assert resp.json["row"]["id"] == 2
