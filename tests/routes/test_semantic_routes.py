from __future__ import annotations

from datetime import datetime

import app.routes.semantic_registry as semantic_registry
import app.routes.semantic_relationships as semantic_relationships
from app.services.semantic.semantic_registry_service import SemanticRegistryService
from tests._support.fakes import FakeForgeQueryPort


def _headers(monkeypatch):
    from app import factory
    from app.decorators import security
    from app.routes import request_helpers as _route_utils
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
        def list_entries(self, **kwargs):
            return {"rows": [], "total": 0, "page": 1, "page_size": 25}

    monkeypatch.setattr(semantic_registry, "SemanticRegistryService", _Svc)

    resp = client.get("/api/v1/semantic/registry", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["total"] == 0


def test_semantic_registry_list_route_serializes_datetimes(client, monkeypatch):
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 1,
                "vertical": "education",
                "vertical_norm": "education",
                "concept_key": "student.id",
                "semantic_type": "identifier",
                "sub_type": None,
                "entity": "student",
                "description": "Student id",
                "granularity_rank": 0,
                "filter_allowed": 1,
                "group_by_allowed": 1,
                "aggregation_allowed": 0,
                "is_identifier": 1,
                "is_metric": 0,
                "display_priority": 0,
                "sensitive": 0,
                "created_at": datetime(2026, 3, 22, 11, 15, 0),
                "updated_at": datetime(2026, 3, 22, 11, 16, 30),
            }
        ],
        [{"total": 1}],
    ]
    svc = SemanticRegistryService(sql=sql)
    monkeypatch.setattr(semantic_registry, "SemanticRegistryService", lambda: svc)

    resp = client.get("/api/v1/semantic/registry?limit=1", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert "vertical" not in resp.json["rows"][0]
    assert "vertical_norm" not in resp.json["rows"][0]
    assert resp.json["rows"][0]["created_at"] == "2026-03-22T11:15:00"
    assert resp.json["rows"][0]["updated_at"] == "2026-03-22T11:16:30"


def test_semantic_registry_invalid_semantic_type_returns_400(client, monkeypatch):
    resp = client.get("/api/v1/semantic/registry?semantic_type=invalid_type", headers=_headers(monkeypatch))
    assert resp.status_code == 400
    assert "semantic_type" in resp.json["error"]


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
