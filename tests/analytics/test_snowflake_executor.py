"""Tests for app.adapters.analytics.snowflake_executor.SnowflakeSQLExecutor.

All tests mock ``snowflake.connector`` — no real Snowflake connection is made.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from app.adapters.analytics.snowflake_executor import SnowflakeSQLExecutor


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_missing_account_raises():
    with pytest.raises(ValueError, match="account"):
        SnowflakeSQLExecutor(
            account="", user="u", database="db", warehouse="wh", password="p"
        )


def test_missing_user_raises():
    with pytest.raises(ValueError, match="user"):
        SnowflakeSQLExecutor(
            account="acc", user="", database="db", warehouse="wh", password="p"
        )


def test_missing_database_raises():
    with pytest.raises(ValueError, match="database"):
        SnowflakeSQLExecutor(
            account="acc", user="u", database="", warehouse="wh", password="p"
        )


def test_missing_warehouse_raises():
    with pytest.raises(ValueError, match="warehouse"):
        SnowflakeSQLExecutor(
            account="acc", user="u", database="db", warehouse="", password="p"
        )


def test_no_auth_method_raises():
    with pytest.raises(ValueError, match="password.*private_key_path"):
        SnowflakeSQLExecutor(account="acc", user="u", database="db", warehouse="wh")


# ---------------------------------------------------------------------------
# get_dialect
# ---------------------------------------------------------------------------


def test_get_dialect():
    exc = SnowflakeSQLExecutor(
        account="acc", user="u", database="db", warehouse="wh", password="p"
    )
    assert exc.get_dialect() == "snowflake"


# ---------------------------------------------------------------------------
# execute — happy path
# ---------------------------------------------------------------------------


def _make_mock_cursor(rows, columns):
    cursor = MagicMock()
    cursor.description = [(col, None, None, None, None, None, None) for col in columns]
    cursor.fetchall.return_value = rows
    return cursor


def _make_mock_conn(cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


def test_execute_returns_list_of_dicts():
    columns = ["id", "name"]
    rows = [(1, "Alice"), (2, "Bob")]
    cursor = _make_mock_cursor(rows, columns)
    conn = _make_mock_conn(cursor)

    with patch("snowflake.connector.connect", return_value=conn):
        executor = SnowflakeSQLExecutor(
            account="acc", user="u", database="db", warehouse="wh", password="p"
        )
        result = executor.execute("SELECT id, name FROM users")

    assert result == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]


def test_execute_with_params_passes_params_to_cursor():
    columns = ["id"]
    rows = [(42,)]
    cursor = _make_mock_cursor(rows, columns)
    conn = _make_mock_conn(cursor)

    params = {"user_id": 42}

    with patch("snowflake.connector.connect", return_value=conn):
        executor = SnowflakeSQLExecutor(
            account="acc", user="u", database="db", warehouse="wh", password="p"
        )
        executor.execute("SELECT id FROM users WHERE id = %(user_id)s", params=params)

    cursor.execute.assert_called_once_with(
        "SELECT id FROM users WHERE id = %(user_id)s", params
    )


def test_execute_no_params_does_not_pass_params_to_cursor():
    columns = ["val"]
    rows = [(1,)]
    cursor = _make_mock_cursor(rows, columns)
    conn = _make_mock_conn(cursor)

    with patch("snowflake.connector.connect", return_value=conn):
        executor = SnowflakeSQLExecutor(
            account="acc", user="u", database="db", warehouse="wh", password="p"
        )
        executor.execute("SELECT 1 AS val")

    cursor.execute.assert_called_once_with("SELECT 1 AS val")


# ---------------------------------------------------------------------------
# execute — connection is always closed
# ---------------------------------------------------------------------------


def test_execute_closes_cursor_and_connection_on_success():
    cursor = _make_mock_cursor([], [])
    conn = _make_mock_conn(cursor)

    with patch("snowflake.connector.connect", return_value=conn):
        executor = SnowflakeSQLExecutor(
            account="acc", user="u", database="db", warehouse="wh", password="p"
        )
        executor.execute("SELECT 1")

    cursor.close.assert_called_once()
    conn.close.assert_called_once()


def test_execute_closes_connection_on_failure():
    conn = MagicMock()
    cursor = MagicMock()
    cursor.description = None
    cursor.execute.side_effect = Exception("network error")
    conn.cursor.return_value = cursor

    with patch("snowflake.connector.connect", return_value=conn):
        executor = SnowflakeSQLExecutor(
            account="acc", user="u", database="db", warehouse="wh", password="p"
        )
        with pytest.raises(RuntimeError, match="Snowflake execute failed"):
            executor.execute("SELECT 1")

    conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


def test_test_connection_executes_version_query():
    columns = ["_ping"]
    rows = [("5.0.0",)]
    cursor = _make_mock_cursor(rows, columns)
    conn = _make_mock_conn(cursor)

    with patch("snowflake.connector.connect", return_value=conn):
        executor = SnowflakeSQLExecutor(
            account="acc", user="u", database="db", warehouse="wh", password="p"
        )
        executor.test_connection()  # Should not raise

    cursor.execute.assert_called_once_with("SELECT CURRENT_VERSION() AS _ping")


def test_test_connection_raises_on_failure():
    conn = MagicMock()
    cursor = MagicMock()
    cursor.execute.side_effect = Exception("auth failed")
    conn.cursor.return_value = cursor

    with patch("snowflake.connector.connect", return_value=conn):
        executor = SnowflakeSQLExecutor(
            account="acc", user="u", database="db", warehouse="wh", password="p"
        )
        with pytest.raises(RuntimeError, match="connection test failed"):
            executor.test_connection()


# ---------------------------------------------------------------------------
# Keypair authentication path
# ---------------------------------------------------------------------------


def test_execute_uses_private_key_when_provided(tmp_path):
    """Verify that private_key is passed to snowflake.connector.connect."""
    # Create a minimal fake PEM key (load will be mocked)
    fake_key_path = tmp_path / "rsa_key.pem"
    fake_key_path.write_text("fake pem content", encoding="utf-8")

    columns = ["val"]
    rows = [(1,)]
    cursor = _make_mock_cursor(rows, columns)
    conn = _make_mock_conn(cursor)

    fake_der_bytes = b"fake_der_bytes"

    with patch(
        "app.adapters.analytics.snowflake_executor._load_private_key",
        return_value=fake_der_bytes,
    ) as mock_load_key, patch("snowflake.connector.connect", return_value=conn) as mock_connect:
        executor = SnowflakeSQLExecutor(
            account="acc",
            user="u",
            database="db",
            warehouse="wh",
            private_key_path=str(fake_key_path),
            private_key_passphrase="passphrase",
        )
        executor.execute("SELECT 1 AS val")

    mock_load_key.assert_called_once_with(str(fake_key_path), "passphrase")
    connect_kwargs = mock_connect.call_args[1]
    assert connect_kwargs["private_key"] == fake_der_bytes
    assert "password" not in connect_kwargs
