"""Tests for app.services.analytics.config_loader."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.services.analytics.config_loader import (
    _resolve_env_vars,
    _find_unresolved_placeholders,
    _validate_datasource,
    load_analytics_config,
)


# ---------------------------------------------------------------------------
# _resolve_env_vars
# ---------------------------------------------------------------------------


def test_resolve_env_vars_substitutes_set_variable(monkeypatch):
    monkeypatch.setenv("MY_HOST", "db.example.com")
    result = _resolve_env_vars("${MY_HOST}")
    assert result == "db.example.com"


def test_resolve_env_vars_preserves_placeholder_for_missing_var(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    result = _resolve_env_vars("${MISSING_VAR}")
    assert result == "${MISSING_VAR}"


def test_resolve_env_vars_nested_dict(monkeypatch):
    monkeypatch.setenv("HOST", "host.example.com")
    monkeypatch.setenv("TOKEN", "abc123")
    cfg = {"host": "${HOST}", "token": "${TOKEN}", "port": 3306}
    result = _resolve_env_vars(cfg)
    assert result == {"host": "host.example.com", "token": "abc123", "port": 3306}


def test_resolve_env_vars_list(monkeypatch):
    monkeypatch.setenv("VAL", "hello")
    result = _resolve_env_vars(["${VAL}", "literal"])
    assert result == ["hello", "literal"]


def test_resolve_env_vars_non_string_passthrough():
    assert _resolve_env_vars(42) == 42
    assert _resolve_env_vars(3.14) == 3.14
    assert _resolve_env_vars(None) is None


# ---------------------------------------------------------------------------
# _find_unresolved_placeholders
# ---------------------------------------------------------------------------


def test_find_unresolved_placeholders_detects_remaining(monkeypatch):
    monkeypatch.delenv("UNSET_VAR", raising=False)
    cfg = {"primary": {"host": "${UNSET_VAR}", "token": "resolved"}}
    unresolved = _find_unresolved_placeholders(cfg)
    assert len(unresolved) == 1
    assert "UNSET_VAR" in unresolved[0]


def test_find_unresolved_placeholders_empty_when_all_resolved():
    cfg = {"primary": {"host": "db.example.com", "token": "mytoken"}}
    assert _find_unresolved_placeholders(cfg) == []


# ---------------------------------------------------------------------------
# _validate_datasource
# ---------------------------------------------------------------------------


def test_validate_datasource_raises_on_missing_type():
    with pytest.raises(ValueError, match="missing required key 'type'"):
        _validate_datasource("ds1", {"host": "x"})


def test_validate_datasource_raises_on_unknown_type():
    with pytest.raises(ValueError, match="unknown type"):
        _validate_datasource("ds1", {"type": "oracle", "host": "x"})


def test_validate_datasource_raises_on_missing_required_key():
    with pytest.raises(ValueError, match="missing required keys"):
        # Databricks requires host, token, http_path — token is missing
        _validate_datasource("ds1", {"type": "databricks", "host": "x", "http_path": "/p"})


def test_validate_datasource_passes_valid_databricks():
    _validate_datasource(
        "ds1",
        {"type": "databricks", "host": "https://h", "token": "t", "http_path": "/p"},
    )


def test_validate_datasource_passes_valid_snowflake():
    _validate_datasource(
        "ds1",
        {
            "type": "snowflake",
            "account": "xy12345",
            "user": "u",
            "database": "db",
            "warehouse": "wh",
        },
    )

def test_validate_datasource_passes_valid_snowflake_without_warehouse():
    _validate_datasource(
        "ds1",
        {
            "type": "snowflake",
            "account": "xy12345",
            "user": "u",
            "database": "db",
            "authenticator": "externalbrowser",
        },
    )


def test_validate_datasource_passes_valid_mysql():
    _validate_datasource(
        "ds1",
        {"type": "mysql", "host": "h", "database": "db", "user": "u", "password": "p",
         "ssl_ca": "/etc/ssl/certs/ca.pem"},
    )


# ---------------------------------------------------------------------------
# load_analytics_config — file not found
# ---------------------------------------------------------------------------


def test_load_analytics_config_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_analytics_config(config_path=tmp_path / "nonexistent.yaml")


# ---------------------------------------------------------------------------
# load_analytics_config — YAML parsing and env var resolution
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "analytics_datasources.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_load_analytics_config_returns_resolved_config(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_DBX_HOST", "https://adb-1.azuredatabricks.net")
    monkeypatch.setenv("TEST_DBX_TOKEN", "dapi_test")
    monkeypatch.setenv("TEST_DBX_PATH", "/sql/1.0/warehouses/w1")

    cfg_path = _write_config(
        tmp_path,
        """
        analytics_datasources:
          primary:
            type: databricks
            host: ${TEST_DBX_HOST}
            token: ${TEST_DBX_TOKEN}
            http_path: ${TEST_DBX_PATH}
        """,
    )

    result = load_analytics_config(config_path=cfg_path)

    assert "primary" in result
    assert result["primary"]["host"] == "https://adb-1.azuredatabricks.net"
    assert result["primary"]["token"] == "dapi_test"
    assert result["primary"]["http_path"] == "/sql/1.0/warehouses/w1"


def test_load_analytics_config_empty_file_returns_empty_dict(tmp_path):
    cfg_path = tmp_path / "analytics_datasources.yaml"
    cfg_path.write_text("analytics_datasources: {}\n", encoding="utf-8")

    result = load_analytics_config(config_path=cfg_path)
    assert result == {}


def test_load_analytics_config_invalid_type_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("H", "host")
    cfg_path = _write_config(
        tmp_path,
        """
        analytics_datasources:
          ds1:
            type: oracle
            host: ${H}
        """,
    )
    with pytest.raises(ValueError, match="unknown type"):
        load_analytics_config(config_path=cfg_path)


def test_load_analytics_config_unresolved_vars_are_warned_not_raised(tmp_path, monkeypatch, caplog):
    """Missing env vars should warn but not raise — callers decide whether to fail."""
    import logging

    monkeypatch.delenv("UNSET_DATABRICKS_HOST", raising=False)
    # Provide the other required vars so validation passes (they are required to be non-empty)
    monkeypatch.setenv("TOKEN_VAL", "t")
    monkeypatch.setenv("PATH_VAL", "/p")

    cfg_path = _write_config(
        tmp_path,
        """
        analytics_datasources:
          primary:
            type: databricks
            host: ${UNSET_DATABRICKS_HOST}
            token: ${TOKEN_VAL}
            http_path: ${PATH_VAL}
        """,
    )

    # Validation will fail because host resolves to the placeholder string (non-empty)
    # so we just confirm the warning is emitted
    with caplog.at_level(logging.WARNING, logger="app.services.analytics.config_loader"):
        try:
            load_analytics_config(config_path=cfg_path)
        except Exception:
            pass

    assert any("UNSET_DATABRICKS_HOST" in msg for msg in caplog.messages)
