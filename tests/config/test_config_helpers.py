from __future__ import annotations

import pytest

import app.config as config


def test_env_int_and_float_fall_back_for_invalid_values(monkeypatch) -> None:
    monkeypatch.setenv("QF_TEST_INT", "not-an-int")
    monkeypatch.setenv("QF_TEST_FLOAT", "not-a-float")

    assert config._env_int("QF_TEST_INT", 7) == 7
    assert config._env_float("QF_TEST_FLOAT", 1.5) == 1.5


def test_env_int_and_float_surface_unexpected_getenv_errors(monkeypatch) -> None:
    def _raise_assertion_error(name, default=None):
        raise AssertionError(f"unexpected getenv bug for {name}")

    monkeypatch.setattr(config.os, "getenv", _raise_assertion_error)

    with pytest.raises(AssertionError, match="unexpected getenv bug for QF_TEST_INT"):
        config._env_int("QF_TEST_INT", 7)

    with pytest.raises(AssertionError, match="unexpected getenv bug for QF_TEST_FLOAT"):
        config._env_float("QF_TEST_FLOAT", 1.5)
