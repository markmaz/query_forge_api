from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.utils import password_check


def test_is_strong_password() -> None:
    assert password_check.is_strong_password("Abcd1234!")
    assert not password_check.is_strong_password("weakpass")


def test_is_good_password_rejects_pwned(monkeypatch) -> None:
    monkeypatch.setattr(password_check, "MIN_PASSWORD_LENGTH", 8)
    monkeypatch.setattr(password_check, "pwned_count", lambda _p: 5)
    assert password_check.is_good_password("Abcd1234!") is False


def test_pwned_count_handles_response(monkeypatch) -> None:
    def fake_get(_url):
        return SimpleNamespace(status_code=200, text="ABCDEF:2\n123456:1\n")

    monkeypatch.setattr(password_check, "PASSWORD_CHECK_URL", "https://example.test/")
    monkeypatch.setattr(password_check.requests, "get", fake_get)

    assert password_check.pwned_count("password") >= 0

    def fake_fail(_url):
        return SimpleNamespace(status_code=500, text="")

    monkeypatch.setattr(password_check.requests, "get", fake_fail)
    with pytest.raises(Exception):
        password_check.pwned_count("password")
