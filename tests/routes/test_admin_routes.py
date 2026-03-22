from __future__ import annotations


import app.routes.admin_routes as admin_routes


def _headers(monkeypatch, *, is_admin: bool = True, roles: set[str] | None = None):
    from app import factory
    from app.decorators import security
    from app.routes import request_helpers as _route_utils
    import app.services.rbac_service as rbac_service
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
    monkeypatch.setattr(
        rbac_service,
        "get_effective_roles",
        lambda user_id, workspace_id=None: set({"super_admin"} if roles is None else roles),
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
                    "broker": {"status": "ok", "ok": True},
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
                    "broker": {"status": "error", "ok": False},
                },
            }

    monkeypatch.setattr(admin_routes, "AdminHealthService", _FakeHealthSvc)
    resp = client.get("/api/v1/admin/health/detailed", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["overall"] == "degraded"


def test_detailed_health_allows_workspace_admin(client, monkeypatch):
    class _FakeHealthSvc:
        def check_all(self):
            return {"overall": "healthy", "checks": {"app": {"status": "ok"}}}

    monkeypatch.setattr(admin_routes, "AdminHealthService", _FakeHealthSvc)
    resp = client.get(
        "/api/v1/admin/health/detailed",
        headers=_headers(monkeypatch, is_admin=False, roles={"workspace_admin"}),
    )
    assert resp.status_code == 200
    assert resp.json["overall"] == "healthy"


def test_broker_health_returns_status(client, monkeypatch):
    class _FakeHealthSvc:
        def check_broker(self):
            return {
                "ok": True,
                "broker_url": "redis://localhost:6379/0",
                "valkey": {"ping_ok": True},
                "celery": {"broker_connect_ok": True, "worker_ping_ok": True, "workers": ["celery@host"]},
            }

    monkeypatch.setattr(admin_routes, "AdminHealthService", _FakeHealthSvc)
    resp = client.get("/api/v1/admin/health/broker", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["ok"] is True


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


def test_pipeline_profiles_list_allows_workspace_admin(client, monkeypatch):
    class _FakePlannerSvc:
        def list_pipeline_profiles(self, *, limit):
            assert limit == 50
            return [{"trace_id": "t-1", "total_ms": 500, "steps": []}]

    from app.services import planner_domain as pd_mod

    monkeypatch.setattr(pd_mod, "PlannerDomainService", _FakePlannerSvc)
    resp = client.get(
        "/api/v1/admin/pipeline-profiles?limit=50",
        headers=_headers(monkeypatch, is_admin=False, roles={"workspace_admin"}),
    )
    assert resp.status_code == 200
    assert resp.json["count"] == 1


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


def test_admin_prompt_feedback_list_allows_workspace_admin(client, monkeypatch):
    class _FakeSvc:
        def list_feedback(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            return {
                "rows": [{"id": 1, "vote": "up"}],
                "count": 1,
                "total": 1,
                "limit": 100,
                "offset": 0,
            }

    monkeypatch.setattr(admin_routes, "PromptFeedbackService", _FakeSvc)
    resp = client.get(
        "/api/v1/admin/prompt-feedback",
        headers=_headers(monkeypatch, is_admin=False, roles={"workspace_admin"}),
    )
    assert resp.status_code == 200
    assert resp.json["count"] == 1


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


def test_domain_profile_list_allows_workspace_admin(client, monkeypatch):
    class _FakeSvc:
        def list_profiles(self, workspace_id):
            return [{"id": 1, "workspace_id": workspace_id, "domain_id": 4}]

    monkeypatch.setattr(admin_routes, "DomainProfileService", _FakeSvc)
    resp = client.get(
        "/api/v1/admin/domain-profiles",
        headers=_headers(monkeypatch, is_admin=False, roles={"workspace_admin"}),
    )
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


def test_domain_profile_generate_one(client, monkeypatch):
    class _FakeSvc:
        def generate_one(self, *, workspace_id, domain_id, force=False):
            assert workspace_id == "ws-1"
            assert domain_id == 4
            assert force is True
            return {"domain_id": 4, "status": "generated"}

    monkeypatch.setattr(admin_routes, "DomainProfileEmbeddingService", _FakeSvc)
    resp = client.post(
        "/api/v1/admin/domain-profiles/4/generate",
        json={"force": True},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["result"]["status"] == "generated"


def test_domain_profile_generate_batch(client, monkeypatch):
    class _FakeSvc:
        def generate_many(self, *, workspace_id, domain_ids, force=False):
            assert workspace_id == "ws-1"
            assert domain_ids == [4, 7]
            assert force is False
            return {"total": 2, "generated": 2, "failed": 0, "results": []}

    monkeypatch.setattr(admin_routes, "DomainProfileEmbeddingService", _FakeSvc)
    resp = client.post(
        "/api/v1/admin/domain-profiles/generate",
        json={"domain_ids": [4, 7]},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["total"] == 2


def test_domain_profile_generate_all(client, monkeypatch):
    class _FakeSvc:
        def generate_all(self, *, workspace_id, force=False, include_inactive=False):
            assert workspace_id == "ws-1"
            assert force is True
            assert include_inactive is True
            return {"total": 3, "generated": 2, "failed": 1, "results": []}

    monkeypatch.setattr(admin_routes, "DomainProfileEmbeddingService", _FakeSvc)
    resp = client.post(
        "/api/v1/admin/domain-profiles/generate-all",
        json={"force": True, "include_inactive": True},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["total"] == 3


# ---------------------------------------------------------------------------
# Semantic catalog build
# ---------------------------------------------------------------------------

def test_semantic_catalog_build_dry_run(client, monkeypatch):
    class _FakeBuilder:
        def build_catalog(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            assert kwargs["domain_id"] == 3
            assert kwargs["vertical_norm"] == "generic"
            assert kwargs["dry_run"] is True
            return {
                "workspace_id": "ws-1",
                "domain_id": 3,
                "vertical_norm": "generic",
                "dry_run": True,
                "profile_count": 12,
            }

    monkeypatch.setattr(admin_routes, "SemanticCatalogBuilder", _FakeBuilder)
    resp = client.post(
        "/api/v1/admin/semantic-catalog/build",
        json={"domain_id": 3},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["result"]["dry_run"] is True
    assert resp.json["result"]["domain_id"] == 3


def test_semantic_catalog_build_write_mode(client, monkeypatch):
    class _FakeBuilder:
        def build_catalog(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            assert kwargs["domain_id"] == 9
            assert kwargs["vertical_norm"] == "sales"
            assert kwargs["domain_name"] == "Sales Performance"
            assert kwargs["dry_run"] is False
            assert kwargs["table_limit"] == 1200
            return {
                "workspace_id": "ws-1",
                "domain_id": 9,
                "vertical_norm": "sales",
                "dry_run": False,
                "concepts_upserted": 24,
            }

    monkeypatch.setattr(admin_routes, "SemanticCatalogBuilder", _FakeBuilder)
    resp = client.post(
        "/api/v1/admin/semantic-catalog/build",
        json={
            "workspace_id": "ws-1",
            "domain_id": 9,
            "vertical_norm": "sales",
            "domain_name": "Sales Performance",
            "dry_run": False,
            "table_limit": 1200,
        },
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["result"]["dry_run"] is False
    assert resp.json["result"]["concepts_upserted"] == 24


def test_semantic_catalog_build_allows_workspace_admin(client, monkeypatch):
    class _FakeBuilder:
        def build_catalog(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            assert kwargs["domain_id"] == 5
            return {
                "workspace_id": "ws-1",
                "domain_id": 5,
                "dry_run": True,
            }

    monkeypatch.setattr(admin_routes, "SemanticCatalogBuilder", _FakeBuilder)
    resp = client.post(
        "/api/v1/admin/semantic-catalog/build",
        json={"domain_id": 5},
        headers=_headers(monkeypatch, is_admin=False, roles={"workspace_admin"}),
    )
    assert resp.status_code == 200
    assert resp.json["result"]["workspace_id"] == "ws-1"


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


def test_vector_semantic_concepts_rebuild_allows_workspace_admin(client, monkeypatch):
    class _FakeSemanticSvc:
        def rebuild_semantic_concept_index(self, vertical_norm=None):
            assert vertical_norm == "education"
            return {"conceptPoints": 10, "aliasPoints": 5}

    monkeypatch.setattr(admin_routes, "SemanticConceptEmbeddingService", _FakeSemanticSvc)
    resp = client.post(
        "/api/v1/admin/vector/semantic-concepts/rebuild",
        json={"vertical_norm": "education"},
        headers=_headers(monkeypatch, is_admin=False, roles={"workspace_admin"}),
    )
    assert resp.status_code == 200
    assert resp.json["vertical_norm"] == "education"
    assert resp.json["result"]["conceptPoints"] == 10


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


def test_vector_embeddings_rebuild_allows_workspace_admin(client, monkeypatch):
    class _FakeEmbeddingSvc:
        def rebuild_index(self, include_tables=True, limit=0, workspace_id=None):
            assert include_tables is True
            assert limit == 0
            assert workspace_id == "ws-1"
            return {"tablesIndexed": 5, "columnsIndexed": 30}

    monkeypatch.setattr(admin_routes, "EmbeddingIndexService", _FakeEmbeddingSvc)
    resp = client.post(
        "/api/v1/admin/vector/embeddings/rebuild",
        json={},
        headers=_headers(monkeypatch, is_admin=False, roles={"workspace_admin"}),
    )
    assert resp.status_code == 200
    assert resp.json["result"]["tablesIndexed"] == 5


def test_vector_domains_reindex_allows_workspace_admin(client, monkeypatch):
    class _FakeDomainVectorSvc:
        def reindex_domains(self, workspace_id=None, vertical_norm=None, force=False, json_fallback_path=None):
            assert workspace_id == "ws-1"
            assert vertical_norm == "education"
            assert force is True
            assert json_fallback_path is None
            return {"upserted": 8, "skipped": 0}

    monkeypatch.setattr(admin_routes, "DomainVectorIndexService", _FakeDomainVectorSvc)
    resp = client.post(
        "/api/v1/admin/vector/domains/reindex",
        json={"vertical_norm": "education", "force": True},
        headers=_headers(monkeypatch, is_admin=False, roles={"workspace_admin"}),
    )
    assert resp.status_code == 200
    assert resp.json["result"]["upserted"] == 8


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


# ---------------------------------------------------------------------------
# Tenancy admin routes
# ---------------------------------------------------------------------------

def test_admin_organizations_list(client, monkeypatch):
    class _FakeSvc:
        def list_organizations(self, **kwargs):
            assert kwargs["include_inactive"] is True
            return {"rows": [{"id": "org-1", "name": "Acme"}], "count": 1, "total": 1, "limit": 100, "offset": 0}

    monkeypatch.setattr(admin_routes, "TenancyAdminService", _FakeSvc)
    resp = client.get("/api/v1/admin/organizations?include_inactive=true", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["count"] == 1
    assert resp.json["rows"][0]["id"] == "org-1"


def test_admin_organizations_list_allows_workspace_admin_in_current_workspace_scope(client, monkeypatch):
    class _FakeSvc:
        def get_workspace_binding(self, workspace_id):
            assert workspace_id == "ws-1"
            return {"workspace_id": "ws-1", "organization_id": "org-1"}

        def get_organization(self, organization_id):
            assert organization_id == "org-1"
            return {"id": "org-1", "name": "Acme", "slug": "acme", "is_active": True}

    monkeypatch.setattr(admin_routes, "TenancyAdminService", _FakeSvc)
    resp = client.get(
        "/api/v1/admin/organizations?include_inactive=true",
        headers=_headers(monkeypatch, is_admin=False, roles={"workspace_admin"}),
    )
    assert resp.status_code == 200
    assert resp.json["count"] == 1
    assert resp.json["rows"][0]["id"] == "org-1"


def test_admin_tenancy_bootstrap_route(client, monkeypatch):
    class _FakeBootstrapSvc:
        def bootstrap(self, req):
            assert req.workspace_id == "ws-1"
            assert req.organization_name == "Acme District"
            assert req.datasource_type == "snowflake"
            return {
                "workspace_id": "ws-1",
                "organization": {"id": "org-1"},
                "datasource": {"id": 11},
                "workspace_binding": {"workspace_id": "ws-1", "datasource_id": 11},
                "memberships": {},
            }

    monkeypatch.setattr(admin_routes, "TenancyBootstrapService", _FakeBootstrapSvc)
    resp = client.post(
        "/api/v1/admin/tenancy/bootstrap",
        json={
            "workspace_id": "ws-1",
            "organization_name": "Acme District",
            "datasource_name": "Primary",
            "datasource_type": "snowflake",
        },
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["result"]["organization"]["id"] == "org-1"


def test_admin_organization_create(client, monkeypatch):
    class _FakeSvc:
        def create_organization(self, req):
            assert req.name == "Acme District"
            return {"id": "org-1", "name": req.name, "slug": "acme-district"}

    monkeypatch.setattr(admin_routes, "TenancyAdminService", _FakeSvc)
    resp = client.post(
        "/api/v1/admin/organizations",
        json={"name": "Acme District"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201
    assert resp.json["slug"] == "acme-district"


def test_admin_organization_datasource_create(client, monkeypatch):
    class _FakeSvc:
        def create_datasource(self, *, organization_id, req):
            assert organization_id == "org-1"
            assert req.type == "snowflake"
            return {"id": 99, "organization_id": organization_id, "type": req.type}

    monkeypatch.setattr(admin_routes, "TenancyAdminService", _FakeSvc)
    resp = client.post(
        "/api/v1/admin/organizations/org-1/datasources",
        json={"name": "primary", "type": "snowflake", "config_json": {"account": "acc"}},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201
    assert resp.json["id"] == 99


def test_admin_datasource_connection_test(client, monkeypatch):
    class _FakeSvc:
        def test_datasource(self, *, datasource_id):
            assert datasource_id == 22
            return {"datasource_id": 22, "status": "ok", "latency_ms": 10}

    monkeypatch.setattr(admin_routes, "TenancyAdminService", _FakeSvc)
    resp = client.post("/api/v1/admin/datasources/22/test", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["result"]["status"] == "ok"


def test_admin_workspace_membership_create(client, monkeypatch):
    class _FakeSvc:
        def upsert_workspace_membership(self, *, workspace_id, req):
            assert workspace_id == "ws-1"
            assert req.user_id == "user-2"
            return {"id": 7, "workspace_id": workspace_id, "user_id": req.user_id, "is_active": True}

    monkeypatch.setattr(admin_routes, "TenancyAdminService", _FakeSvc)
    resp = client.post(
        "/api/v1/admin/workspaces/ws-1/memberships",
        json={"user_id": "user-2", "role": "member"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201
    assert resp.json["id"] == 7


def test_admin_organization_membership_create_null_role_defaults_member(client, monkeypatch):
    class _FakeSvc:
        def upsert_organization_membership(self, *, organization_id, req):
            assert organization_id == "org-1"
            assert req.user_id == "user-2"
            assert req.role == "member"
            return {"id": 88, "organization_id": organization_id, "user_id": req.user_id, "role": req.role}

    monkeypatch.setattr(admin_routes, "TenancyAdminService", _FakeSvc)
    resp = client.post(
        "/api/v1/admin/organizations/org-1/memberships",
        json={"user_id": "user-2", "role": None},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201
    assert resp.json["role"] == "member"


def test_admin_workspace_membership_create_null_role_defaults_member(client, monkeypatch):
    class _FakeSvc:
        def upsert_workspace_membership(self, *, workspace_id, req):
            assert workspace_id == "ws-1"
            assert req.user_id == "user-2"
            assert req.role == "member"
            return {"id": 7, "workspace_id": workspace_id, "user_id": req.user_id, "role": req.role, "is_active": True}

    monkeypatch.setattr(admin_routes, "TenancyAdminService", _FakeSvc)
    resp = client.post(
        "/api/v1/admin/workspaces/ws-1/memberships",
        json={"user_id": "user-2", "role": None},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201
    assert resp.json["role"] == "member"


def test_admin_workspace_binding_list(client, monkeypatch):
    class _FakeSvc:
        def list_workspace_bindings(self, **kwargs):
            assert kwargs["organization_id"] == "org-1"
            return {"rows": [{"workspace_id": "ws-1", "datasource_id": 3}], "count": 1, "total": 1, "limit": 200, "offset": 0}

    monkeypatch.setattr(admin_routes, "TenancyAdminService", _FakeSvc)
    resp = client.get("/api/v1/admin/workspaces?organization_id=org-1", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["rows"][0]["workspace_id"] == "ws-1"


def test_admin_workspace_binding_list_allows_workspace_admin_in_current_workspace_scope(client, monkeypatch):
    class _FakeSvc:
        def get_workspace_binding(self, workspace_id):
            assert workspace_id == "ws-1"
            return {
                "workspace_id": "ws-1",
                "workspace_name": "Workspace One",
                "workspace_is_active": True,
                "organization_id": "org-1",
                "organization_name": "Acme",
                "datasource_name": "Warehouse",
            }

    monkeypatch.setattr(admin_routes, "TenancyAdminService", _FakeSvc)
    resp = client.get(
        "/api/v1/admin/workspaces",
        headers=_headers(monkeypatch, is_admin=False, roles={"workspace_admin"}),
    )
    assert resp.status_code == 200
    assert resp.json["count"] == 1
    assert resp.json["rows"][0]["workspace_id"] == "ws-1"


def test_admin_workspace_create(client, monkeypatch):
    class _FakeSvc:
        def create_workspace(self, req):
            assert req.organization_id == "org-1"
            assert req.name == "Acme Workspace"
            return {"workspace_id": "ws-new-1", "organization_id": req.organization_id}

    monkeypatch.setattr(admin_routes, "TenancyAdminService", _FakeSvc)
    resp = client.post(
        "/api/v1/admin/workspaces",
        json={"organization_id": "org-1", "name": "Acme Workspace"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201
    assert resp.json["workspace_id"] == "ws-new-1"


def test_admin_workspace_binding_update(client, monkeypatch):
    class _FakeSvc:
        def update_workspace_binding(self, *, workspace_id, req):
            assert workspace_id == "ws-1"
            assert req.datasource_id == 8
            return {"workspace_id": workspace_id, "datasource_id": req.datasource_id}

    monkeypatch.setattr(admin_routes, "TenancyAdminService", _FakeSvc)
    resp = client.patch(
        "/api/v1/admin/workspaces/ws-1/binding",
        json={"datasource_id": 8},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["datasource_id"] == 8


def test_admin_tenancy_routes_require_admin(client, monkeypatch):
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
        "/api/v1/admin/organizations",
        headers={"Authorization": "Bearer test-token", "X-Workspace-Id": "ws-1"},
    )
    assert resp.status_code == 403

    resp_bootstrap = client.post(
        "/api/v1/admin/tenancy/bootstrap",
        json={
            "workspace_id": "ws-1",
            "organization_name": "Acme District",
            "datasource_name": "Primary",
            "datasource_type": "snowflake",
        },
        headers={"Authorization": "Bearer test-token", "X-Workspace-Id": "ws-1"},
    )
    assert resp_bootstrap.status_code == 403
