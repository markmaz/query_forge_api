"""Tests for app.adapters.analytics.databricks_executor.DatabricksSQLExecutor."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.adapters.analytics.databricks_executor import DatabricksSQLExecutor


def test_missing_host_raises():
    with pytest.raises(ValueError, match="host.*required"):
        DatabricksSQLExecutor(host="", token="t", http_path="/sql/1.0/warehouses/w1")


def test_missing_token_raises():
    with pytest.raises(ValueError, match="token.*token_provider.*required"):
        DatabricksSQLExecutor(
            host="https://adb-1.azuredatabricks.net",
            token="",
            http_path="/sql/1.0/warehouses/w1",
        )


def test_missing_http_path_raises():
    with pytest.raises(ValueError, match="http_path.*required"):
        DatabricksSQLExecutor(
            host="https://adb-1.azuredatabricks.net",
            token="t",
            http_path="",
        )


def test_host_without_scheme_is_normalized_to_https():
    with patch(
        "app.adapters.analytics.databricks_executor.DatabricksForgeQueryPort"
    ) as mock_delegate:
        DatabricksSQLExecutor(
            host="adb-1.azuredatabricks.net",
            token="t",
            http_path="/sql/1.0/warehouses/w1",
        )

    assert mock_delegate.call_args.kwargs["base_url"] == "https://adb-1.azuredatabricks.net"


def test_explicit_http_host_is_rejected():
    with pytest.raises(ValueError, match="must begin with 'https://'"):
        DatabricksSQLExecutor(
            host="http://adb-1.azuredatabricks.net",
            token="t",
            http_path="/sql/1.0/warehouses/w1",
        )


def test_unresolved_placeholder_host_is_rejected():
    with pytest.raises(ValueError, match="unresolved environment placeholder"):
        DatabricksSQLExecutor(
            host="${DATABRICKS_HOST}",
            token="t",
            http_path="/sql/1.0/warehouses/w1",
        )


def test_unresolved_placeholder_token_is_rejected_without_provider():
    with pytest.raises(ValueError, match="token.*unresolved environment placeholder"):
        DatabricksSQLExecutor(
            host="https://adb-1.azuredatabricks.net",
            token="${DATABRICKS_TOKEN}",
            http_path="/sql/1.0/warehouses/w1",
        )


def test_token_provider_is_used_when_token_missing():
    provider = object()
    with patch(
        "app.adapters.analytics.databricks_executor.DatabricksForgeQueryPort"
    ) as mock_delegate:
        DatabricksSQLExecutor(
            host="https://adb-1.azuredatabricks.net",
            token=None,
            http_path="/sql/1.0/warehouses/w1",
            token_provider=provider,
        )

    assert mock_delegate.call_args.kwargs["token_provider"] is provider


def test_host_with_path_is_rejected():
    with pytest.raises(ValueError, match="only scheme and hostname"):
        DatabricksSQLExecutor(
            host="https://adb-1.azuredatabricks.net/some/path",
            token="t",
            http_path="/sql/1.0/warehouses/w1",
        )


def test_get_dialect():
    with patch("app.adapters.analytics.databricks_executor.DatabricksForgeQueryPort"):
        executor = DatabricksSQLExecutor(
            host="https://adb-1.azuredatabricks.net",
            token="t",
            http_path="/sql/1.0/warehouses/w1",
        )

    assert executor.get_dialect() == "databricks"


def test_get_bearer_token_returns_static_token():
    with patch("app.adapters.analytics.databricks_executor.DatabricksForgeQueryPort"):
        executor = DatabricksSQLExecutor(
            host="https://adb-1.azuredatabricks.net",
            token="token-123",
            http_path="/sql/1.0/warehouses/w1",
        )

    assert executor.get_bearer_token() == "token-123"


def test_execute_wraps_expected_delegate_errors():
    with patch("app.adapters.analytics.databricks_executor.DatabricksForgeQueryPort") as mock_delegate:
        mock_delegate.return_value.execute_query_mappings.side_effect = RuntimeError("driver failed")
        executor = DatabricksSQLExecutor(
            host="https://adb-1.azuredatabricks.net",
            token="t",
            http_path="/sql/1.0/warehouses/w1",
        )

        with pytest.raises(RuntimeError, match="Analytics query execution failed"):
            executor.execute("SELECT 1")


def test_execute_surfaces_unexpected_delegate_errors():
    with patch("app.adapters.analytics.databricks_executor.DatabricksForgeQueryPort") as mock_delegate:
        mock_delegate.return_value.execute_query_mappings.side_effect = AssertionError("unexpected delegate bug")
        executor = DatabricksSQLExecutor(
            host="https://adb-1.azuredatabricks.net",
            token="t",
            http_path="/sql/1.0/warehouses/w1",
        )

        with pytest.raises(AssertionError, match="unexpected delegate bug"):
            executor.execute("SELECT 1")


def test_test_connection_wraps_expected_delegate_errors():
    with patch("app.adapters.analytics.databricks_executor.DatabricksForgeQueryPort") as mock_delegate:
        mock_delegate.return_value.execute_query_mappings.side_effect = RuntimeError("ping failed")
        executor = DatabricksSQLExecutor(
            host="https://adb-1.azuredatabricks.net",
            token="t",
            http_path="/sql/1.0/warehouses/w1",
        )

        with pytest.raises(RuntimeError, match="Analytics datasource connection test failed"):
            executor.test_connection()


def test_test_connection_surfaces_unexpected_delegate_errors():
    with patch("app.adapters.analytics.databricks_executor.DatabricksForgeQueryPort") as mock_delegate:
        mock_delegate.return_value.execute_query_mappings.side_effect = AssertionError("unexpected ping bug")
        executor = DatabricksSQLExecutor(
            host="https://adb-1.azuredatabricks.net",
            token="t",
            http_path="/sql/1.0/warehouses/w1",
        )

        with pytest.raises(AssertionError, match="unexpected ping bug"):
            executor.test_connection()
