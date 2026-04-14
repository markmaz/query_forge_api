from __future__ import annotations

import app.features.saved_queries.query_tree_api as query_tree_routes
import app.routes.request_helpers as request_helpers
import app.decorators.rbac as rbac_decorators
import app.decorators.security as security
import app.services.rbac_service as rbac_service


def _headers(monkeypatch, *, actor_id: str = "user-1", roles: set[str] | None = None):
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": actor_id, "username": actor_id, "is_admin": False},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(
        request_helpers.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(
        rbac_service,
        "get_effective_roles",
        lambda user_id, workspace_id=None: set(roles or {"query_studio:user"}),
    )
    monkeypatch.setattr(rbac_decorators, "workspace_has_feature", lambda workspace_id, feature_key: True)
    return {"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-1"}


def test_query_tree_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def get_tree(self, view: str):
            return {"view": view, "rootNodes": []}

    monkeypatch.setattr(query_tree_routes, "SavedQueryTreeService", _Svc)

    resp = client.get("/api/v1/query-tree/?view=my", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["view"] == "my"


def test_query_tree_missing_workspace(client, auth_headers):
    headers = {k: v for k, v in auth_headers.items() if k.lower() != "x-workspace-id"}
    resp = client.get("/api/v1/query-tree/?view=my", headers=headers)
    assert resp.status_code == 400


def test_query_tree_requires_auth(client):
    resp = client.get("/api/v1/query-tree/?view=my")
    assert resp.status_code == 403


def test_save_to_library_allows_library_admin(client, monkeypatch):
    class _LibrarySvc:
        def __init__(self, *args, **kwargs):
            assert kwargs["allow_publish"] is True

        def save_query_to_library(self, source_query_id: str):
            return {"queryId": "lib-1", "sourceQueryId": source_query_id}

    monkeypatch.setattr(query_tree_routes, "SavedQueryLibraryService", _LibrarySvc)
    headers = _headers(monkeypatch, roles={"query_studio:user", "library_admin"})

    resp = client.post("/api/v1/saved-queries/q-1/save-to-library", headers=headers)

    assert resp.status_code == 200
    assert resp.json["sourceQueryId"] == "q-1"


def test_library_delete_uses_library_service_for_library_admin(client, monkeypatch):
    class _LibrarySvc:
        def __init__(self, *args, **kwargs):
            assert kwargs["allow_delete_query"] is True
            assert kwargs["allow_manage"] is True

        def query_exists(self, query_id: str):
            return query_id == "lib-q-1"

        def delete_query(self, query_id: str):
            return {"queryId": query_id, "deleted": True}

    class _WriteSvc:
        def __init__(self, *args, **kwargs):
            pass

        def delete_query(self, query_id: str):
            raise AssertionError("personal query service should not handle library delete")

    monkeypatch.setattr(query_tree_routes, "SavedQueryLibraryService", _LibrarySvc)
    monkeypatch.setattr(query_tree_routes, "SavedQueryWriteService", _WriteSvc)
    headers = _headers(monkeypatch, roles={"query_studio:user", "library_admin"})

    resp = client.post("/api/v1/saved-queries/lib-q-1/delete", headers=headers)

    assert resp.status_code == 200
    assert resp.json["deleted"] is True


def test_library_move_allows_library_admin(client, monkeypatch):
    class _LibrarySvc:
        def __init__(self, *args, **kwargs):
            assert kwargs["allow_manage"] is True

        def query_exists(self, query_id: str):
            return query_id == "lib-q-1"

        def move_query(self, *, query_id: str, folder_id: str | None):
            return {"queryId": query_id, "folderId": folder_id}

    class _WriteSvc:
        def __init__(self, *args, **kwargs):
            pass

        def move_query(self, query_id: str, folder_id: str | None):
            raise AssertionError("personal query service should not handle library move")

    monkeypatch.setattr(query_tree_routes, "SavedQueryLibraryService", _LibrarySvc)
    monkeypatch.setattr(query_tree_routes, "SavedQueryWriteService", _WriteSvc)
    headers = _headers(monkeypatch, roles={"query_studio:user", "library_admin"})

    resp = client.patch("/api/v1/saved-queries/lib-q-1/move", json={"folderId": "folder-1"}, headers=headers)

    assert resp.status_code == 200
    assert resp.json["folderId"] == "folder-1"


def test_library_folder_create_allows_library_admin(client, monkeypatch):
    class _LibrarySvc:
        def __init__(self, *args, **kwargs):
            assert kwargs["allow_manage"] is True

        def create_folder(self, *, name: str, parent_folder_id: str | None = None, sort_index: int = 0):
            return {"folderId": "lib-folder-1", "name": name, "parentId": parent_folder_id}

    monkeypatch.setattr(query_tree_routes, "SavedQueryLibraryService", _LibrarySvc)
    headers = _headers(monkeypatch, roles={"query_studio:user", "library_admin"})

    resp = client.post(
        "/api/v1/query-tree/folders",
        json={"name": "Library Folder", "scope": "library"},
        headers=headers,
    )

    assert resp.status_code == 200
    assert resp.json["folderId"] == "lib-folder-1"
