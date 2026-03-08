import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.result import Result
from sqlalchemy.pool import QueuePool

from app.config import DB_URI, MAX_OVERFLOW, POOL_RECYCLE, POOL_SIZE, POOL_TIMEOUT
from app.ports.sql_executor import ForgeExecResult, ForgeQueryPort, ForgeQueryTx

logger = logging.getLogger(__name__)

engine = create_engine(
    DB_URI,
    poolclass=QueuePool,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
)


def open_forge_connection() -> Connection:
    """
    Connects to the database and returns a connection.

    Returns:
        Connection: A SQLAlchemy database connection object.
    """
    return engine.connect()


def execute_query(query: str, params: dict[str, Any] = None) -> List[Tuple]:
    """
    Executes a database query and returns the results.

    :param query: The SQL query to execute.
    :type query: str
    :param params: Optional query parameters.
    :type params: dict[str, Any], optional

    Returns:
        List[Tuple]: The results of the database query.
    """
    with open_forge_connection() as conn:
        result: Result = conn.execute(text(query), params or {})
        return result.fetchall()


def show_status():
    logger.info(f"URI: {DB_URI}")


def execute_query_mappings(query: str, params: dict[str, Any] = None) -> List[dict[str, Any]]:
    with open_forge_connection() as conn:
        result: Result = conn.execute(text(query), params or {})
        return [dict(r) for r in result.mappings().all()]


def execute_write(query: str, params: Optional[Dict[str, Any]] = None) -> int:
    """
    Executes INSERT/UPDATE/DELETE. Returns affected rowcount.
    """
    with open_forge_connection() as conn:
        tx = conn.begin()
        try:
            result = conn.execute(text(query), params or {})
            tx.commit()
            return int(result.rowcount or 0)
        except Exception:
            tx.rollback()
            raise


class ForgeMetaSQL(ForgeQueryPort):
    @contextmanager
    def transaction(self) -> Iterator[ForgeQueryTx]:
        conn = open_forge_connection()
        tx = conn.begin()
        try:
            yield _ForgeMetaTransaction(conn)
            tx.commit()
        except Exception:
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
        return None

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
            except Exception:
                tx.rollback()
                raise


class _ForgeMetaTransaction(ForgeQueryTx):
    def __init__(self, conn: Connection):
        self._conn = conn

    def execute_write(self, query: str, params: Optional[Dict[str, Any]] = None) -> int:
        result = self._conn.execute(text(query), params or {})
        return int(result.rowcount or 0)

    def execute_query_mappings(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        result: Result = self._conn.execute(text(query), params or {})
        return [dict(r) for r in result.mappings().all()]

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Tuple]:
        result: Result = self._conn.execute(text(query), params or {})
        return result.fetchall()

    def execute_insert(self, query: str, params: Optional[Dict[str, Any]] = None) -> ForgeExecResult:
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
