from __future__ import annotations

import app.features.semantic.semantic_relationships_api as semantic_relationships


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


def test_list_relationships_route(client, monkeypatch):
    class _Svc:
        def list_relationships(self, **kwargs):
            assert kwargs["relationship_type"] == "belongs_to_domain"
            return {
                "rows": [{"id": 11, "relationship_type": "belongs_to_domain"}],
                "total": 1,
                "page": 1,
                "page_size": 25,
            }

    monkeypatch.setattr(semantic_relationships, "SemanticRelationshipService", _Svc)
    resp = client.get(
        "/api/v1/semantic/relationships?relationship_type=belongs_to_domain",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["total"] == 1
    assert resp.json["rows"][0]["id"] == 11


def test_get_relationship_by_id_route(client, monkeypatch):
    class _Svc:
        def get_relationship(self, relationship_id):
            assert relationship_id == 14
            return {
                "id": 14,
                "relationship_type": "default_time_field_for",
                "parent_concept_name": "Total Net Amount",
                "child_concept_name": "Order Date",
                "parent_display_label": "Total Net Amount (TOTAL_NET_AMOUNT)",
                "child_display_label": "Order Date (ORDER_DATE)",
            }

    monkeypatch.setattr(semantic_relationships, "SemanticRelationshipService", _Svc)
    resp = client.get("/api/v1/semantic/relationships/14", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["row"]["id"] == 14
    assert resp.json["row"]["parent_display_label"] == "Total Net Amount (TOTAL_NET_AMOUNT)"


def test_relationship_concept_lookup_route(client, monkeypatch):
    class _Svc:
        def list_concept_lookup(self, **kwargs):
            assert kwargs["q"] == "sales"
            return {
                "rows": [
                    {
                        "id": 1,
                        "concept_key": "TOTAL_NET_AMOUNT",
                        "concept_name": "Total Net Amount",
                        "display_label": "Total Net Amount (TOTAL_NET_AMOUNT)",
                        "semantic_type": "metric",
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 100,
            }

    monkeypatch.setattr(semantic_relationships, "SemanticRelationshipService", _Svc)
    resp = client.get("/api/v1/semantic/relationships/concepts?q=sales", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["rows"][0]["concept_name"] == "Total Net Amount"


def test_patch_relationship_by_id_route(client, monkeypatch):
    class _Svc:
        def patch_relationship(self, relationship_id, payload):
            assert relationship_id == 18
            assert payload["relationship_type"] == "grouped_by_with"
            return {"id": 18, "relationship_type": "grouped_by_with"}

    monkeypatch.setattr(semantic_relationships, "SemanticRelationshipService", _Svc)
    resp = client.patch(
        "/api/v1/semantic/relationships/18",
        json={"relationship_type": "grouped_by_with"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["row"]["relationship_type"] == "grouped_by_with"


def test_delete_relationship_by_id_route(client, monkeypatch):
    class _Svc:
        def delete_relationship(self, relationship_id):
            assert relationship_id == 19
            return None

    monkeypatch.setattr(semantic_relationships, "SemanticRelationshipService", _Svc)
    resp = client.delete("/api/v1/semantic/relationships/19", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["deleted"] is True
