from __future__ import annotations

import io

import app.routes.dictionary_routes as dict_routes
from app.exceptions.forge_error import ForgeError


# ---------------------------------------------------------------------------
# GET /dictionary/tables
# ---------------------------------------------------------------------------

def test_get_tables_success(client, auth_headers, monkeypatch):
    class _Svc:
        def list_tables(self, *, workspace_id, q, limit, offset):
            return {"rows": [{"id": 1, "table_name": "dim_prov", "full_name": "asset.dim_prov",
                               "schema_name": "asset", "catalog_name": None, "description": None}],
                    "total": 1, "limit": limit, "offset": offset}

    monkeypatch.setattr(dict_routes, "DictionaryService", _Svc)
    resp = client.get("/api/v1/dictionary/tables", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["rows"][0]["table_name"] == "dim_prov"
    assert resp.json["total"] == 1


def test_get_tables_missing_workspace(client, auth_headers):
    headers = {k: v for k, v in auth_headers.items() if k.lower() != "x-workspace-id"}
    resp = client.get("/api/v1/dictionary/tables", headers=headers)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /dictionary/columns
# ---------------------------------------------------------------------------

def test_get_columns_success(client, auth_headers, monkeypatch):
    class _Svc:
        def list_columns(self, *, workspace_id, workspace_table_id, q, active_only):
            return {"rows": [{"id": 5, "workspace_table_id": workspace_table_id,
                               "column_name": "npi", "data_type": "string",
                               "ordinal_position": 1, "description": None, "is_active": True,
                               "semantic_type": None, "semantic_entity": None,
                               "semantic_sub_type": None, "semantic_confidence": None,
                               "sample_values_json": None, "sample_stats_json": None,
                               "sample_ran_at": None, "sample_error": None,
                               "table_name": "dim_prov", "full_name": "asset.dim_prov"}]}

    monkeypatch.setattr(dict_routes, "DictionaryService", _Svc)
    resp = client.get("/api/v1/dictionary/columns?workspace_table_id=1", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["rows"][0]["column_name"] == "npi"


def test_get_columns_missing_workspace_table_id(client, auth_headers):
    resp = client.get("/api/v1/dictionary/columns", headers=auth_headers)
    assert resp.status_code == 400


def test_get_columns_404(client, auth_headers, monkeypatch):
    class _Svc:
        def list_columns(self, *, workspace_id, workspace_table_id, q, active_only):
            raise ForgeError("Workspace table not found", status_code=404)

    monkeypatch.setattr(dict_routes, "DictionaryService", _Svc)
    resp = client.get("/api/v1/dictionary/columns?workspace_table_id=999", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /dictionary/columns/search
# ---------------------------------------------------------------------------

def test_search_columns_success(client, auth_headers, monkeypatch):
    class _Svc:
        def search_columns(self, *, workspace_id, q, limit, active_only):
            return {"rows": []}

    monkeypatch.setattr(dict_routes, "DictionaryService", _Svc)
    resp = client.get("/api/v1/dictionary/columns/search?q=npi", headers=auth_headers)
    assert resp.status_code == 200


def test_search_columns_missing_q(client, auth_headers):
    resp = client.get("/api/v1/dictionary/columns/search", headers=auth_headers)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PATCH /dictionary/columns/:id
# ---------------------------------------------------------------------------

def test_patch_column_success(client, auth_headers, monkeypatch):
    class _Svc:
        def patch_column(self, *, workspace_id, column_id, patch):
            return {"row": {"id": column_id, "description": patch.get("description"),
                             "workspace_table_id": 1, "column_name": "npi",
                             "data_type": "string", "ordinal_position": 1,
                             "is_active": True, "semantic_type": None,
                             "semantic_entity": None, "semantic_sub_type": None,
                             "semantic_confidence": None, "sample_values_json": None,
                             "sample_stats_json": None, "sample_ran_at": None,
                             "sample_error": None, "table_name": "dim_prov",
                             "full_name": "asset.dim_prov"}}

    monkeypatch.setattr(dict_routes, "DictionaryService", _Svc)
    resp = client.patch("/api/v1/dictionary/columns/5",
                        json={"description": "Hello"},
                        headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["row"]["description"] == "Hello"


def test_patch_column_404(client, auth_headers, monkeypatch):
    class _Svc:
        def patch_column(self, *, workspace_id, column_id, patch):
            raise ForgeError("Column not found", status_code=404)

    monkeypatch.setattr(dict_routes, "DictionaryService", _Svc)
    resp = client.patch("/api/v1/dictionary/columns/999",
                        json={"description": "x"},
                        headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /dictionary/columns/import
# ---------------------------------------------------------------------------

def test_import_columns_success(client, auth_headers, monkeypatch):
    class _Svc:
        def import_columns(self, *, workspace_id, rows, full_replace):
            return {"updated": 2, "unmatched": []}

    monkeypatch.setattr(dict_routes, "DictionaryService", _Svc)
    csv_content = b"table_name,column_name,description\ndim_prov,npi,NPI\ndim_prov,name,Name"
    data = {"file": (io.BytesIO(csv_content), "test.csv")}
    resp = client.post("/api/v1/dictionary/columns/import?fullReplace=false",
                       data=data, content_type="multipart/form-data",
                       headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["updated"] == 2


def test_import_columns_missing_file(client, auth_headers):
    resp = client.post("/api/v1/dictionary/columns/import",
                       data={}, content_type="multipart/form-data",
                       headers=auth_headers)
    assert resp.status_code == 400


def test_import_columns_empty_file_full_replace(client, auth_headers, monkeypatch):
    """fullReplace=true with an empty file must return 400."""
    class _Svc:
        def import_columns(self, **_):
            return {"updated": 0, "unmatched": []}

    monkeypatch.setattr(dict_routes, "DictionaryService", _Svc)
    csv_content = b"table_name,column_name\n"  # header only, no data rows
    data = {"file": (io.BytesIO(csv_content), "empty.csv")}
    resp = client.post("/api/v1/dictionary/columns/import?fullReplace=true",
                       data=data, content_type="multipart/form-data",
                       headers=auth_headers)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PATCH /dictionary/tables/:id
# ---------------------------------------------------------------------------

def test_patch_table_success(client, auth_headers, monkeypatch):
    class _Svc:
        def patch_table(self, *, workspace_id, table_id, patch):
            return {"row": {"id": table_id, "table_name": "dim_prov",
                            "full_name": "asset.dim_prov", "schema_name": "asset",
                            "catalog_name": None, "description": patch.get("description")}}

    monkeypatch.setattr(dict_routes, "DictionaryService", _Svc)
    resp = client.patch(
        "/api/v1/dictionary/tables/1",
        json={"description": "Updated"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json["row"]["description"] == "Updated"


def test_patch_table_400_on_empty_body(client, auth_headers):
    resp = client.patch(
        "/api/v1/dictionary/tables/1",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 400
