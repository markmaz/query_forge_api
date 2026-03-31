from __future__ import annotations

import app.services.execution_service as execution_service


class _FakeValkey:
    def __init__(self):
        self.store = {}

    def setex(self, key, _ttl, value):
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        return self.store.pop(key, None)


def _install_valkey(monkeypatch):
    client = _FakeValkey()
    monkeypatch.setattr(execution_service, "_get_valkey_client", lambda: client)
    return client


def _install_nocode_prepare(monkeypatch, *, sql="SELECT 1", params=None, qf_rendered_sql=None, qf_count_sql=None):
    class _Prepared:
        pass

    prepared = _Prepared()
    prepared.sql = sql
    prepared.params = params or {}
    prepared.qf_rendered_sql = sql if qf_rendered_sql is None else qf_rendered_sql
    prepared.qf_count_sql = qf_count_sql

    class _NoCodeService:
        def __init__(self, executor, domain_resolver):
            self.executor = executor
            self.domain_resolver = domain_resolver

        def prepare(self, raw_query, mode="preview", limit=200, offset=0):
            return prepared

    monkeypatch.setattr(execution_service, "QueryForgeService", _NoCodeService)
    monkeypatch.setattr(execution_service, "DomainResolver", lambda workspace_id: object())


def test_execution_start_status_cancel(client, auth_headers, monkeypatch):
    _install_valkey(monkeypatch)
    _install_nocode_prepare(monkeypatch, sql="SELECT 1", params={})

    class _SqlExec:
        def __init__(self):
            self.canceled = []

        def submit_statement_async(self, sql, parameters, **_kwargs):
            assert sql == "SELECT 1"
            assert parameters == {}
            return {"qf_statement_id": "stmt-1"}

        def get_statement_status(self, qf_statement_id):
            return {"status": {"state": "SUCCEEDED"}, "qf_statement_id": qf_statement_id}

        def cancel_statement(self, qf_statement_id):
            self.canceled.append(qf_statement_id)

    class _Ctx:
        sql_exec = _SqlExec()

    class _Builder:
        def build(self, workspace_id: str):
            return _Ctx()

    monkeypatch.setattr(execution_service, "WorkspaceSqlContextBuilder", _Builder)

    resp = client.post(
        "/api/v1/executions/start",
        headers=auth_headers,
        json={"sqlJson": {"domainId": 1}, "kind": "query_builder"},
    )
    assert resp.status_code == 200
    job_id = resp.json["jobId"]
    assert resp.json["statementId"] == "stmt-1"

    status = client.get(f"/api/v1/executions/{job_id}/status", headers=auth_headers)
    assert status.status_code == 200
    assert status.json["status"] == "SUCCEEDED"
    assert status.json["statementId"] == "stmt-1"

    cancel = client.post(f"/api/v1/executions/{job_id}/cancel", headers=auth_headers)
    assert cancel.status_code == 200
    assert cancel.json["ok"] is True


def test_execution_start_validation_error(client, auth_headers, monkeypatch):
    _install_valkey(monkeypatch)

    class _Builder:
        def build(self, workspace_id: str):
            raise AssertionError("Builder should not be called")

    monkeypatch.setattr(execution_service, "WorkspaceSqlContextBuilder", _Builder)

    resp = client.post(
        "/api/v1/executions/start",
        headers=auth_headers,
        json={},
    )
    assert resp.status_code == 400


def test_execution_status_not_found(client, auth_headers, monkeypatch):
    _install_valkey(monkeypatch)

    class _Builder:
        def build(self, workspace_id: str):
            raise AssertionError("Builder should not be called")

    monkeypatch.setattr(execution_service, "WorkspaceSqlContextBuilder", _Builder)

    resp = client.get("/api/v1/executions/missing/status", headers=auth_headers)
    assert resp.status_code == 404


