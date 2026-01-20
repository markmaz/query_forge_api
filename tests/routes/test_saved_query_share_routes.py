from __future__ import annotations

import app.routes.query_tree_routes as query_tree_routes
from app.exceptions.service_error import ServiceError


def test_saved_query_share_to_workspace(client, auth_headers, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def share_to_workspace(self, query_id: str, can_edit: bool = False):
            return {
                "aclId": "a1",
                "queryId": query_id,
                "principalType": "WORKSPACE",
                "principalId": "ws-1",
                "permission": "WRITE" if can_edit else "READ",
                "canEdit": can_edit,
            }

    monkeypatch.setattr(query_tree_routes, "SavedQueryShareService", _Svc)

    resp = client.post(
        "/api/v1/saved-queries/q1/shares",
        headers=auth_headers,
        json={"shareKind": "WORKSPACE", "canEdit": True},
    )
    assert resp.status_code == 200
    assert resp.json["principalType"] == "WORKSPACE"
    assert resp.json["canEdit"] is True


def test_saved_query_share_to_user(client, auth_headers, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def share_to_user(self, query_id: str, shared_with_user_id: str, can_edit: bool = False):
            return {
                "aclId": "a2",
                "queryId": query_id,
                "principalType": "USER",
                "principalId": shared_with_user_id,
                "permission": "READ",
                "canEdit": False,
            }

    monkeypatch.setattr(query_tree_routes, "SavedQueryShareService", _Svc)

    resp = client.post(
        "/api/v1/saved-queries/q1/shares",
        headers=auth_headers,
        json={"shareKind": "USER", "sharedWithUserId": "user-2"},
    )
    assert resp.status_code == 200
    assert resp.json["principalType"] == "USER"
    assert resp.json["principalId"] == "user-2"


def test_saved_query_share_non_owner_returns_404(client, auth_headers, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def share_to_workspace(self, query_id: str, can_edit: bool = False):
            raise ServiceError("Saved query not found", status_code=404)

    monkeypatch.setattr(query_tree_routes, "SavedQueryShareService", _Svc)

    resp = client.post(
        "/api/v1/saved-queries/q1/shares",
        headers=auth_headers,
        json={"shareKind": "WORKSPACE"},
    )
    assert resp.status_code == 404


def test_saved_query_list_shares(client, auth_headers, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def list_shares(self, query_id: str):
            return {
                "queryId": query_id,
                "shares": [
                    {
                        "aclId": "a1",
                        "principalType": "WORKSPACE",
                        "principalId": "ws-1",
                        "permission": "READ",
                        "canEdit": False,
                        "createdAt": "2024-01-01T00:00:00",
                    },
                    {
                        "aclId": "a2",
                        "principalType": "USER",
                        "principalId": "user-2",
                        "permission": "WRITE",
                        "canEdit": True,
                        "createdAt": "2024-01-02T00:00:00",
                    },
                ],
            }

    monkeypatch.setattr(query_tree_routes, "SavedQueryShareService", _Svc)

    resp = client.get("/api/v1/saved-queries/q1/shares", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json["shares"]) == 2


def test_saved_query_unshare(client, auth_headers, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def unshare(self, query_id: str, share_kind: str, shared_with_user_id=None):
            return {"queryId": query_id, "shareKind": share_kind, "removed": True}

    monkeypatch.setattr(query_tree_routes, "SavedQueryShareService", _Svc)

    resp = client.delete(
        "/api/v1/saved-queries/q1/shares",
        headers=auth_headers,
        json={"shareKind": "USER", "sharedWithUserId": "user-2"},
    )
    assert resp.status_code == 200
    assert resp.json["removed"] is True


def test_saved_query_shares_requires_auth(client):
    resp = client.get("/api/v1/saved-queries/q1/shares")
    assert resp.status_code == 403
