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
