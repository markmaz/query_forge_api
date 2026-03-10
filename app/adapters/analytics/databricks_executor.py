from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlparse

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

    :param host: Databricks workspace host URL or hostname,
        e.g. ``https://adb-xxx.azuredatabricks.net`` or ``adb-xxx.azuredatabricks.net``.
    :param token: Optional Databricks personal access token or service‑principal OAuth token.
    :param token_provider: Optional token provider object exposing ``get_token()``,
        ``token`` property, or ``__call__``.  If provided, it is used in preference to
        ``token`` so refreshed OAuth tokens can be consumed dynamically.
    :param http_path: SQL warehouse HTTP path (e.g. ``/sql/1.0/warehouses/<id>``) or
        just the bare warehouse ID.  The warehouse ID is extracted automatically from
        either form and used in the Statements API payload.
    :param catalog: Optional default Unity Catalog catalog name.
    :param schema: Optional default schema name.
    :param platform: Cloud platform — ``"azure"`` or ``"aws"``.  Used for diagnostics
        and future platform-specific auth handling.  Auto-detected from *host* when omitted.
    """

    def __init__(
        self,
        host: str,
        token: Optional[str],
        http_path: str,
        catalog: Optional[str] = None,
        schema: Optional[str] = None,
        token_provider: Optional[object] = None,
        platform: Optional[str] = None,
    ) -> None:
        raw_host = (host or "").strip()
        if not raw_host:
            raise ValueError("DatabricksSQLExecutor: 'host' is required")
        if not http_path:
            raise ValueError("DatabricksSQLExecutor: 'http_path' is required")

        # FIND-022: enforce HTTPS transport.  Scheme-less hosts are normalized to
        # HTTPS, but explicit non-HTTPS URLs are rejected.
        self._host = self._normalize_https_host(raw_host)
        self._http_path = http_path
        self._catalog = catalog
        self._schema = schema

        # The Statements API `warehouse_id` field expects just the bare ID
        # (e.g. "abc123"), NOT the full JDBC HTTP path ("/sql/1.0/warehouses/abc123").
        # Extract the trailing segment so both forms are accepted transparently.
        self._warehouse_id = self._extract_warehouse_id(http_path)

        # Auto-detect platform from host if not supplied.
        self._platform = self._resolve_platform(platform, self._host)

        provider = token_provider
        if provider is None:
            raw_token = (token or "").strip()
            if not raw_token:
                raise ValueError(
                    "DatabricksSQLExecutor: either 'token' or 'token_provider' is required"
                )
            if "${" in raw_token or "}" in raw_token:
                raise ValueError(
                    "DatabricksSQLExecutor: 'token' contains an unresolved environment placeholder"
                )
            provider = _StaticTokenPort(raw_token)
        self._token_provider = provider

        self._delegate = DatabricksForgeQueryPort(
            base_url=self._host,
            token_provider=provider,
            default_warehouse_id=self._warehouse_id,
            default_catalog=catalog,
            default_schema=schema,
        )

        logger.debug(
            "DatabricksSQLExecutor initialised: host=%s http_path=%s warehouse_id=%s catalog=%s schema=%s platform=%s",
            self._host,
            self._http_path,
            self._warehouse_id,
            self._catalog,
            self._schema,
            self._platform,
        )

    @staticmethod
    def _extract_warehouse_id(http_path: str) -> str:
        """Return the bare warehouse ID from an HTTP path or a plain ID.

        Examples::

            "/sql/1.0/warehouses/abc123"  →  "abc123"
            "abc123"                       →  "abc123"
        """
        return (http_path or "").strip("/").split("/")[-1]

    @staticmethod
    def _resolve_platform(platform: Optional[str], host: str) -> str:
        """Return 'azure' or 'aws', auto-detecting from *host* when *platform* is not set.

        Unresolved env-var placeholders (``${...}``) are treated as absent so that
        omitting ``DATABRICKS_PLATFORM`` from the environment falls back gracefully to
        auto-detection rather than storing a garbage value.
        """
        if platform and "${" not in platform:
            return platform.strip().lower()
        if "azuredatabricks.net" in host.lower():
            return "azure"
        return "aws"

    @staticmethod
    def _normalize_https_host(host: str) -> str:
        # Leave unresolved env placeholders as hard failures so startup errors are clear.
        if "${" in host or "}" in host:
            raise ValueError(
                "DatabricksSQLExecutor: 'host' contains an unresolved environment placeholder"
            )

        candidate = host if "://" in host else f"https://{host}"
        parsed = urlparse(candidate)
        if parsed.scheme.lower() != "https":
            raise ValueError(
                "DatabricksSQLExecutor: 'host' must begin with 'https://'"
            )
        if not parsed.netloc:
            raise ValueError("DatabricksSQLExecutor: 'host' must be a valid HTTPS URL")
        if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
            raise ValueError(
                "DatabricksSQLExecutor: 'host' must contain only scheme and hostname"
            )

        return f"https://{parsed.netloc}"

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

    def get_platform(self) -> str:
        """Return the cloud platform: ``'azure'`` or ``'aws'``."""
        return self._platform

    def get_bearer_token(self) -> str:
        """Return the active Databricks bearer token from the configured provider."""
        token = self._token_from_provider(self._token_provider)
        if not token:
            raise RuntimeError("Databricks token provider returned no token")
        return token

    @staticmethod
    def _token_from_provider(provider: Any) -> str | None:
        getter = getattr(provider, "get_token", None)
        if callable(getter):
            value = getter()
            if value:
                return str(value)

        fetcher = getattr(provider, "fetch_forge_token", None)
        if callable(fetcher):
            value = fetcher()
            if value:
                return str(value)

        token = getattr(provider, "token", None)
        if token:
            return str(token)

        if callable(provider):
            value = provider()
            if value:
                return str(value)

        return None
