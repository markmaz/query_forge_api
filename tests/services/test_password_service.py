from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services import password_service


def test_check_breach_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(password_service, "check_password_pwned", lambda _pw: 0)
    assert password_service.check_breach.__wrapped__(password="GoodPass1!") == 200


def test_check_breach_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(password_service, "check_password_pwned", lambda _pw: 1)
    with pytest.raises(ServiceError):
        password_service.check_breach.__wrapped__(password="BadPass1!")


def test_check_password_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(password_service, "is_proper_length", lambda _pw: True)
    assert password_service.check_password_length(password="LongEnough1!") == 200

    monkeypatch.setattr(password_service, "is_proper_length", lambda _pw: False)
    with pytest.raises(ServiceError):
        password_service.check_password_length(password="short")


def test_check_is_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(password_service, "is_strong_password", lambda _pw: True)
    assert password_service.check_is_string(password="Strong1!") == 200

    monkeypatch.setattr(password_service, "is_strong_password", lambda _pw: False)
    with pytest.raises(ServiceError):
        password_service.check_is_string(password="weak")


def test_generate_otp_secret() -> None:
    secret = password_service.generate_otp_secret()
    assert isinstance(secret, str)
    assert len(secret) >= 16
