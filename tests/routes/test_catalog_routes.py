from __future__ import annotations

import app.features.catalog.catalog_api as catalog_routes


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


def test_catalog_sync_route(client, monkeypatch):
    class _Ctx:
        sql_exec = object()

    class _Builder:
        def build(self, workspace_id):
            assert workspace_id == "ws-1"
            return _Ctx()

    class _Pipeline:
        def __init__(self, sql):
            assert sql is _Ctx.sql_exec

        def sync_snapshot(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            assert kwargs["schema_name"] == "asset"
            return {"tables_synced": 4}

    monkeypatch.setattr(catalog_routes, "WorkspaceSqlContextBuilder", _Builder)
    monkeypatch.setattr(catalog_routes, "WorkspacePipelineService", _Pipeline)

    resp = client.post("/api/v1/catalog/sync", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["tables_synced"] == 4


def test_catalog_recon_counts_route(client, monkeypatch):
    class _Svc:
        def counts_by_status(self, *, workspace_id):
            assert workspace_id == "ws-1"
            return {"MATCHED": 7, "UNMATCHED": 2}

    monkeypatch.setattr(catalog_routes, "_catalog_recon_service", lambda: _Svc())

    resp = client.get("/api/v1/catalog/recon/counts", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["counts"]["MATCHED"] == 7


def test_catalog_unmapped_tables_route(client, monkeypatch):
    class _Svc:
        def list_unmapped_tables(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            assert kwargs["schema_name"] == "asset"
            return {"rows": [{"workspace_table_id": 11}], "total": 1}

    monkeypatch.setattr(catalog_routes, "_catalog_unmapped_service", lambda: _Svc())

    resp = client.get(
        "/api/v1/catalog/unmapped-tables?schema=asset",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["total"] == 1


def test_catalog_table_sample_not_found(client, monkeypatch):
    class _Result:
        def mappings(self):
            return self

        def first(self):
            return None

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, stmt, params):
            del stmt
            assert params["id"] == 9
            assert params["ws"] == "ws-1"
            return _Result()

    class _Engine:
        def connect(self):
            return _Conn()

    monkeypatch.setattr(catalog_routes, "engine", _Engine())

    resp = client.get(
        "/api/v1/catalog/table-sample?workspace_table_id=9",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 404
