from __future__ import annotations

from app.ports.metadata_provider_abc import MetadataProvider
from app.ports.sql_executor_abc import SQLExecutor

_SUPPORTED = frozenset({"databricks", "snowflake", "mysql"})


class MetadataProviderFactory:
    """Creates MetadataProvider instances from a type string and a SQLExecutor.

    The executor is injected rather than constructed here — callers obtain
    executors from ``AnalyticsDatasourceRegistry`` and pass them in.
    """

    @staticmethod
    def create(datasource_type: str, executor: SQLExecutor) -> MetadataProvider:
        """Create a ``MetadataProvider`` wrapping *executor*.

        :param datasource_type: One of ``"databricks"``, ``"snowflake"``, ``"mysql"``.
        :param executor: Configured ``SQLExecutor`` instance.
        :returns: Concrete ``MetadataProvider``.
        :raises ValueError: if *datasource_type* is not supported.
        """
        t = (datasource_type or "").strip().lower()
        if t not in _SUPPORTED:
            raise ValueError(
                f"Unsupported MetadataProvider type: '{datasource_type}'. "
                f"Supported: {sorted(_SUPPORTED)}"
            )

        if t == "databricks":
            from app.adapters.analytics.databricks_metadata_provider import DatabricksMetadataProvider
            return DatabricksMetadataProvider(executor=executor)
        if t == "snowflake":
            from app.adapters.analytics.snowflake_metadata_provider import SnowflakeMetadataProvider
            return SnowflakeMetadataProvider(executor=executor)
        from app.adapters.analytics.mysql_metadata_provider import MySQLMetadataProvider
        return MySQLMetadataProvider(executor=executor)
