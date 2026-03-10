from __future__ import annotations

from datetime import datetime

import app.routes.forge_insights as forge_insights_route


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


def _project(project_id: int) -> dict:
    return {
        "id": project_id,
        "workspace_id": "ws-1",
        "user_id": "user-1",
        "name": "Project A",
        "description": "Desc",
        "is_archived": False,
        "created_at": datetime(2026, 1, 1, 12, 0, 0),
        "updated_at": datetime(2026, 1, 1, 12, 1, 0),
    }


def _thread(thread_id: int) -> dict:
    return {
        "id": thread_id,
        "workspace_id": "ws-1",
        "user_id": "user-1",
        "project_id": 1,
        "conversation_id": "fi_123",
        "title": "Thread",
        "preview_text": "Preview",
        "is_pinned": False,
        "is_archived": False,
        "last_message_at": datetime(2026, 1, 1, 12, 2, 0),
        "created_at": datetime(2026, 1, 1, 12, 0, 0),
        "updated_at": datetime(2026, 1, 1, 12, 3, 0),
    }


def test_create_project_route(client, monkeypatch):
    class _Svc:
        def create_project(self, *, workspace_id, user_id, name, description):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert name == "Project A"
            assert description == "Desc"
            return _project(11)

    monkeypatch.setattr(forge_insights_route, "ForgeInsightsThreadsService", _Svc)
    resp = client.post(
        "/api/v1/forge-insights/projects",
        json={"name": "Project A", "description": "Desc"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201
    assert resp.json["id"] == 11


def test_list_projects_route(client, monkeypatch):
    class _Svc:
        def list_projects(self, *, workspace_id, user_id, include_archived):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert include_archived is True
            return [_project(1)]

    monkeypatch.setattr(forge_insights_route, "ForgeInsightsThreadsService", _Svc)
    resp = client.get("/api/v1/forge-insights/projects?include_archived=true", headers=_headers(monkeypatch))
    assert resp.status_code == 200
    assert resp.json["items"][0]["id"] == 1


def test_create_thread_route(client, monkeypatch):
    class _Svc:
        def create_thread(self, *, workspace_id, user_id, **kwargs):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert kwargs["project_id"] == 1
            return _thread(22)

    monkeypatch.setattr(forge_insights_route, "ForgeInsightsThreadsService", _Svc)
    resp = client.post(
        "/api/v1/forge-insights/threads",
        json={"project_id": 1, "title": "Thread"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201
    assert resp.json["id"] == 22
    assert resp.json["conversation_id"] == "fi_123"


def test_list_threads_route_excludes_stale_by_default(client, monkeypatch):
    class _Svc:
        def list_threads(self, *, workspace_id, user_id, project_id, include_archived, include_stale, limit, offset):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert project_id is None
            assert include_archived is False
            assert include_stale is False
            assert limit == 200
            assert offset == 0
            return [_thread(31)]

    monkeypatch.setattr(forge_insights_route, "ForgeInsightsThreadsService", _Svc)
    resp = client.get(
        "/api/v1/forge-insights/threads?include_archived=false&limit=200&offset=0",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["items"][0]["id"] == 31


def test_patch_thread_route(client, monkeypatch):
    class _Svc:
        def update_thread(self, *, workspace_id, user_id, thread_id, **kwargs):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert thread_id == 22
            assert kwargs["title"] == "Renamed"
            return _thread(22) | {"title": "Renamed"}

    monkeypatch.setattr(forge_insights_route, "ForgeInsightsThreadsService", _Svc)
    resp = client.patch(
        "/api/v1/forge-insights/threads/22",
        json={"title": "Renamed"},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["title"] == "Renamed"


def test_invalid_project_create_payload_returns_400(client, monkeypatch):
    resp = client.post(
        "/api/v1/forge-insights/projects",
        json={"name": ""},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 400
