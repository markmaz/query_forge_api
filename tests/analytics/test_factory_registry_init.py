"""Tests for analytics registry initialization in app.factory."""
from __future__ import annotations

import logging

from flask import Flask

from app.factory import (
    _databricks_oauth_configured,
    _needs_databricks_token_manager,
    _register_analytics_registry,
    _sigma_oauth_configured,
)


class _DummyExecutor:
    def __init__(self, dialect: str) -> None:
        self._dialect = dialect

    def get_dialect(self) -> str:
        return self._dialect


def test_needs_databricks_token_manager_false_when_no_databricks():
    cfg = {"primary": {"type": "snowflake", "account": "a", "user": "u", "database": "d"}}
    assert _needs_databricks_token_manager(cfg) is False


def test_needs_databricks_token_manager_false_when_static_token_present():
    cfg = {"dbx": {"type": "databricks", "host": "h", "http_path": "/p", "token": "dapi_123"}}
    assert _needs_databricks_token_manager(cfg) is False


def test_needs_databricks_token_manager_true_when_token_placeholder():
    cfg = {"dbx": {"type": "databricks", "host": "h", "http_path": "/p", "token": "${DATABRICKS_TOKEN}"}}
    assert _needs_databricks_token_manager(cfg) is True


def test_needs_databricks_token_manager_false_when_databricks_not_fully_configured():
    cfg = {"dbx": {"type": "databricks", "host": "${DATABRICKS_HOST}", "http_path": "/p", "token": "${DATABRICKS_TOKEN}"}}
    assert _needs_databricks_token_manager(cfg) is False


def test_databricks_oauth_configured(monkeypatch):
    monkeypatch.setenv("DATABRICKS_TOKEN_URL", "https://accounts.example.com/token")
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "cid")
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "secret")
    assert _databricks_oauth_configured() is True

    monkeypatch.delenv("DATABRICKS_CLIENT_SECRET", raising=False)
    assert _databricks_oauth_configured() is False


def test_sigma_oauth_configured(monkeypatch):
    monkeypatch.setenv("SIGMA_TOKEN_URL", "https://sigma.example.com/token")
    monkeypatch.setenv("SIGMA_CLIENT_ID", "cid")
    monkeypatch.setenv("SIGMA_CLIENT_SECRET", "secret")
    assert _sigma_oauth_configured() is True

    monkeypatch.setenv("SIGMA_TOKEN_URL", "not-a-url")
    assert _sigma_oauth_configured() is False


def test_register_registry_skips_invalid_datasource(monkeypatch, caplog):
    app = Flask(__name__)
    cfg = {
        "primary": {"type": "databricks", "host": "https://ok"},
        "broken": {"type": "databricks", "host": "bad"},
    }

    monkeypatch.setattr("app.factory.load_analytics_config", lambda: cfg)

    def _create(_type, ds_cfg):
        if ds_cfg["host"] == "bad":
            raise ValueError("invalid host")
        return _DummyExecutor("databricks")

    monkeypatch.setattr("app.factory.ExecutorFactory.create", _create)

    with caplog.at_level(logging.WARNING, logger="app.factory"):
        _register_analytics_registry(app)

    registry = app.extensions.get("analytics_registry")
    assert registry is not None
    assert registry.list_datasources() == [{"name": "primary", "type": "databricks"}]
    assert any("skipped 1 datasource(s): broken" in msg for msg in caplog.messages)


def test_register_registry_sets_empty_registry_when_all_invalid(monkeypatch, caplog):
    app = Flask(__name__)
    cfg = {"broken": {"type": "databricks", "host": "bad"}}

    monkeypatch.setattr("app.factory.load_analytics_config", lambda: cfg)
    monkeypatch.setattr(
        "app.factory.ExecutorFactory.create",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("invalid host")),
    )

    with caplog.at_level(logging.WARNING, logger="app.factory"):
        _register_analytics_registry(app)

    registry = app.extensions.get("analytics_registry")
    assert registry is not None
    assert registry.list_datasources() == []
    assert any("initialised with 0 datasource(s); skipped 1 datasource(s)" in msg for msg in caplog.messages)


def test_register_registry_injects_token_manager_for_databricks(monkeypatch):
    app = Flask(__name__)
    app.config["DATABRICKS_TOKEN_MANAGER"] = object()
    cfg = {
        "primary": {
            "type": "databricks",
            "host": "https://adb-1.azuredatabricks.net",
            "token": "${DATABRICKS_TOKEN}",
            "http_path": "/sql/1.0/warehouses/w1",
        }
    }
    captured = {}

    monkeypatch.setattr("app.factory.load_analytics_config", lambda: cfg)

    def _create(_type, ds_cfg):
        captured.update(ds_cfg)
        return _DummyExecutor("databricks")

    monkeypatch.setattr("app.factory.ExecutorFactory.create", _create)

    _register_analytics_registry(app)

    assert "token" not in captured
    assert captured["token_provider"] is app.config["DATABRICKS_TOKEN_MANAGER"]


def test_register_registry_uses_preloaded_config(monkeypatch):
    app = Flask(__name__)
    cfg = {
        "primary": {
            "type": "snowflake",
            "account": "acc",
            "user": "u",
            "database": "db",
            "authenticator": "externalbrowser",
        }
    }

    monkeypatch.setattr(
        "app.factory.load_analytics_config",
        lambda: (_ for _ in ()).throw(RuntimeError("should not be called")),
    )
    monkeypatch.setattr(
        "app.factory.ExecutorFactory.create",
        lambda _type, _cfg: _DummyExecutor("snowflake"),
    )

    _register_analytics_registry(app, config=cfg)

    registry = app.extensions.get("analytics_registry")
    assert registry is not None
    assert registry.list_datasources() == [{"name": "primary", "type": "snowflake"}]
