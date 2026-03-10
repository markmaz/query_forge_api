from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.analytics.metadata_provider_factory import MetadataProviderFactory
from app.ports.sql_executor_abc import SQLExecutor
from app.adapters.analytics.databricks_metadata_provider import DatabricksMetadataProvider
from app.adapters.analytics.snowflake_metadata_provider import SnowflakeMetadataProvider
from app.adapters.analytics.mysql_metadata_provider import MySQLMetadataProvider


def _stub(dialect: str) -> SQLExecutor:
    ex = MagicMock(spec=SQLExecutor)
    ex.get_dialect.return_value = dialect
    return ex


def test_create_databricks():
    provider = MetadataProviderFactory.create("databricks", _stub("databricks"))
    assert isinstance(provider, DatabricksMetadataProvider)


def test_create_snowflake():
    provider = MetadataProviderFactory.create("snowflake", _stub("snowflake"))
    assert isinstance(provider, SnowflakeMetadataProvider)


def test_create_mysql():
    provider = MetadataProviderFactory.create("mysql", _stub("mysql"))
    assert isinstance(provider, MySQLMetadataProvider)


def test_create_case_insensitive():
    provider = MetadataProviderFactory.create("DATABRICKS", _stub("databricks"))
    assert isinstance(provider, DatabricksMetadataProvider)


def test_create_unknown_type_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        MetadataProviderFactory.create("oracle", _stub("oracle"))
