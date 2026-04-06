from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.analytics.mysql_executor import MySQLAnalyticsSQLExecutor


def _executor() -> MySQLAnalyticsSQLExecutor:
    with patch("app.adapters.analytics.mysql_executor.create_engine") as mock_create_engine:
        mock_create_engine.return_value = MagicMock()
        return MySQLAnalyticsSQLExecutor(
            host="mysql.example.com",
            port=3306,
            database="analytics",
            user="user",
            password="secret",
            ssl_ca="/tmp/ca.pem",
        )


def test_execute_wraps_expected_sqlalchemy_errors() -> None:
    executor = _executor()
    executor._engine = MagicMock()
    executor._engine.connect.side_effect = SQLAlchemyError("db down")

    with pytest.raises(RuntimeError, match="Analytics query execution failed"):
        executor.execute("SELECT 1")


def test_execute_surfaces_unexpected_errors() -> None:
    executor = _executor()
    executor._engine = MagicMock()
    executor._engine.connect.side_effect = AssertionError("unexpected mysql bug")

    with pytest.raises(AssertionError, match="unexpected mysql bug"):
        executor.execute("SELECT 1")


def test_test_connection_wraps_expected_sqlalchemy_errors() -> None:
    executor = _executor()
    executor._engine = MagicMock()
    executor._engine.connect.side_effect = SQLAlchemyError("ping down")

    with pytest.raises(RuntimeError, match="Analytics datasource connection test failed"):
        executor.test_connection()


def test_test_connection_surfaces_unexpected_errors() -> None:
    executor = _executor()
    executor._engine = MagicMock()
    executor._engine.connect.side_effect = AssertionError("unexpected mysql ping bug")

    with pytest.raises(AssertionError, match="unexpected mysql ping bug"):
        executor.test_connection()