def test_execution_results_success(client, auth_headers, monkeypatch):
    _install_valkey(monkeypatch)
    _install_nocode_prepare(monkeypatch, sql="SELECT 1", params={"a": 1}, qf_rendered_sql="SELECT 1")

    class _SqlExec:
        def submit_statement_async(self, sql, parameters, **_kwargs):
            assert sql == "SELECT 1"
            assert parameters == {"a": 1}
            return {"qf_statement_id": "stmt-2"}

        def get_statement_status(self, qf_statement_id):
            assert qf_statement_id == "stmt-2"
            return {
                "status": {"state": "SUCCEEDED"},
                "manifest": {"schema": {"columns": [{"name": "a", "type": "INT", "nullable": True}]}},
                "result": {"row_count": 2},
            }

        def fetch_all_json(self, qf_statement_id):
            assert qf_statement_id == "stmt-2"
            return [[1], [2]]

    class _Ctx:
        sql_exec = _SqlExec()

    class _Builder:
        def build(self, workspace_id: str):
            return _Ctx()

    monkeypatch.setattr(execution_service, "WorkspaceSqlContextBuilder", _Builder)

    resp = client.post(
        "/api/v1/executions/start",
        headers=auth_headers,
        json={
            "sqlJson": {"domainId": 1},
            "kind": "query_builder",
            "limit": 5,
            "offset": 10,
        },
    )
    assert resp.status_code == 200
    job_id = resp.json["jobId"]

    results = client.get(f"/api/v1/executions/{job_id}/results", headers=auth_headers)
    assert results.status_code == 200
    assert results.json["rows"] == [{"a": 1}, {"a": 2}]
    assert results.json["columns"] == [{"key": "a", "label": "a", "dataType": "INT", "nullable": True}]
    assert results.json["total"] == 2
    assert results.json["totalRowCount"] == 2
    assert results.json["sql"] == "SELECT 1"
    assert results.json["sqlRendered"] == "SELECT 1"
    assert results.json["params"] == {"a": 1}
    assert results.json["limit"] == 5
    assert results.json["offset"] == 10
    assistant = results.json.get("assistant_message") or {}
    assert assistant.get("role") == "assistant"
    assert assistant.get("kind") == "execution_result"
    assert assistant.get("format") == "markdown"
    assert "Query complete." in str(assistant.get("content") or "")
    assert "| a |" in str(assistant.get("content") or "")


def test_execution_results_running(client, auth_headers, monkeypatch):
    _install_valkey(monkeypatch)
    _install_nocode_prepare(monkeypatch, sql="SELECT 1", params={})

    class _SqlExec:
        def submit_statement_async(self, sql, parameters, **_kwargs):
            return {"qf_statement_id": "stmt-3"}

        def get_statement_status(self, qf_statement_id):
            assert qf_statement_id == "stmt-3"
            return {"status": {"state": "RUNNING"}}

    class _Ctx:
        sql_exec = _SqlExec()

    class _Builder:
        def build(self, workspace_id: str):
            return _Ctx()

    monkeypatch.setattr(execution_service, "WorkspaceSqlContextBuilder", _Builder)

    resp = client.post(
        "/api/v1/executions/start",
        headers=auth_headers,
        json={"sqlJson": {"domainId": 1}, "kind": "query_builder"},
    )
    assert resp.status_code == 200
    job_id = resp.json["jobId"]

    results = client.get(f"/api/v1/executions/{job_id}/results", headers=auth_headers)
    assert results.status_code == 409
    assert results.json["status"] == "RUNNING"


def test_execution_results_failed(client, auth_headers, monkeypatch):
    _install_valkey(monkeypatch)
    _install_nocode_prepare(monkeypatch, sql="SELECT 1", params={})

    class _SqlExec:
        def submit_statement_async(self, sql, parameters, **_kwargs):
            return {"qf_statement_id": "stmt-4"}

        def get_statement_status(self, qf_statement_id):
            assert qf_statement_id == "stmt-4"
            return {"status": {"state": "FAILED"}}

    class _Ctx:
        sql_exec = _SqlExec()

    class _Builder:
        def build(self, workspace_id: str):
            return _Ctx()

    monkeypatch.setattr(execution_service, "WorkspaceSqlContextBuilder", _Builder)

    resp = client.post(
        "/api/v1/executions/start",
        headers=auth_headers,
        json={"sqlJson": {"domainId": 1}, "kind": "query_builder"},
    )
    assert resp.status_code == 200
    job_id = resp.json["jobId"]

    results = client.get(f"/api/v1/executions/{job_id}/results", headers=auth_headers)
    assert results.status_code == 500
    assert results.json["status"] == "FAILED"


def test_execution_start_sql_json(client, auth_headers, monkeypatch):
    _install_valkey(monkeypatch)

    class _Prepared:
        sql = "SELECT 2"
        params = {"x": 1}
        qf_rendered_sql = "SELECT 2"
        qf_count_sql = "SELECT COUNT(*) AS total FROM t"

    class _NoCodeService:
        def __init__(self, executor, domain_resolver):
            self.executor = executor
            self.domain_resolver = domain_resolver

        def prepare(self, raw_query, mode="preview", limit=200, offset=0):
            assert raw_query == {"domainId": 1}
            assert mode == "preview"
            assert limit == 25
            assert offset == 5
            return _Prepared()

    class _SqlExec:
        def submit_statement_async(self, sql, parameters, **_kwargs):
            assert sql == "SELECT 2"
            assert parameters == {"x": 1}
            return {"qf_statement_id": "stmt-5"}

    class _Ctx:
        sql_exec = _SqlExec()

    class _Builder:
        def build(self, workspace_id: str):
            return _Ctx()

    monkeypatch.setattr(execution_service, "WorkspaceSqlContextBuilder", _Builder)
    monkeypatch.setattr(execution_service, "QueryForgeService", _NoCodeService)
    monkeypatch.setattr(execution_service, "DomainResolver", lambda workspace_id: object())

    resp = client.post(
        "/api/v1/executions/start?limit=25&offset=5",
        headers=auth_headers,
        json={"sqlJson": {"domainId": 1}, "kind": "query_builder"},
    )
    assert resp.status_code == 200
    job_id = resp.json["jobId"]

    job = execution_service._get_job(job_id)
    assert job["sql"] == "SELECT 2"
    assert job["sqlRendered"] == "SELECT 2"
    assert job["params"] == {"x": 1}
    assert job["limit"] == 25
    assert job["offset"] == 5
    assert job["countSql"] == "SELECT COUNT(*) AS total FROM t"


