from __future__ import annotations

import logging
from typing import Optional

from app.adapters.databricks_sql_executor import DatabricksForgeQueryPort
from app.ports.sql_executor_abc import SQLExecutor

logger = logging.getLogger(__name__)


class _StaticTokenPort:
    """Minimal token provider that returns a fixed token string."""

    def __init__(self, token: str) -> None:
        self._token = token

    def get_token(self) -> str:
        return self._token


class DatabricksSQLExecutor(SQLExecutor):
    """Analytics executor backed by ``DatabricksForgeQueryPort``.

    All configuration is injected via the constructor — no global config is read.
    The existing ``DatabricksForgeQueryPort`` is unchanged; this class is a thin
    wrapper that satisfies the ``SQLExecutor`` interface.

    :param host: Databricks workspace host URL, e.g. ``https://adb-xxx.azuredatabricks.net``.
    :param token: Databricks personal access token or service‑principal OAuth token.
    :param http_path: SQL warehouse HTTP path, e.g. ``/sql/1.0/warehouses/<id>``.
    :param catalog: Optional default Unity Catalog catalog name.
    :param schema: Optional default schema name.
    """

    def __init__(
        self,
        host: str,
        token: str,
        http_path: str,
        catalog: Optional[str] = None,
        schema: Optional[str] = None,
    ) -> None:
        if not host:
            raise ValueError("DatabricksSQLExecutor: 'host' is required")
        if not token:
            raise ValueError("DatabricksSQLExecutor: 'token' is required")
        if not http_path:
            raise ValueError("DatabricksSQLExecutor: 'http_path' is required")

        # FIND-022: enforce HTTPS transport — reject any non-HTTPS host URL at
        # construction time so a misconfigured env var cannot silently downgrade to
        # plain HTTP and expose Databricks PATs in transit.
        if not host.lower().startswith("https://"):
            raise ValueError(
                "DatabricksSQLExecutor: 'host' must begin with 'https://'"
            )

        self._host = host.rstrip("/")
        self._http_path = http_path
        self._catalog = catalog
        self._schema = schema

        token_provider = _StaticTokenPort(token)
        self._delegate = DatabricksForgeQueryPort(
            base_url=self._host,
            token_provider=token_provider,
            default_warehouse_id=http_path,
            default_catalog=catalog,
            default_schema=schema,
        )

        logger.debug(
            "DatabricksSQLExecutor initialised: host=%s http_path=%s catalog=%s schema=%s",
            self._host,
            self._http_path,
            self._catalog,
            self._schema,
        )

    # ------------------------------------------------------------------
    # SQLExecutor interface
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: Optional[dict] = None) -> list[dict]:
        """Execute *sql* via the Databricks Statements API.

        Delegates to ``DatabricksForgeQueryPort.execute_query_mappings``.

        :param sql: SQL statement to execute.
        :param params: Optional named parameters.
        :returns: List of row dicts.
        :raises RuntimeError: on Databricks execution failure.
        """
        logger.debug("DatabricksSQLExecutor.execute: sql_len=%d", len(sql))
        try:
            return self._delegate.execute_query_mappings(sql, params)
        except Exception as exc:
            # FIND-021: log the original driver exception internally but do NOT
            # include it in the raised message — driver exceptions often contain
            # the workspace hostname or HTTP path.
            logger.exception("DatabricksSQLExecutor.execute failed")
            raise RuntimeError("Analytics query execution failed") from exc

    def test_connection(self) -> None:
        """Verify connectivity by running a lightweight ``SELECT 1``."""
        try:
            self._delegate.execute_query_mappings("SELECT 1 AS _ping")
        except Exception as exc:
            # FIND-021: sanitized message — no hostname or connection details.
            logger.exception("DatabricksSQLExecutor.test_connection failed")
            raise RuntimeError("Analytics datasource connection test failed") from exc

    def get_dialect(self) -> str:
        return "databricks"
