from __future__ import annotations

from types import SimpleNamespace

import app.features.data_catalog.workspace_inventory_api as workspace_inventory_route


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


def test_workspace_inventory_sync_route_returns_snapshot(client, monkeypatch):
    class _ContextBuilder:
        def build(self, workspace_id):
            assert workspace_id == "ws-1"
            return SimpleNamespace(sql_exec="sql-exec")

    class _Pipeline:
        def __init__(self, *, sql):
            assert sql == "sql-exec"

        def sync_snapshot(self, *, workspace_id, schema_name, catalog_name):
            assert workspace_id == "ws-1"
            assert schema_name == "asset"
            assert catalog_name == "main"
            return {"tables_synced": 3}

    monkeypatch.setattr(workspace_inventory_route, "WorkspaceSqlContextBuilder", _ContextBuilder)
    monkeypatch.setattr(workspace_inventory_route, "WorkspacePipelineService", _Pipeline)

    resp = client.post(
        "/api/v1/workspace-inventory/sync?catalog=main",
        headers=_headers(monkeypatch),
    )

    assert resp.status_code == 200
    assert resp.json == {"ok": True, "workspaceSnapshot": {"tables_synced": 3}}
