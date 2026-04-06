from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.ports.sql_executor_abc import SQLExecutor

logger = logging.getLogger(__name__)

MYSQL_EXECUTION_ERRORS = (
    SQLAlchemyError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


class MySQLAnalyticsSQLExecutor(SQLExecutor):
    """Analytics executor for external MySQL databases.

    This class is for analytics (read) connections to MySQL databases that are
    **not** the QueryForge application database.  It maintains its own SQLAlchemy
    engine, completely separate from the ``ForgeMetaSQL`` application engine.

    ``NullPool`` is used so that connections are not pooled — each ``execute()``
    call opens and closes its own connection.

    SSL is required for all connections (FIND-022).  Provide ``ssl_ca`` (path to
    the CA certificate PEM file) to verify the server certificate.  If ``ssl_ca``
    is omitted the connection is refused at construction time so that plain-text
    analytics connections can never be made silently.

    :param host: MySQL server hostname or IP address.
    :param port: MySQL server port (typically 3306).
    :param database: Database / schema name.
    :param user: MySQL username.
    :param password: MySQL password.
    :param ssl_ca: Path to PEM CA certificate file for server certificate
        verification.  Required — connections without SSL are rejected.
    """

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        ssl_ca: Optional[str] = None,
    ) -> None:
        if not host:
            raise ValueError("MySQLAnalyticsSQLExecutor: 'host' is required")
        if not database:
            raise ValueError("MySQLAnalyticsSQLExecutor: 'database' is required")
        if not user:
            raise ValueError("MySQLAnalyticsSQLExecutor: 'user' is required")
        if not password:
            raise ValueError("MySQLAnalyticsSQLExecutor: 'password' is required")
        # FIND-022: SSL is mandatory for analytics MySQL connections to prevent
        # credentials and query results from being transmitted in plaintext.
        if not ssl_ca:
            raise ValueError(
                "MySQLAnalyticsSQLExecutor: 'ssl_ca' is required — "
                "plaintext MySQL analytics connections are not permitted"
            )

        self._host = host
        self._port = int(port)
        self._database = database
        self._user = user

        # Never log the password
        uri = (
            f"mysql+pymysql://{user}:{password}"
            f"@{host}:{self._port}/{database}"
        )

        # FIND-022: pass SSL parameters to pymysql via connect_args so that the
        # CA certificate is verified on every connection.
        ssl_args = {"ssl_ca": ssl_ca, "ssl_verify_cert": True}

        # NullPool — no persistent connections across execute() calls
        self._engine = create_engine(uri, poolclass=NullPool, connect_args=ssl_args)

        logger.debug(
            "MySQLAnalyticsSQLExecutor initialised: host=%s port=%d database=%s user=%s",
            self._host,
            self._port,
            self._database,
            self._user,
        )

    # ------------------------------------------------------------------
    # SQLExecutor interface
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: Optional[dict] = None) -> list[dict]:
        """Execute *sql* against the analytics MySQL database.

        Opens and closes a connection for each call.

        :param sql: SQL statement to execute.
        :param params: Optional named parameters (``:{name}`` placeholders).
        :returns: List of row dicts.
        :raises RuntimeError: on execution failure.
        """
        logger.debug("MySQLAnalyticsSQLExecutor.execute: sql_len=%d", len(sql))
        try:
            with self._engine.connect() as conn:
                result = conn.execute(text(sql), params or {})
                return [dict(row._mapping) for row in result.fetchall()]
        except MYSQL_EXECUTION_ERRORS as exc:
            # FIND-021: log full driver exception internally; sanitize the raised
            # message so MySQL host/port are not returned to callers.
            logger.exception("MySQLAnalyticsSQLExecutor.execute failed")
            raise RuntimeError("Analytics query execution failed") from exc

    def test_connection(self) -> None:
        """Verify connectivity by running ``SELECT 1``."""
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1 AS _ping"))
        except MYSQL_EXECUTION_ERRORS as exc:
            # FIND-021: sanitized message — no host or port details.
            logger.exception("MySQLAnalyticsSQLExecutor.test_connection failed")
            raise RuntimeError("Analytics datasource connection test failed") from exc

    def get_dialect(self) -> str:
        return "mysql"
