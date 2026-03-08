from __future__ import annotations


import app.routes.admin_routes as admin_routes


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


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_healthz(client):
    resp = client.get("/api/v1/admin/healthz")
    assert resp.status_code == 200


def test_detailed_health_returns_checks(client, monkeypatch):
    class _FakeHealthSvc:
        def check_all(self):
            return {
                "overall": "healthy",
                "checks": {
                    "app": {"status": "ok"},
                    "mysql": {"status": "ok", "latency_ms": 1},
                    "vllm": {"status": "ok", "model": "qwen25-7b"},
                    "qdrant": {"status": "ok", "latency_ms": 2},
                },
            }

    monkeypatch.setattr(admin_routes, "AdminHealthService", _FakeHealthSvc)
    resp = client.get("/api/v1/admin/health/detailed", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    data = resp.json
    assert data["overall"] == "healthy"
    assert data["checks"]["mysql"]["status"] == "ok"


def test_detailed_health_degraded(client, monkeypatch):
    class _FakeHealthSvc:
        def check_all(self):
            return {
                "overall": "degraded",
                "checks": {
                    "app": {"status": "ok"},
                    "mysql": {"status": "error", "error": "connection refused"},
                    "vllm": {"status": "ok"},
                    "qdrant": {"status": "ok"},
                },
            }

    monkeypatch.setattr(admin_routes, "AdminHealthService", _FakeHealthSvc)
    resp = client.get("/api/v1/admin/health/detailed", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["overall"] == "degraded"


# ---------------------------------------------------------------------------
# Pipeline profiles
# ---------------------------------------------------------------------------

def test_pipeline_profiles_list(client, monkeypatch):
    class _FakePlannerSvc:
        def list_pipeline_profiles(self, *, limit):
            return [
                {"trace_id": "t-1", "total_ms": 500, "steps": []},
                {"trace_id": "t-2", "total_ms": 300, "steps": []},
            ]

    from app.services import planner_domain as pd_mod
    monkeypatch.setattr(pd_mod, "PlannerDomainService", _FakePlannerSvc)
    resp = client.get("/api/v1/admin/pipeline-profiles", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["count"] == 2


# ---------------------------------------------------------------------------
# Prompt feedback admin
# ---------------------------------------------------------------------------

def test_admin_prompt_feedback_list(client, monkeypatch):
    class _FakeSvc:
        def list_feedback(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            assert kwargs["limit"] == 25
            assert kwargs["offset"] == 10
            assert kwargs["include_payload"] is True
            return {
                "rows": [{"id": 1, "vote": "up"}],
                "count": 1,
                "total": 1,
                "limit": 25,
                "offset": 10,
            }

    monkeypatch.setattr(admin_routes, "PromptFeedbackService", _FakeSvc)
    resp = client.get(
        "/api/v1/admin/prompt-feedback?limit=25&offset=10&include_payload=true",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["count"] == 1
    assert resp.json["rows"][0]["id"] == 1


def test_admin_prompt_feedback_delete(client, monkeypatch):
    class _FakeSvc:
        def delete_feedback(self, *, workspace_id, feedback_id):
            assert workspace_id == "ws-1"
            assert feedback_id == 22
            return type("DeleteResult", (), {"id": 22, "deleted": True})()

    monkeypatch.setattr(admin_routes, "PromptFeedbackService", _FakeSvc)
    resp = client.delete(
        "/api/v1/admin/prompt-feedback/22",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["deleted"] is True
    assert resp.json["id"] == 22


# ---------------------------------------------------------------------------
# Domain profiles CRUD
# ---------------------------------------------------------------------------

def test_domain_profile_list(client, monkeypatch):
    class _FakeSvc:
        def list_profiles(self, workspace_id):
            return [{"id": 1, "workspace_id": workspace_id, "domain_id": 4}]

    monkeypatch.setattr(admin_routes, "DomainProfileService", _FakeSvc)
    resp = client.get("/api/v1/admin/domain-profiles", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["count"] == 1


def test_domain_profile_get(client, monkeypatch):
    class _FakeSvc:
        def get_profile(self, workspace_id, domain_id):
            return {"id": 1, "workspace_id": workspace_id, "domain_id": domain_id, "summary": "test"}

    monkeypatch.setattr(admin_routes, "DomainProfileService", _FakeSvc)
    resp = client.get("/api/v1/admin/domain-profiles/4", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["domain_id"] == 4


def test_domain_profile_create(client, monkeypatch):
    class _FakeSvc:
        def create_profile(self, req):
            return {"id": 1, "workspace_id": req.workspace_id, "domain_id": req.domain_id}

    monkeypatch.setattr(admin_routes, "DomainProfileService", _FakeSvc)
    resp = client.post(
        "/api/v1/admin/domain-profiles",
        json={"domain_id": 4, "summary": "New profile"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201


def test_domain_profile_update(client, monkeypatch):
    class _FakeSvc:
        def update_profile(self, workspace_id, domain_id, req):
            return {"id": 1, "workspace_id": workspace_id, "domain_id": domain_id, "summary": req.summary}

    monkeypatch.setattr(admin_routes, "DomainProfileService", _FakeSvc)
    resp = client.put(
        "/api/v1/admin/domain-profiles/4",
        json={"summary": "Updated"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["summary"] == "Updated"


def test_domain_profile_delete(client, monkeypatch):
    class _FakeSvc:
        def delete_profile(self, workspace_id, domain_id):
            return {"deleted": True, "workspace_id": workspace_id, "domain_id": domain_id}

    monkeypatch.setattr(admin_routes, "DomainProfileService", _FakeSvc)
    resp = client.delete("/api/v1/admin/domain-profiles/4", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["deleted"] is True


# ---------------------------------------------------------------------------
# Vector rebuild
# ---------------------------------------------------------------------------

def test_vector_rebuild_all(client, monkeypatch):
    class _FakeSemanticSvc:
        def rebuild_semantic_concept_index(self, vertical_norm=None):
            return {"conceptPoints": 10, "aliasPoints": 5}

    class _FakeEmbeddingSvc:
        def rebuild_index(self, include_tables=True, limit=0, workspace_id=None):
            return {"tablesIndexed": 3, "columnsIndexed": 20}

    class _FakeDomainVectorSvc:
        def reindex_domains(self, workspace_id=None, vertical_norm=None, force=False, json_fallback_path=None):
            return {"upserted": 8, "skipped": 0}

    monkeypatch.setattr(admin_routes, "SemanticConceptEmbeddingService", _FakeSemanticSvc)
    monkeypatch.setattr(admin_routes, "EmbeddingIndexService", _FakeEmbeddingSvc)
    monkeypatch.setattr(admin_routes, "DomainVectorIndexService", _FakeDomainVectorSvc)

    resp = client.post(
        "/api/v1/admin/vector/rebuild-all",
        json={"vertical_norm": "education", "force": True},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    data = resp.json
    assert data["status"] == "completed"
    assert "semantic_concepts" in data["results"]
    assert "embeddings" in data["results"]
    assert "domain_vectors" in data["results"]
    assert data["errors"] == {}


def test_vector_embeddings_rebuild(client, monkeypatch):
    class _FakeEmbeddingSvc:
        def rebuild_index(self, include_tables=True, limit=0, workspace_id=None):
            return {"tablesIndexed": 5, "columnsIndexed": 30}

    monkeypatch.setattr(admin_routes, "EmbeddingIndexService", _FakeEmbeddingSvc)
    resp = client.post(
        "/api/v1/admin/vector/embeddings/rebuild",
        json={},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["result"]["tablesIndexed"] == 5


# ---------------------------------------------------------------------------
# Auth checks
# ---------------------------------------------------------------------------

def test_detailed_health_requires_admin(client, monkeypatch):
    from app import factory
    from app.decorators import security
    from app.routes import request_helpers as _route_utils
    from app.services.workspace_inventory import workspace_context

    def _verify_token(_token):
        return {"sub": "user-1", "username": "user-1", "is_admin": False}

    def _allow_workspace_access(*, user_id, workspace_id):
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

    resp = client.get(
        "/api/v1/admin/health/detailed",
        headers={"Authorization": "Bearer test-token", "X-Workspace-Id": "ws-1"},
    )
    assert resp.status_code == 403


def test_prompt_feedback_list_requires_admin(client, monkeypatch):
    from app import factory
    from app.decorators import security
    from app.routes import request_helpers as _route_utils
    from app.services.workspace_inventory import workspace_context

    def _verify_token(_token):
        return {"sub": "user-1", "username": "user-1", "is_admin": False}

    def _allow_workspace_access(*, user_id, workspace_id):
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

    resp = client.get(
        "/api/v1/admin/prompt-feedback",
        headers={"Authorization": "Bearer test-token", "X-Workspace-Id": "ws-1"},
    )
    assert resp.status_code == 403
