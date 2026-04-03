from __future__ import annotations

import app.features.workspaces.workspace_api as workspace_route


def _headers(monkeypatch):
    from app import factory
    from app.decorators import security
    from app.services.workspace_inventory import workspace_context

    def _verify_token(_token):
        return {"sub": "user-1", "username": "user-1", "is_admin": True}

    monkeypatch.setattr(security.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(factory.auth_service, "verify_token", _verify_token)
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


def test_workspace_users_route_reads_from_mysql_backed_service(client, monkeypatch):
    class _Svc:
        def list_workspace_users(self, *, workspace_id, q, limit, offset, include_inactive):
            assert workspace_id == "ws-88"
            assert q == "john"
            assert limit == 20
            assert offset == 40
            assert include_inactive is True
            return [{"user_id": "user-1", "username": "john"}]

    monkeypatch.setattr(workspace_route, "WorkspaceUserReadService", _Svc)

    resp = client.get(
        "/api/v1/workspaces/ws-88/users?q=john&limit=20&offset=40&include_inactive=true",
        headers=_headers(monkeypatch),
    )

    assert resp.status_code == 200
    assert resp.json == {"rows": [{"user_id": "user-1", "username": "john"}]}