def test_execution_start_rejects_raw_sql_fields(client, auth_headers, monkeypatch):
    _install_valkey(monkeypatch)

    class _Builder:
        def build(self, workspace_id: str):
            raise AssertionError("Builder should not be called")

    monkeypatch.setattr(execution_service, "WorkspaceSqlContextBuilder", _Builder)

    resp = client.post(
        "/api/v1/executions/start",
        headers=auth_headers,
        json={"sqlJson": {"domainId": 1}, "sql": "SELECT 1", "kind": "query_builder"},
    )
    assert resp.status_code == 400
    assert "Raw SQL fields are not allowed" in resp.json["error"]


def test_execution_start_accepts_read_only_raw_sql_preview(client, auth_headers, monkeypatch):
    _install_valkey(monkeypatch)

    class _SqlExec:
        def submit_statement_async(self, sql, parameters, **_kwargs):
            assert sql == "SELECT patient_id FROM dim_patient"
            assert parameters == {}
            return {"qf_statement_id": "stmt-raw-1"}

    class _Ctx:
        sql_exec = _SqlExec()

    class _Builder:
        def build(self, workspace_id: str):
            return _Ctx()

    monkeypatch.setattr(execution_service, "WorkspaceSqlContextBuilder", _Builder)

    resp = client.post(
        "/api/v1/executions/start",
        headers=auth_headers,
        json={
            "kind": "query_builder_sql",
            "rawSql": "SELECT patient_id FROM dim_patient",
            "limit": 25,
            "offset": 0,
        },
    )
    assert resp.status_code == 200
    job_id = resp.json["jobId"]
    job = execution_service._get_job(job_id)
    assert job["kind"] == "query_builder_sql"
    assert job["sql"] == "SELECT patient_id FROM dim_patient"
    assert job["sqlRendered"] == "SELECT patient_id FROM dim_patient"
    assert job["params"] == {}
    assert job["countSql"] is None


def test_execution_start_rejects_mutating_raw_sql_preview(client, auth_headers, monkeypatch):
    _install_valkey(monkeypatch)

    class _Builder:
        def build(self, workspace_id: str):
            raise AssertionError("Builder should not be called for rejected SQL")

    monkeypatch.setattr(execution_service, "WorkspaceSqlContextBuilder", _Builder)

    resp = client.post(
        "/api/v1/executions/start",
        headers=auth_headers,
        json={
            "kind": "query_builder_sql",
            "rawSql": "DELETE FROM dim_patient",
        },
    )
    assert resp.status_code == 400
    assert "must be read-only" in resp.json["error"]


def test_execution_status_and_results_use_inline_snapshot_for_sync_adapter(client, auth_headers, monkeypatch):
    _install_valkey(monkeypatch)
    _install_nocode_prepare(monkeypatch, sql="SELECT 7 AS a", params={})

    class _SqlExec:
        def submit_statement_async(self, sql, parameters, **_kwargs):
            return {"qf_statement_id": "stmt-inline", "status": {"state": "SUCCEEDED"}}

        def fetch_all_json(self, qf_statement_id):
            assert qf_statement_id == "stmt-inline"
            return [[7]]

        def get_statement_status(self, qf_statement_id):
            # Simulate fresh process/instance where in-memory statements are gone.
            return {"status": {"state": "FAILED", "error": "statement not found"}}

    class _Ctx:
        sql_exec = _SqlExec()

    class _Builder:
        def build(self, workspace_id: str):
            return _Ctx()

    monkeypatch.setattr(execution_service, "WorkspaceSqlContextBuilder", _Builder)
    monkeypatch.setattr(execution_service, "AnalyticsExecutorForgeAdapter", _SqlExec)

    start = client.post(
        "/api/v1/executions/start",
        headers=auth_headers,
        json={"sqlJson": {"domainId": 1}, "kind": "query_builder"},
    )
    assert start.status_code == 200
    job_id = start.json["jobId"]

    status = client.get(f"/api/v1/executions/{job_id}/status", headers=auth_headers)
    assert status.status_code == 200
    assert status.json["status"] == "SUCCEEDED"

    results = client.get(f"/api/v1/executions/{job_id}/results", headers=auth_headers)
    assert results.status_code == 200
    assert results.json["rows"] == [{"a": 7}]
