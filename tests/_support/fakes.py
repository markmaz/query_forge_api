from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from app.ports.sql_executor import ForgeExecResult, ForgeQueryPort, ForgeQueryTx


@dataclass
class CapturedCall:
    query: str
    params: Optional[Mapping[str, Any]] = None


class FakeForgeQueryTx(ForgeQueryTx):
    def __init__(self, parent: "FakeForgeQueryPort") -> None:
        self._parent = parent

    def execute_write(self, query: str, params: Optional[Mapping[str, Any]] = None) -> int:
        return self._parent.execute_write(query, params)

    def execute_query_mappings(self, query: str, params: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._parent.execute_query_mappings(query, params)

    def execute_query(self, query: str, params: Optional[Mapping[str, Any]] = None) -> List[Tuple]:
        return self._parent.execute_query(query, params)

    def execute_insert(self, query: str, params: Optional[Mapping[str, Any]] = None) -> ForgeExecResult:
        return self._parent.execute_insert(query, params)


class FakeForgeQueryPort(ForgeQueryPort):
    def __init__(self) -> None:
        self.write_calls: List[CapturedCall] = []
        self.query_calls: List[CapturedCall] = []
        self.query_mappings_calls: List[CapturedCall] = []
        self.insert_calls: List[CapturedCall] = []
        self.query_responses: List[List[Tuple]] = []
        self.query_mappings_responses: List[List[Dict[str, Any]]] = []
        self.write_responses: List[int] = []
        self.insert_responses: List[ForgeExecResult] = []
        self.write_exceptions: List[Exception] = []
        self.query_exceptions: List[Exception] = []
        self.query_mappings_exceptions: List[Exception] = []
        self.insert_exceptions: List[Exception] = []

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
        raise NotImplementedError

    def poll_status(self, qf_statement_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def fetch_all_json(self, qf_statement_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def cancel(self, qf_statement_id: str) -> None:
        raise NotImplementedError

    def execute_write(self, query: str, params: Optional[Mapping[str, Any]] = None) -> int:
        self.write_calls.append(CapturedCall(query=query, params=params))
        if self.write_exceptions:
            raise self.write_exceptions.pop(0)
        if self.write_responses:
            return int(self.write_responses.pop(0))
        return 0

    def execute_query_mappings(self, query: str, params: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
        self.query_mappings_calls.append(CapturedCall(query=query, params=params))
        if self.query_mappings_exceptions:
            raise self.query_mappings_exceptions.pop(0)
        if self.query_mappings_responses:
            return self.query_mappings_responses.pop(0)
        return []

    def execute_query(self, query: str, params: Optional[Mapping[str, Any]] = None) -> List[Tuple]:
        self.query_calls.append(CapturedCall(query=query, params=params))
        if self.query_exceptions:
            raise self.query_exceptions.pop(0)
        if self.query_responses:
            return self.query_responses.pop(0)
        return []

    def execute_insert(self, query: str, params: Optional[Mapping[str, Any]] = None) -> ForgeExecResult:
        self.insert_calls.append(CapturedCall(query=query, params=params))
        if self.insert_exceptions:
            raise self.insert_exceptions.pop(0)
        if self.insert_responses:
            return self.insert_responses.pop(0)
        return ForgeExecResult(rowcount=1, lastrowid=1)

    @contextmanager
    def transaction(self) -> Iterable[ForgeQueryTx]:
        yield FakeForgeQueryTx(self)


class FakeDatabricksForgeQueryPort:
    def __init__(self) -> None:
        self.submit_calls: List[CapturedCall] = []
        self.submit_responses: List[Dict[str, Any]] = []

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
        del warehouse_id, parameters, wait, qf_timeout_s, qf_result_fmt
        self.submit_calls.append(CapturedCall(query=sql))
        if self.submit_responses:
            return self.submit_responses.pop(0)
        return {}


class FakeDomainResolver:
    def __init__(self, plan: Optional[Any] = None) -> None:
        self.plan = plan
        self.resolve_calls: List[int] = []
        self.resolve_plan_calls: List[int] = []

    def resolve(self, domain_id: int) -> Any:
        self.resolve_calls.append(domain_id)
        return self.plan

    def resolve_plan(self, domain_id: int) -> Any:
        self.resolve_plan_calls.append(domain_id)
        return self.plan
