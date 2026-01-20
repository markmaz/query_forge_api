from __future__ import annotations

from types import SimpleNamespace

import app.routes.no_code_query_routes as no_code_query_routes


def test_no_code_query_post_success(client, auth_headers, monkeypatch):
    class _Ctx:
        sql_exec = object()

    class _Builder:
        def build(self, workspace_id: str):
            return _Ctx()

    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, raw_query, mode, limit, offset):
            return SimpleNamespace(
                sql="select 1",
                sql_rendered="select 1",
                params={},
                rows=[],
                columns=[],
                total=2,
                limit=limit,
                offset=offset,
            )

    monkeypatch.setattr(no_code_query_routes, "WorkspaceContextBuilder", _Builder)
    monkeypatch.setattr(no_code_query_routes, "NoCodeQueryService", _Svc)

    resp = client.post("/api/v1/query/?mode=preview", headers=auth_headers, json={"version": 1})
    assert resp.status_code == 200
    assert resp.json["sql"] == "select 1"
    assert resp.json["totalRowCount"] == 2
    assert resp.json["export"]["excel"]["allowed"] is True
    assert resp.json["rowCountSignature"]


def test_no_code_query_invalid_body(client, auth_headers, monkeypatch):
    class _Ctx:
        sql_exec = object()

    class _Builder:
        def build(self, workspace_id: str):
            return _Ctx()

    monkeypatch.setattr(no_code_query_routes, "WorkspaceContextBuilder", _Builder)

    resp = client.post("/api/v1/query/", headers=auth_headers, json="not-json")
    assert resp.status_code == 400


def test_no_code_query_requires_auth(client):
    resp = client.post("/api/v1/query/", json={"version": 1})
    assert resp.status_code == 403
