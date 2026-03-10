from __future__ import annotations

import app.routes.query_tree_routes as query_tree_routes


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
