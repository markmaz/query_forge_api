from __future__ import annotations

import pyarrow as pa

import app.routes.export_routes as export_routes
from app.services.exports.export_policy import EXCEL_MAX_ROWS, clear_rowcount_cache


class _DummyValkey:
    def __init__(self, *args, **kwargs):
        self._store = {}

    def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    def get(self, key: str):
        return self._store.get(key)

    def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0


class _SqlExec:
    def __init__(self, total: int, rows: list[dict]):
        self.total = total
        self._table = pa.Table.from_pylist(rows)

    def submit_statement(self, sql: str, parameters=None, result_format=None):
        if result_format == "ARROW_STREAM":
            return {"table": self._table, "rows": self._table.to_pylist()}
        return {"rows": [{"total": self.total}]}


class _Ctx:
    def __init__(self, total: int, rows: list[dict]):
        self.sql_exec = _SqlExec(total, rows)


class _Builder:
    def __init__(self, total: int, rows: list[dict]):
        self._total = total
        self._rows = rows

    def build(self, workspace_id: str):
        return _Ctx(self._total, self._rows)


def _install_nocode_compile(monkeypatch, *, sql="SELECT 1", params=None, count_sql="SELECT COUNT(*) AS total FROM t"):
    class _Compiled:
        pass

    compiled = _Compiled()
    compiled.sql = sql
    compiled.params = params or {}
    compiled.count_sql = count_sql

    class _NoCodeService:
        def __init__(self, executor, domain_resolver):
            self.executor = executor
            self.domain_resolver = domain_resolver

        def normalize(self, sql_json):
            return sql_json

        def compile(self, normalized, mode="export", limit=0, offset=0):
            return compiled

    monkeypatch.setattr(export_routes, "NoCodeQueryService", _NoCodeService)
    monkeypatch.setattr(export_routes, "DomainResolver", lambda workspace_id: object())


def test_excel_export_blocks_over_limit(client, auth_headers, monkeypatch):
    clear_rowcount_cache()
    export_routes._valkey_client = None
    monkeypatch.setattr(export_routes.valkey, "StrictValkey", _DummyValkey)
    _install_nocode_compile(monkeypatch)
    monkeypatch.setattr(
        export_routes,
        "WorkspaceContextBuilder",
        lambda: _Builder(EXCEL_MAX_ROWS + 5, [{"a": 1}]),
    )

    resp = client.post(
        "/api/v1/exports/excel",
        headers=auth_headers,
        json={"sqlJson": {"domainId": 1}},
    )

    assert resp.status_code == 409
    assert resp.json["error"] == "EXCEL_ROW_LIMIT"
    assert resp.json["rowCount"] == EXCEL_MAX_ROWS + 5
    assert resp.json["maxRows"] == EXCEL_MAX_ROWS


def test_excel_export_allows_under_limit(client, auth_headers, monkeypatch):
    clear_rowcount_cache()
    export_routes._valkey_client = None
    monkeypatch.setattr(export_routes.valkey, "StrictValkey", _DummyValkey)
    _install_nocode_compile(monkeypatch)
    monkeypatch.setattr(
        export_routes,
        "WorkspaceContextBuilder",
        lambda: _Builder(2, [{"a": 1}, {"a": 2}]),
    )

    resp = client.post(
        "/api/v1/exports/excel",
        headers=auth_headers,
        json={"sqlJson": {"domainId": 1}},
    )

    assert resp.status_code == 200
    assert resp.json["token"]
    assert resp.json["filename"].endswith(".xlsx")

    download = client.get(f"/api/v1/exports/excel/{resp.json['token']}", headers=auth_headers)
    assert download.status_code == 200
    assert download.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert download.data
    assert download.headers["Content-Disposition"].endswith(".xlsx")

    reused = client.get(f"/api/v1/exports/excel/{resp.json['token']}", headers=auth_headers)
    assert reused.status_code == 404


def test_excel_export_download_requires_auth(client, auth_headers, monkeypatch):
    clear_rowcount_cache()
    export_routes._valkey_client = None
    monkeypatch.setattr(export_routes.valkey, "StrictValkey", _DummyValkey)
    _install_nocode_compile(monkeypatch)
    monkeypatch.setattr(
        export_routes,
        "WorkspaceContextBuilder",
        lambda: _Builder(1, [{"a": 1}]),
    )

    resp = client.post(
        "/api/v1/exports/excel",
        headers=auth_headers,
        json={"sqlJson": {"domainId": 1}},
    )
    token = resp.json["token"]

    download = client.get(f"/api/v1/exports/excel/{token}")
    assert download.status_code == 403


def test_excel_export_download_wrong_workspace(client, auth_headers, monkeypatch):
    clear_rowcount_cache()
    export_routes._valkey_client = None
    monkeypatch.setattr(export_routes.valkey, "StrictValkey", _DummyValkey)
    _install_nocode_compile(monkeypatch)
    monkeypatch.setattr(
        export_routes,
        "WorkspaceContextBuilder",
        lambda: _Builder(1, [{"a": 1}]),
    )

    resp = client.post(
        "/api/v1/exports/excel",
        headers=auth_headers,
        json={"sqlJson": {"domainId": 1}},
    )
    token = resp.json["token"]

    wrong_headers = dict(auth_headers)
    wrong_headers["X-Workspace-Id"] = "ws-2"
    download = client.get(f"/api/v1/exports/excel/{token}", headers=wrong_headers)
    assert download.status_code == 404


def test_excel_export_rejects_raw_sql_fields(client, auth_headers, monkeypatch):
    clear_rowcount_cache()
    export_routes._valkey_client = None
    monkeypatch.setattr(export_routes.valkey, "StrictValkey", _DummyValkey)
    _install_nocode_compile(monkeypatch)

    resp = client.post(
        "/api/v1/exports/excel",
        headers=auth_headers,
        json={"sqlJson": {"domainId": 1}, "sql": "SELECT 1"},
    )
    assert resp.status_code == 400
    assert "Raw SQL fields are not allowed" in resp.json["error"]
