from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.result import Result
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool

from app.config import DB_URI, MAX_OVERFLOW, POOL_RECYCLE, POOL_SIZE, POOL_TIMEOUT
from app.ports.sql_executor import ForgeExecResult, ForgeQueryPort, ForgeQueryTx

logger = logging.getLogger(__name__)

_SLOW_QUERY_WARN_MS: int = 1000

_engine = create_engine(
    DB_URI,
    poolclass=QueuePool,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
    pool_pre_ping=True,
)

# Backward-compatible public engine export used across route/service modules.
engine = _engine


@contextmanager
def _timed(label: str, query: str):
    """Emit a structured warning if query execution exceeds the slow-query threshold."""
    t0 = time.monotonic()
    yield
    elapsed_ms = (time.monotonic() - t0) * 1000
    if elapsed_ms >= _SLOW_QUERY_WARN_MS:
        logger.warning(
            "slow_%s elapsed_ms=%.0f sql=%r",
            label,
            elapsed_ms,
            query.strip()[:120].replace("\n", " "),
        )


def open_forge_connection() -> Connection:
    return _engine.connect()


def execute_query(query: str, params: Optional[Dict[str, Any]] = None) -> List[Tuple]:
    with _timed("read", query):
        with open_forge_connection() as conn:
            result: Result = conn.execute(text(query), params or {})
            return result.fetchall()


def show_status() -> None:
    logger.info("DB_URI=%s", DB_URI)


def execute_query_mappings(query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    with _timed("read", query):
        with open_forge_connection() as conn:
            result: Result = conn.execute(text(query), params or {})
            return [dict(r) for r in result.mappings().all()]


def execute_write(query: str, params: Optional[Dict[str, Any]] = None) -> int:
    """Execute INSERT/UPDATE/DELETE and return the affected rowcount."""
    with _timed("write", query):
        with open_forge_connection() as conn:
            tx = conn.begin()
            try:
                result = conn.execute(text(query), params or {})
                tx.commit()
                return int(result.rowcount or 0)
            except SQLAlchemyError:
                tx.rollback()
                raise


class ForgeMetaSQL(ForgeQueryPort):
    @contextmanager
    def transaction(self) -> Iterator[ForgeQueryTx]:
        conn = open_forge_connection()
        tx = conn.begin()
        try:
            yield _ForgeTransaction(conn)
            tx.commit()
        except SQLAlchemyError:
            tx.rollback()
            raise
        finally:
            conn.close()

    def submit_statement(
        self,
        sql: str,
        *,
        warehouse_id: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        wait: bool = True,
        qf_timeout_s: int = 120,
        qf_result_fmt: Optional[str] = None,
    ) -> Dict[str, Any]:
        del warehouse_id, wait, qf_timeout_s, qf_result_fmt
        sql_str = (sql or "").strip()
        if sql_str.lower().startswith("select"):
            rows = execute_query_mappings(sql_str, parameters or {})
            return {"status": {"state": "SUCCEEDED"}, "rows": rows}
        affected = execute_write(sql_str, parameters or {})
        return {"status": {"state": "SUCCEEDED"}, "rowcount": affected, "rows": []}

    def poll_status(self, qf_statement_id: str) -> Dict[str, Any]:
        del qf_statement_id
        return {"status": {"state": "SUCCEEDED"}}

    def fetch_all_json(self, qf_statement_id: str) -> List[Dict[str, Any]]:
        del qf_statement_id
        return []

    def cancel(self, qf_statement_id: str) -> None:
        del qf_statement_id

    def execute_write(self, query: str, params: Optional[Dict[str, Any]] = None) -> int:
        return execute_write(query, params)

    def execute_query_mappings(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return execute_query_mappings(query, params)

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Tuple]:
        return execute_query(query, params)

    def execute_insert(self, query: str, params: Optional[Dict[str, Any]] = None) -> ForgeExecResult:
        with open_forge_connection() as conn:
            tx = conn.begin()
            try:
                result = conn.execute(text(query), params or {})
                tx.commit()
                return ForgeExecResult(rowcount=int(result.rowcount or 0), lastrowid=result.lastrowid)
            except SQLAlchemyError:
                tx.rollback()
                raise


class _ForgeTransaction(ForgeQueryTx):
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def execute_write(self, query: str, params: Optional[Dict[str, Any]] = None) -> int:
        with _timed("tx_write", query):
            result = self._conn.execute(text(query), params or {})
            return int(result.rowcount or 0)

    def execute_query_mappings(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        with _timed("tx_read", query):
            result: Result = self._conn.execute(text(query), params or {})
            return [dict(r) for r in result.mappings().all()]

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Tuple]:
        with _timed("tx_read", query):
            result: Result = self._conn.execute(text(query), params or {})
            return result.fetchall()

    def execute_insert(self, query: str, params: Optional[Dict[str, Any]] = None) -> ForgeExecResult:
        with _timed("tx_insert", query):
            result = self._conn.execute(text(query), params or {})
            return ForgeExecResult(rowcount=int(result.rowcount or 0), lastrowid=result.lastrowid)


def ensure_workspace(conn: Connection, workspace_id: str, display_name: Optional[str] = None) -> None:
    conn.execute(
        text(
            """
            INSERT INTO workspace (id, display_name)
            VALUES (:id, :display_name)
            ON DUPLICATE KEY UPDATE id=id
            """
        ),
        {"id": workspace_id, "display_name": display_name},
    )
