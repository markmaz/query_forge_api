from __future__ import annotations

import logging

from app.config import logging_config


def test_configure_logging_defaults_to_info(monkeypatch) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.setenv("LOG_FILE", "test.log")

    kwargs = {}

    monkeypatch.setattr(logging, "FileHandler", lambda *args, **kwargs: logging.NullHandler())
    monkeypatch.setattr(logging, "basicConfig", lambda **k: kwargs.update(k))
    monkeypatch.setattr(logging, "info", lambda *args, **kw: None)

    logging_config.configure_logging()

    assert kwargs["level"] == logging.INFO
    assert kwargs["force"] is True
    assert logging.getLogger("urllib3").getEffectiveLevel() == logging.WARNING


def test_configure_logging_respects_valid_log_level(monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("LOG_FILE", "test.log")

    kwargs = {}

    monkeypatch.setattr(logging, "FileHandler", lambda *args, **kwargs: logging.NullHandler())
    monkeypatch.setattr(logging, "basicConfig", lambda **k: kwargs.update(k))
    monkeypatch.setattr(logging, "info", lambda *args, **kw: None)

    logging_config.configure_logging()

    assert kwargs["level"] == logging.DEBUG


def test_configure_logging_falls_back_for_invalid_level(monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "nope")
    monkeypatch.setenv("LOG_FILE", "test.log")

    kwargs = {}

    monkeypatch.setattr(logging, "FileHandler", lambda *args, **kwargs: logging.NullHandler())
    monkeypatch.setattr(logging, "basicConfig", lambda **k: kwargs.update(k))
    monkeypatch.setattr(logging, "info", lambda *args, **kw: None)

    logging_config.configure_logging()

    assert kwargs["level"] == logging.INFO
