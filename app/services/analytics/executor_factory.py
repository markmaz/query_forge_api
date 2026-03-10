from __future__ import annotations

import logging
from typing import Any

from app.ports.sql_executor_abc import SQLExecutor

logger = logging.getLogger(__name__)

_SUPPORTED_TYPES = frozenset({"databricks", "snowflake", "mysql"})


class ExecutorFactory:
    """Factory that constructs ``SQLExecutor`` instances from a type string and a config dict.

    Supported types: ``databricks``, ``snowflake``, ``mysql``.

    Example usage::

        executor = ExecutorFactory.create(
            "databricks",
            {
                "type": "databricks",
                "host": "https://adb-xxx.azuredatabricks.net",
                "token": "dapi...",
                "http_path": "/sql/1.0/warehouses/abc",
            },
        )

    The ``type`` key in *config* is ignored — the positional *type* parameter takes precedence.
    Credentials must already be resolved (env var substitution is the caller's responsibility,
    e.g. ``config_loader.load_analytics_config``).
    """

    @staticmethod
    def create(type: str, config: dict[str, Any]) -> SQLExecutor:
        """Create a ``SQLExecutor`` from a type identifier and configuration mapping.

        :param type: Datasource type string.  One of ``"databricks"``, ``"snowflake"``,
            ``"mysql"``.
        :param config: Dict of constructor arguments for the chosen executor.  Keys vary
            per type; see the respective executor classes for details.
        :returns: Configured ``SQLExecutor`` instance.
        :raises ValueError: if *type* is not recognised.
        """
        normalised = (type or "").strip().lower()

        if normalised not in _SUPPORTED_TYPES:
            raise ValueError(
                f"ExecutorFactory: unsupported type '{type}'. "
                f"Supported types: {sorted(_SUPPORTED_TYPES)}"
            )

        logger.debug("ExecutorFactory.create: type=%s", normalised)

        if normalised == "databricks":
            return ExecutorFactory._create_databricks(config)
        if normalised == "snowflake":
            return ExecutorFactory._create_snowflake(config)
        # mysql
        return ExecutorFactory._create_mysql(config)

    # ------------------------------------------------------------------
    # Private per-type constructors
    # ------------------------------------------------------------------

    @staticmethod
    def _create_databricks(config: dict[str, Any]) -> SQLExecutor:
        from app.adapters.analytics.databricks_executor import DatabricksSQLExecutor

        return DatabricksSQLExecutor(
            host=config["host"],
            token=config.get("token"),
            http_path=config["http_path"],
            catalog=config.get("catalog"),
            schema=config.get("schema"),
            token_provider=config.get("token_provider"),
            platform=config.get("platform"),
        )

    @staticmethod
    def _create_snowflake(config: dict[str, Any]) -> SQLExecutor:
        from app.adapters.analytics.snowflake_executor import SnowflakeSQLExecutor

        return SnowflakeSQLExecutor(
            account=config["account"],
            user=config["user"],
            database=config["database"],
            warehouse=config.get("warehouse"),
            schema=config.get("schema"),
            authenticator=config.get("authenticator"),
            role=config.get("role"),
            password=config.get("password"),
            private_key_path=config.get("private_key_path"),
            private_key_passphrase=config.get("private_key_passphrase"),
        )

    @staticmethod
    def _create_mysql(config: dict[str, Any]) -> SQLExecutor:
        from app.adapters.analytics.mysql_executor import MySQLAnalyticsSQLExecutor

        return MySQLAnalyticsSQLExecutor(
            host=config["host"],
            port=int(config.get("port", 3306)),
            database=config["database"],
            user=config["user"],
            password=config["password"],
            # FIND-022: ssl_ca is required; MySQLAnalyticsSQLExecutor raises
            # ValueError at construction time if it is absent.
            ssl_ca=config.get("ssl_ca"),
        )
