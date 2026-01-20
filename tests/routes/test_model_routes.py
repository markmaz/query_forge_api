from __future__ import annotations

import app.routes.model_routes as model_routes


def test_model_tables_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def list_tables(self, *, q=None, active=None, limit=0, offset=0):
            return {"rows": [{"id": 1}], "total": 1, "limit": limit, "offset": offset}

    monkeypatch.setattr(model_routes, "ModelReadService", _Svc)

    resp = client.get("/api/v1/models/tables", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["total"] == 1


def test_model_tables_missing_workspace(client, auth_headers):
    headers = {k: v for k, v in auth_headers.items() if k.lower() != "x-workspace-id"}
    resp = client.get("/api/v1/models/tables", headers=headers)
    assert resp.status_code == 400


def test_model_tables_requires_auth(client):
    resp = client.get("/api/v1/models/tables")
    assert resp.status_code == 403
