"""Tests for app.adapters.analytics.snowflake_executor.SnowflakeSQLExecutor.

All tests mock ``snowflake.connector`` — no real Snowflake connection is made.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.adapters.analytics.snowflake_executor import (
    SnowflakeSQLExecutor,
    _load_private_key_pem,
    _normalize_account_identifier,
)


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


def test_missing_warehouse_is_allowed():
    SnowflakeSQLExecutor(
        account="acc", user="u", database="db", warehouse="", password="p"
    )


def test_no_auth_method_raises():
    with pytest.raises(ValueError, match="one auth method is required"):
        SnowflakeSQLExecutor(account="acc", user="u", database="db", warehouse="wh")


# ---------------------------------------------------------------------------
# get_dialect
# ---------------------------------------------------------------------------


def test_get_dialect():
    exc = SnowflakeSQLExecutor(
        account="acc", user="u", database="db", warehouse="wh", password="p"
    )
    assert exc.get_dialect() == "snowflake"


def test_normalize_account_identifier_accepts_url_and_uppercase():
    assert (
        _normalize_account_identifier("https://MBPTPRZ-EQC30653.snowflakecomputing.com")
        == "mbptprz-eqc30653"
    )


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
        with pytest.raises(RuntimeError, match="Analytics query execution failed"):
            executor.execute("SELECT 1")

    conn.close.assert_called_once()


def test_execute_returns_auth_hint_for_saml_account_error():
    class _Exc(Exception):
        errno = 390190

    conn = MagicMock()
    cursor = MagicMock()
    cursor.description = None
    cursor.execute.side_effect = _Exc("bad saml account parameter")
    conn.cursor.return_value = cursor

    with patch("snowflake.connector.connect", return_value=conn):
        executor = SnowflakeSQLExecutor(
            account="acc", user="u", database="db", warehouse="wh", password="p"
        )
        with pytest.raises(RuntimeError, match="account identifier and authenticator settings"):
            executor.execute("SELECT 1")


def test_execute_returns_auth_hint_for_invalid_jwt():
    class _Exc(Exception):
        errno = 250001

    conn = MagicMock()
    cursor = MagicMock()
    cursor.description = None
    cursor.execute.side_effect = _Exc("JWT token is invalid")
    conn.cursor.return_value = cursor

    with patch("snowflake.connector.connect", return_value=conn):
        executor = SnowflakeSQLExecutor(
            account="acc", user="u", database="db", warehouse="wh", password="p"
        )
        with pytest.raises(RuntimeError, match="JWT token is invalid"):
            executor.execute("SELECT 1")


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


def test_execute_uses_private_key_pem_when_provided():
    columns = ["val"]
    rows = [(1,)]
    cursor = _make_mock_cursor(rows, columns)
    conn = _make_mock_conn(cursor)

    fake_der_bytes = b"fake_der_bytes"
    pem = "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----"

    with patch(
        "app.adapters.analytics.snowflake_executor._load_private_key_pem",
        return_value=fake_der_bytes,
    ) as mock_load_key, patch("snowflake.connector.connect", return_value=conn) as mock_connect:
        executor = SnowflakeSQLExecutor(
            account="acc",
            user="u",
            database="db",
            warehouse="wh",
            private_key_pem=pem,
            private_key_passphrase="passphrase",
        )
        executor.execute("SELECT 1 AS val")

    mock_load_key.assert_called_once_with(pem, "passphrase")
    connect_kwargs = mock_connect.call_args[1]
    assert connect_kwargs["private_key"] == fake_der_bytes
    assert "password" not in connect_kwargs


def test_execute_uses_externalbrowser_auth_without_password():
    columns = ["val"]
    rows = [(1,)]
    cursor = _make_mock_cursor(rows, columns)
    conn = _make_mock_conn(cursor)

    with patch("snowflake.connector.connect", return_value=conn) as mock_connect:
        executor = SnowflakeSQLExecutor(
            account="acc",
            user="u",
            database="db",
            warehouse="",
            schema="MEDICAL_SALES",
            authenticator="externalbrowser",
            role="ACCOUNTADMIN",
        )
        executor.execute("SELECT 1 AS val")

    connect_kwargs = mock_connect.call_args[1]
    assert connect_kwargs["authenticator"] == "externalbrowser"
    assert connect_kwargs["schema"] == "MEDICAL_SALES"
    assert connect_kwargs["role"] == "ACCOUNTADMIN"
    assert "warehouse" not in connect_kwargs
    assert "password" not in connect_kwargs


def test_load_private_key_reads_pem_text(monkeypatch):
    fake_private_key = MagicMock()
    fake_private_key.private_bytes.return_value = b"der-bytes"
    load_mock = MagicMock(return_value=fake_private_key)

    monkeypatch.setattr(
        "cryptography.hazmat.primitives.serialization.load_pem_private_key",
        load_mock,
    )

    result = _load_private_key_pem(
        "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
        "passphrase",
    )

    assert result == b"der-bytes"
    call_args = load_mock.call_args
    assert call_args.args[0].startswith(b"-----BEGIN PRIVATE KEY-----")
    assert call_args.kwargs["password"] == b"passphrase"
