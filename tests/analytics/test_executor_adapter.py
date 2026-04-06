from __future__ import annotations

import pytest

from app.services.analytics.executor_adapter import AnalyticsExecutorForgeAdapter


class _Executor:
    def __init__(self, *, rows=None, exc: Exception | None = None) -> None:
        self._rows = list(rows or [])
        self._exc = exc

    def execute(self, sql: str, params: dict | None = None) -> list[dict]:
        del sql, params
        if self._exc is not None:
            raise self._exc
        return list(self._rows)

    def test_connection(self) -> None:
        return None

    def get_dialect(self) -> str:
        return "snowflake"


def test_submit_statement_async_records_expected_runtime_failures() -> None:
    adapter = AnalyticsExecutorForgeAdapter(_Executor(exc=RuntimeError("query failed")))

    result = adapter.submit_statement_async("select 1")

    assert result["status"]["state"] == "FAILED"
    assert result["status"]["error"] == "query failed"


def test_submit_statement_async_surfaces_unexpected_executor_errors() -> None:
    adapter = AnalyticsExecutorForgeAdapter(_Executor(exc=AssertionError("unexpected executor bug")))

    with pytest.raises(AssertionError, match="unexpected executor bug"):
        adapter.submit_statement_async("select 1")
