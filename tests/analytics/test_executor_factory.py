"""Tests for app.services.analytics.executor_factory.ExecutorFactory."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.analytics.executor_factory import ExecutorFactory


# ---------------------------------------------------------------------------
# Unknown type
# ---------------------------------------------------------------------------


def test_create_unknown_type_raises_value_error():
    with pytest.raises(ValueError, match="unsupported type"):
        ExecutorFactory.create("oracle", {"type": "oracle"})


def test_create_empty_type_raises_value_error():
    with pytest.raises(ValueError, match="unsupported type"):
        ExecutorFactory.create("", {})


# ---------------------------------------------------------------------------
# Databricks
# ---------------------------------------------------------------------------


def test_create_databricks_returns_executor():
    cfg = {
        "type": "databricks",
        "host": "https://adb-1.azuredatabricks.net",
        "token": "dapi_test",
        "http_path": "/sql/1.0/warehouses/w1",
    }

    with patch(
        "app.services.analytics.executor_factory.ExecutorFactory._create_databricks"
    ) as mock_create:
        mock_executor = MagicMock()
        mock_executor.get_dialect.return_value = "databricks"
        mock_create.return_value = mock_executor

        result = ExecutorFactory.create("databricks", cfg)

    mock_create.assert_called_once_with(cfg)
    assert result is mock_executor


def test_create_databricks_missing_host_raises():
    cfg = {"type": "databricks", "token": "t", "http_path": "/p"}
    with pytest.raises((ValueError, KeyError)):
        ExecutorFactory.create("databricks", cfg)


def test_create_databricks_missing_token_raises():
    cfg = {"type": "databricks", "host": "https://h", "http_path": "/p"}
    with pytest.raises((ValueError, KeyError)):
        ExecutorFactory.create("databricks", cfg)


def test_create_databricks_oauth_builds_token_provider():
    cfg = {
        "type": "databricks",
        "host": "https://adb-1.azuredatabricks.net",
        "http_path": "/sql/1.0/warehouses/w1",
        "auth_method": "oauth_client_credentials",
        "client_id": "client-1",
        "client_secret": "secret-1",
    }

    with patch("app.adapters.databricks_workspace_token_provider.create_databricks_oauth_provider") as mock_provider:
        with patch("app.adapters.analytics.databricks_executor.DatabricksSQLExecutor") as mock_cls:
            provider = MagicMock()
            mock_provider.return_value = provider
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance

            result = ExecutorFactory.create("databricks", cfg)

    assert result is mock_instance
    mock_provider.assert_called_once()
    mock_cls.assert_called_once_with(
        host="https://adb-1.azuredatabricks.net",
        token=None,
        http_path="/sql/1.0/warehouses/w1",
        catalog=None,
        schema=None,
        token_provider=provider,
        platform=None,
    )


# ---------------------------------------------------------------------------
# Snowflake
# ---------------------------------------------------------------------------


def test_create_snowflake_returns_executor():
    cfg = {
        "type": "snowflake",
        "account": "xy12345.us-east-1",
        "user": "svc_user",
        "database": "analytics",
        "warehouse": "compute_wh",
        "password": "s3cr3t",
    }

    with patch(
        "app.services.analytics.executor_factory.ExecutorFactory._create_snowflake"
    ) as mock_create:
        mock_executor = MagicMock()
        mock_executor.get_dialect.return_value = "snowflake"
        mock_create.return_value = mock_executor

        result = ExecutorFactory.create("snowflake", cfg)

    mock_create.assert_called_once_with(cfg)
    assert result is mock_executor


def test_create_snowflake_passes_optional_authenticator_and_schema():
    cfg = {
        "type": "snowflake",
        "account": "xy12345.us-east-1",
        "user": "svc_user",
        "database": "analytics",
        "authenticator": "externalbrowser",
        "schema": "MEDICAL_SALES",
        "role": "ACCOUNTADMIN",
    }

    with patch("app.adapters.analytics.snowflake_executor.SnowflakeSQLExecutor") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.get_dialect.return_value = "snowflake"
        mock_cls.return_value = mock_instance

        result = ExecutorFactory.create("snowflake", cfg)

    assert result is mock_instance
    mock_cls.assert_called_once_with(
        account="xy12345.us-east-1",
        user="svc_user",
        database="analytics",
        warehouse=None,
        schema="MEDICAL_SALES",
        authenticator="externalbrowser",
        role="ACCOUNTADMIN",
        password=None,
        private_key_pem=None,
        private_key_path=None,
        private_key_passphrase=None,
    )


# ---------------------------------------------------------------------------
# MySQL
# ---------------------------------------------------------------------------


def test_create_mysql_returns_executor():
    cfg = {
        "type": "mysql",
        "host": "mysql.example.com",
        "port": 3306,
        "database": "reporting",
        "user": "reader",
        "password": "readpass",
    }

    with patch(
        "app.services.analytics.executor_factory.ExecutorFactory._create_mysql"
    ) as mock_create:
        mock_executor = MagicMock()
        mock_executor.get_dialect.return_value = "mysql"
        mock_create.return_value = mock_executor

        result = ExecutorFactory.create("mysql", cfg)

    mock_create.assert_called_once_with(cfg)
    assert result is mock_executor


def test_create_mysql_default_port():
    """Port should default to 3306 when omitted from config."""
    cfg = {
        "type": "mysql",
        "host": "mysql.example.com",
        "database": "reporting",
        "user": "reader",
        "password": "pass",
        "ssl_ca": "/etc/ssl/certs/ca.pem",
    }

    with patch(
        "app.adapters.analytics.mysql_executor.create_engine"
    ) as mock_engine:
        mock_engine.return_value = MagicMock()
        executor = ExecutorFactory.create("mysql", cfg)
        assert executor.get_dialect() == "mysql"
        # Verify the connection URI used port 3306
        call_args = mock_engine.call_args[0][0]
        assert ":3306/" in call_args


# ---------------------------------------------------------------------------
# Case insensitivity
# ---------------------------------------------------------------------------


def test_create_type_is_case_insensitive():
    cfg = {
        "type": "DATABRICKS",
        "host": "https://adb-1.azuredatabricks.net",
        "token": "t",
        "http_path": "/p",
    }
    with patch(
        "app.services.analytics.executor_factory.ExecutorFactory._create_databricks"
    ) as mock_create:
        mock_create.return_value = MagicMock()
        ExecutorFactory.create("DATABRICKS", cfg)
        mock_create.assert_called_once()
