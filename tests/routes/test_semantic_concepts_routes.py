from __future__ import annotations

import app.routes.semantic_concepts as semantic_concepts


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


def test_list_concepts_route(client, monkeypatch):
    class _Svc:
        def list_concepts(self, **kwargs):
            return {
                "rows": [{"id": 1, "concept_key": "SCHOOL_YEAR", "vertical_norm": "generic"}],
                "total": 1,
                "page": kwargs["page"],
                "page_size": kwargs["page_size"],
            }

    monkeypatch.setattr(semantic_concepts, "SemanticConceptService", _Svc)

    resp = client.get("/api/v1/semantic/concepts?page=1&page_size=10", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["total"] == 1
    assert resp.json["rows"][0]["concept_key"] == "SCHOOL_YEAR"
    assert "vertical_norm" not in resp.json["rows"][0]


def test_list_concept_keys_route(client, monkeypatch):
    class _Svc:
        def list_concept_keys(self, **kwargs):
            return {"concept_keys": ["ATTENDANCE_RATE", "SCHOOL_YEAR"]}

    monkeypatch.setattr(semantic_concepts, "SemanticConceptService", _Svc)

    resp = client.get("/api/v1/semantic/concepts/keys", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["concept_keys"] == ["ATTENDANCE_RATE", "SCHOOL_YEAR"]


def test_create_concept_requires_admin(client, monkeypatch):
    resp = client.post(
        "/api/v1/semantic/concepts",
        json={
            "vertical_norm": "education",
            "concept_key": "SCHOOL_YEAR",
            "name": "School Year",
            "semantic_type": "time",
        },
        headers=_headers(monkeypatch, is_admin=False),
    )
    assert resp.status_code == 403


def test_create_alias_route(client, monkeypatch):
    class _Svc:
        def create_alias(self, payload):
            return {"id": 9, **payload}

    monkeypatch.setattr(semantic_concepts, "SemanticConceptService", _Svc)

    resp = client.post(
        "/api/v1/semantic/concept-aliases",
        json={
            "vertical_norm": "education",
            "alias_key": "k_school",
            "concept_key": "SCHOOL_ID",
            "match_kind": "exact",
            "weight": 1.0,
        },
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201
    assert resp.json["row"]["id"] == 9


def test_seed_route(client, monkeypatch):
    class _Svc:
        def seed(self):
            return {"vertical_norm": "generic", "concepts_created": 1, "aliases_created": 1}

    monkeypatch.setattr(semantic_concepts, "SemanticConceptService", _Svc)

    resp = client.post(
        "/api/v1/semantic/concepts/seed",
        json={},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert "vertical_norm" not in resp.json["result"]


def test_rebuild_index_route(client, monkeypatch):
    class _EmbedSvc:
        def rebuild_semantic_concept_index(self, *, vertical_norm):
            return {"collection": "semantic_concepts_v1", "points_upserted": 10, "vertical_norm": vertical_norm}

    monkeypatch.setattr(semantic_concepts, "SemanticConceptEmbeddingService", _EmbedSvc)

    resp = client.post(
        "/api/v1/semantic/concepts/rebuild-index",
        json={},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert "vertical_norm" not in resp.json["result"]
    assert resp.json["result"]["points_upserted"] == 10


def test_backfill_primary_keys_route(client, monkeypatch):
    class _Svc:
        def backfill_primary_semantic_keys(self, *, workspace_id, dry_run):
            assert workspace_id == "ws-1"
            assert dry_run is True
            return {
                "workspace_id": workspace_id,
                "vertical_norm": "generic",
                "dry_run": dry_run,
                "candidates": 4,
                "updated": 0,
            }

    monkeypatch.setattr(semantic_concepts, "SemanticConceptService", _Svc)

    resp = client.post(
        "/api/v1/semantic/concepts/backfill-primary-keys",
        json={"workspace_id": "ws-1", "dry_run": True},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["result"]["candidates"] == 4


def test_delete_concept_route(client, monkeypatch):
    class _Svc:
        def delete_concept(self, concept_id):
            assert concept_id == 7
            return None

    monkeypatch.setattr(semantic_concepts, "SemanticConceptService", _Svc)

    resp = client.delete("/api/v1/semantic/concepts/7", headers=_headers(monkeypatch))
    assert resp.status_code == 204


def test_alias_crud_routes(client, monkeypatch):
    class _Svc:
        def patch_alias(self, alias_id, payload):
            return {"id": alias_id, **payload}

        def delete_alias(self, alias_id):
            assert alias_id == 9
            return None

    monkeypatch.setattr(semantic_concepts, "SemanticConceptService", _Svc)

    patch_resp = client.patch(
        "/api/v1/semantic/concept-aliases/9",
        json={"weight": 0.9},
        headers=_headers(monkeypatch),
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json["row"]["weight"] == 0.9

    delete_resp = client.delete("/api/v1/semantic/concept-aliases/9", headers=_headers(monkeypatch))
    assert delete_resp.status_code == 204


def test_value_alias_crud_routes(client, monkeypatch):
    class _Svc:
        def list_value_aliases(self, **kwargs):
            return {
                "rows": [{"id": 1, "semantic_concept_id": 10, "concept_name": "District Name"}],
                "total": 1,
                "page": kwargs["page"],
                "page_size": kwargs["page_size"],
            }

        def create_value_alias(self, payload):
            return {"id": 2, **payload}

        def patch_value_alias(self, value_alias_id, payload):
            return {"id": value_alias_id, **payload}

        def delete_value_alias(self, value_alias_id):
            assert value_alias_id == 2
            return None

    monkeypatch.setattr(semantic_concepts, "SemanticConceptService", _Svc)

    list_resp = client.get("/api/v1/semantic/value-aliases?page=1&page_size=10", headers=_headers(monkeypatch))
    assert list_resp.status_code == 200
    assert list_resp.json["total"] == 1
    assert list_resp.json["rows"][0]["concept_name"] == "District Name"

    create_resp = client.post(
        "/api/v1/semantic/value-aliases",
        json={
            "vertical_norm": "education",
            "semantic_concept_id": 10,
            "canonical_value": "Metro District",
            "alias_value": "metro district",
        },
        headers=_headers(monkeypatch),
    )
    assert create_resp.status_code == 201
    assert create_resp.json["row"]["id"] == 2

    patch_resp = client.patch(
        "/api/v1/semantic/value-aliases/2",
        json={"weight": 0.7},
        headers=_headers(monkeypatch),
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json["row"]["weight"] == 0.7

    delete_resp = client.delete("/api/v1/semantic/value-aliases/2", headers=_headers(monkeypatch))
    assert delete_resp.status_code == 204


def test_concept_column_map_crud_routes(client, monkeypatch):
    class _Svc:
        def list_concept_column_maps(self, **kwargs):
            assert kwargs["concept_key"] == "district"
            assert kwargs["column_name"] == "lea"
            assert kwargs["q"] == "district"
            assert kwargs["workspace_column_id"] == 88
            return {"rows": [{"id": 5}], "total": 1, "page": kwargs["page"], "page_size": kwargs["page_size"]}

        def create_concept_column_map(self, payload):
            return {"id": 6, **payload}

        def patch_concept_column_map(self, map_id, payload):
            return {"id": map_id, **payload}

        def delete_concept_column_map(self, map_id):
            assert map_id == 6
            return None

    monkeypatch.setattr(semantic_concepts, "SemanticConceptService", _Svc)

    list_resp = client.get(
        "/api/v1/semantic/concept-column-maps?page=1&page_size=10&concept_key=district&column_name=lea&q=district&workspace_column_id=88",
        headers=_headers(monkeypatch),
    )
    assert list_resp.status_code == 200
    assert list_resp.json["total"] == 1

    create_resp = client.post(
        "/api/v1/semantic/concept-column-maps",
        json={
            "vertical_norm": "education",
            "semantic_concept_id": 10,
            "workspace_column_id": 88,
        },
        headers=_headers(monkeypatch),
    )
    assert create_resp.status_code == 201
    assert create_resp.json["row"]["id"] == 6
    assert create_resp.json["row"]["workspace_column_id"] == 88

    patch_resp = client.patch(
        "/api/v1/semantic/concept-column-maps/6",
        json={"weight": 0.5},
        headers=_headers(monkeypatch),
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json["row"]["weight"] == 0.5

    delete_resp = client.delete("/api/v1/semantic/concept-column-maps/6", headers=_headers(monkeypatch))
    assert delete_resp.status_code == 204
