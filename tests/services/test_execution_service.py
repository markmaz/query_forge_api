from __future__ import annotations

import pytest

import app.services.execution_service as execution_service


class _FakeValkey:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def setex(self, key: str, _ttl: int, value: str) -> bool:
        self.store[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def delete(self, key: str) -> str | None:
        return self.store.pop(key, None)


class _PreparedMode:
    def prepare(
        self,
        *,
        workspace_id: str,
        sql_exec,
        sql_json,
        mode: str,
        limit: int,
        offset: int,
    ):
        del workspace_id, sql_exec, sql_json, mode, limit, offset

        class _Prepared:
            sql = "SELECT 1"
            params = {}
            sql_rendered = "SELECT 1"
            count_sql = None

        return _Prepared()


def test_start_falls_back_when_inline_rows_fetch_raises_expected_error(monkeypatch) -> None:
    client = _FakeValkey()
    monkeypatch.setattr(execution_service, "_get_valkey_client", lambda: client)

    class _SqlExec:
        def submit_statement_async(self, sql, parameters):
            assert sql == "SELECT 1"
            assert parameters == {}
            return {"statement_id": "stmt-inline", "status": {"state": "SUCCEEDED"}}

        def fetch_all_json(self, statement_id: str):
            assert statement_id == "stmt-inline"
            raise TypeError("inline rows unavailable")

    class _Ctx:
        sql_exec = _SqlExec()

    class _Builder:
        def build(self, workspace_id: str):
            assert workspace_id == "ws1"
            return _Ctx()

    monkeypatch.setattr(execution_service, "AnalyticsExecutorForgeAdapter", _SqlExec)

    service = execution_service.ExecutionService(context_builder=_Builder())
    service._query_builder_mode = _PreparedMode()

    payload, status_code = service.start("ws1", {"sqlJson": {"domainId": 1}, "kind": "query_builder"}, {})

    assert status_code == 200
    job = execution_service._get_job(payload["jobId"])
    assert job is not None
    assert job["inline_status"] == {"state": "SUCCEEDED"}
    assert job["inline_rows"] is None


def test_start_surfaces_unexpected_inline_rows_fetch_errors(monkeypatch) -> None:
    client = _FakeValkey()
    monkeypatch.setattr(execution_service, "_get_valkey_client", lambda: client)

    class _SqlExec:
        def submit_statement_async(self, sql, parameters):
            assert sql == "SELECT 1"
            assert parameters == {}
            return {"statement_id": "stmt-inline", "status": {"state": "SUCCEEDED"}}

        def fetch_all_json(self, statement_id: str):
            assert statement_id == "stmt-inline"
            raise AssertionError("unexpected inline fetch failure")

    class _Ctx:
        sql_exec = _SqlExec()

    class _Builder:
        def build(self, workspace_id: str):
            assert workspace_id == "ws1"
            return _Ctx()

    monkeypatch.setattr(execution_service, "AnalyticsExecutorForgeAdapter", _SqlExec)

    service = execution_service.ExecutionService(context_builder=_Builder())
    service._query_builder_mode = _PreparedMode()

    with pytest.raises(AssertionError, match="unexpected inline fetch failure"):
        service.start("ws1", {"sqlJson": {"domainId": 1}, "kind": "query_builder"}, {})


def test_execution_service_uses_keyword_workspace_id_for_domain_resolver(monkeypatch) -> None:
    captured = {}

    class _SqlExec:
        pass

    class _Ctx:
        sql_exec = _SqlExec()

    class _Builder:
        def build(self, workspace_id: str):
            assert workspace_id == "ws1"
            return _Ctx()

    class _Prepared:
        sql = "SELECT 1"
        params = {}
        qf_rendered_sql = "SELECT 1"
        qf_count_sql = None

    class _QueryForgeService:
        def __init__(self, executor, domain_resolver):
            captured["executor"] = executor
            captured["domain_resolver"] = domain_resolver

        def prepare(self, raw_query, mode="preview", limit=200, offset=0):
            assert raw_query == {"domainId": 1}
            return _Prepared()

    class _DomainResolver:
        def __init__(self, *, workspace_id: str, allow_ambiguous: bool = False, sql=None):
            captured["workspace_id"] = workspace_id
            captured["allow_ambiguous"] = allow_ambiguous
            captured["sql"] = sql

    monkeypatch.setattr(execution_service, "_get_valkey_client", lambda: _FakeValkey())
    monkeypatch.setattr(execution_service, "QueryForgeService", _QueryForgeService)
    monkeypatch.setattr(execution_service, "DomainResolver", _DomainResolver)

    service = execution_service.ExecutionService(context_builder=_Builder())

    class _SubmitExec(_SqlExec):
        def submit_statement_async(self, sql, parameters):
            assert sql == "SELECT 1"
            assert parameters == {}
            return {"statement_id": "stmt-kw"}

    _Ctx.sql_exec = _SubmitExec()
    payload, status_code = service.start("ws1", {"sqlJson": {"domainId": 1}, "kind": "query_builder"}, {})

    assert status_code == 200
    assert payload["statementId"] == "stmt-kw"
    assert captured["workspace_id"] == "ws1"
    assert captured["allow_ambiguous"] is False


def test_start_routes_flowforge_domains_to_metadata_executor(monkeypatch) -> None:
    client = _FakeValkey()
    monkeypatch.setattr(execution_service, "_get_valkey_client", lambda: client)

    class _Builder:
        def build(self, workspace_id: str):
            raise AssertionError("workspace datasource should not be initialized for FlowForge reporting domains")

    class _Prepared:
        sql = "SELECT mode, COUNT(*) AS total FROM query_forge_rbac.v_flowforge_report_intake_events GROUP BY mode"
        params = {}
        qf_rendered_sql = sql
        qf_count_sql = None

    class _MetadataSqlExec:
        def submit_statement_async(self, sql, parameters):
            assert sql == _Prepared.sql
            assert parameters == {}
            return {"statement_id": "stmt-flowforge", "status": {"state": "SUCCEEDED"}}

        def fetch_all_json(self, statement_id: str):
            assert statement_id == "stmt-flowforge"
            return [{"mode": "production", "total": 2}]

    metadata_exec = _MetadataSqlExec()

    class _QueryForgeService:
        def __init__(self, executor, domain_resolver):
            assert executor is metadata_exec
            self.domain_resolver = domain_resolver

        def prepare(self, raw_query, mode="preview", limit=200, offset=0):
            assert raw_query == {"domainId": 29}
            assert mode == "preview"
            assert limit == 200
            assert offset == 0
            return _Prepared()

    class _DomainResolver:
        def __init__(self, *, workspace_id: str, allow_ambiguous: bool = False, sql=None):
            assert workspace_id == "ws1"
            assert allow_ambiguous is False
            assert sql is None

    monkeypatch.setattr(execution_service, "QueryForgeService", _QueryForgeService)
    monkeypatch.setattr(execution_service, "DomainResolver", _DomainResolver)
    monkeypatch.setattr(execution_service, "AnalyticsExecutorForgeAdapter", _MetadataSqlExec)
    monkeypatch.setattr(
        execution_service,
        "_sql_json_uses_flowforge_metadata_domain",
        lambda *, workspace_id, sql_json: workspace_id == "ws1" and sql_json == {"domainId": 29},
    )
    monkeypatch.setattr(execution_service, "_build_metadata_sql_exec", lambda: metadata_exec)

    service = execution_service.ExecutionService(context_builder=_Builder())

    payload, status_code = service.start("ws1", {"sqlJson": {"domainId": 29}, "kind": "query_builder"}, {})

    assert status_code == 200
    assert payload["statementId"] == "stmt-flowforge"
    job = execution_service._get_job(payload["jobId"])
    assert job is not None
    assert job["execution_backend"] == "queryforge_metadata"
    assert job["inline_rows"] == [{"mode": "production", "total": 2}]

    results, results_status = service.results("ws1", payload["jobId"])

    assert results_status == 200
    assert results["rows"] == [{"mode": "production", "total": 2}]


def test_start_records_inline_total_for_sync_adapter(monkeypatch) -> None:
    client = _FakeValkey()
    monkeypatch.setattr(execution_service, "_get_valkey_client", lambda: client)

    class _SqlExec:
        def submit_statement_async(self, sql, parameters):
            assert sql == "SELECT mode, COUNT(*) AS total FROM t GROUP BY mode"
            assert parameters == {"p1": "ws1"}
            return {"statement_id": "stmt-inline", "status": {"state": "SUCCEEDED"}}

        def fetch_all_json(self, statement_id: str):
            assert statement_id == "stmt-inline"
            return [{"mode": "production", "total": 2}]

        def submit_statement(self, sql, parameters=None):
            assert sql == "SELECT COUNT(*) AS total FROM t"
            assert parameters == {"p1": "ws1"}
            return {"rows": [{"total": 42}]}

    class _Ctx:
        sql_exec = _SqlExec()

    class _Builder:
        def build(self, workspace_id: str):
            assert workspace_id == "ws1"
            return _Ctx()

    class _PreparedMode:
        def prepare(
            self,
            *,
            workspace_id: str,
            sql_exec,
            sql_json,
            mode: str,
            limit: int,
            offset: int,
        ):
            assert workspace_id == "ws1"
            assert isinstance(sql_exec, _SqlExec)
            assert sql_json == {"domainId": 1}
            assert mode == "preview"
            assert limit == 200
            assert offset == 0

            class _Prepared:
                sql = "SELECT mode, COUNT(*) AS total FROM t GROUP BY mode"
                params = {"p1": "ws1"}
                sql_rendered = "SELECT mode, COUNT(*) AS total FROM t GROUP BY mode"
                count_sql = "SELECT COUNT(*) AS total FROM t"

            return _Prepared()

    monkeypatch.setattr(execution_service, "AnalyticsExecutorForgeAdapter", _SqlExec)

    service = execution_service.ExecutionService(context_builder=_Builder())
    service._query_builder_mode = _PreparedMode()

    payload, status_code = service.start("ws1", {"sqlJson": {"domainId": 1}, "kind": "query_builder"}, {})

    assert status_code == 200
    job = execution_service._get_job(payload["jobId"])
    assert job is not None
    assert job["inline_rows"] == [{"mode": "production", "total": 2}]
    assert job["inline_total"] == 42
