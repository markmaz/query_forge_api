from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ContextManager, Dict, List, Mapping, Optional, Protocol, Tuple, runtime_checkable


@dataclass(frozen=True)
class QueryExecResult:
    rowcount: int
    lastrowid: Optional[int] = None


@runtime_checkable
class QueryTransaction(Protocol):
    def execute_write(self, query: str, params: Optional[Mapping[str, Any]] = None) -> int: ...
    def execute_query_mappings(self, query: str, params: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]: ...
    def execute_query(self, query: str, params: Optional[Mapping[str, Any]] = None) -> List[Tuple]: ...
    def execute_insert(self, query: str, params: Optional[Mapping[str, Any]] = None) -> QueryExecResult: ...


@runtime_checkable
class QueryPort(Protocol):
    """Abstract SQL executor used by QueryForge services (injectable)."""

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
        """Submit a SQL statement. If wait=True, blocks until DONE/FAILED/CANCELED, else returns handle immediately."""

    def poll_status(self, qf_statement_id: str) -> Dict[str, Any]:
        """Polls the statement status payload (RAW response dict)."""

    def fetch_all_json(self, qf_statement_id: str) -> List[Dict[str, Any]]:
        """Fetches all results as a list[dict] (handles pagination/external links)."""

    def cancel(self, qf_statement_id: str) -> None:
        """Attempts to cancel the running statement (best effort)."""

    def execute_write(self, query: str, params: Optional[Mapping[str, Any]] = None) -> int:
        """Executes INSERT/UPDATE/DELETE. Returns affected rowcount."""

    def execute_query_mappings(self, query: str, params: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
        """Executes a query and returns list of dict rows."""

    def execute_query(self, query: str, params: Optional[Mapping[str, Any]] = None) -> List[Tuple]:
        """Executes a query and returns list of tuple rows."""

    def execute_insert(self, query: str, params: Optional[Mapping[str, Any]] = None) -> QueryExecResult:
        """Executes INSERT and returns rowcount + lastrowid."""

    def transaction(self) -> ContextManager[QueryTransaction]:
        """Starts a transaction context."""


# Legacy aliases — existing code uses ForgeQueryPort / ForgeExecResult / ForgeQueryTx
ForgeExecResult = QueryExecResult
ForgeQueryTx = QueryTransaction
ForgeQueryPort = QueryPort
