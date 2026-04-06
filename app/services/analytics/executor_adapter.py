from __future__ import annotations

import uuid
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List, Mapping, Optional

from app.ports.sql_executor import ForgeExecResult, ForgeQueryPort
from app.ports.sql_executor_abc import SQLExecutor

ASYNC_STATEMENT_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError)


@dataclass
class _StatementRecord:
    state: str
    rows: List[Dict[str, Any]]
    error: Optional[str] = None


class AnalyticsExecutorForgeAdapter(ForgeQueryPort):
    """Adapt an analytics ``SQLExecutor`` to the ``ForgeQueryPort`` contract.

    This provides synchronous execution and emulates async statement lifecycle so
    existing execution endpoints can continue to operate for non-Databricks datasources.
    """

    def __init__(self, executor: SQLExecutor):
        self._executor = executor
        self._statements: Dict[str, _StatementRecord] = {}
        self._lock = Lock()

    def submit_statement(
        self,
        sql: str,
        *,
        warehouse_id: Optional[str] = None,
        parameters: Optional[Mapping[str, Any]] = None,
        wait: bool = True,
        qf_timeout_s: int = 120,
        qf_result_fmt: Optional[str] = None,
    ) -> Dict[str, Any]:
        del warehouse_id, wait, qf_timeout_s, qf_result_fmt
        rows = self._executor.execute(sql, dict(parameters or {}))
        return {"status": {"state": "SUCCEEDED"}, "rows": rows}

    def submit_statement_async(
        self,
        sql: str,
        parameters: Optional[Mapping[str, Any]] = None,
        *,
        warehouse_id: Optional[str] = None,
        catalog: Optional[str] = None,
        schema: Optional[str] = None,
        qf_result_fmt: str = "JSON_ARRAY",
    ) -> Dict[str, Any]:
        del warehouse_id, catalog, schema, qf_result_fmt
        statement_id = uuid.uuid4().hex
        try:
            rows = self._executor.execute(sql, dict(parameters or {}))
            record = _StatementRecord(state="SUCCEEDED", rows=rows)
        except ASYNC_STATEMENT_FALLBACK_ERRORS as exc:
            record = _StatementRecord(state="FAILED", rows=[], error=str(exc))

        with self._lock:
            self._statements[statement_id] = record

        return {
            "qf_statement_id": statement_id,
            "statement_id": statement_id,
            "status": {"state": record.state, "error": record.error},
        }

    def get_statement_status(self, qf_statement_id: str) -> Dict[str, Any]:
        with self._lock:
            record = self._statements.get(qf_statement_id)
        if not record:
            return {"status": {"state": "FAILED", "error": "statement not found"}}
        return {"status": {"state": record.state, "error": record.error}}

    def cancel_statement(self, qf_statement_id: str) -> None:
        with self._lock:
            record = self._statements.get(qf_statement_id)
            if record:
                record.state = "CANCELED"

    def poll_status(self, qf_statement_id: str) -> Dict[str, Any]:
        return self.get_statement_status(qf_statement_id)

    def fetch_all_json(self, qf_statement_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            record = self._statements.get(qf_statement_id)
        if not record:
            return []
        return list(record.rows)

    def cancel(self, qf_statement_id: str) -> None:
        self.cancel_statement(qf_statement_id)

    def execute_write(self, query: str, params: Optional[Mapping[str, Any]] = None) -> int:
        rows = self._executor.execute(query, dict(params or {}))
        return int(len(rows or []))

    def execute_query_mappings(self, query: str, params: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._executor.execute(query, dict(params or {}))

    def execute_query(self, query: str, params: Optional[Mapping[str, Any]] = None):
        rows = self._executor.execute(query, dict(params or {}))
        if not rows:
            return []
        return [tuple(row.values()) for row in rows]

    def execute_insert(self, query: str, params: Optional[Mapping[str, Any]] = None) -> ForgeExecResult:
        count = self.execute_write(query, params)
        return ForgeExecResult(rowcount=count, lastrowid=None)

    def transaction(self):
        raise NotImplementedError("AnalyticsExecutorForgeAdapter does not support transactions")
