from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services import password_service


def test_check_breach_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(password_service, "pwned_count", lambda _pw: 0)
    assert password_service.check_breach.__wrapped__(password="GoodPass1!") == 200


def test_check_breach_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(password_service, "pwned_count", lambda _pw: 1)
    with pytest.raises(ForgeError):
        password_service.check_breach.__wrapped__(password="BadPass1!")


def test_check_password_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(password_service, "is_proper_length", lambda _pw: True)
    assert password_service.check_password_length(password="LongEnough1!") == 200

    monkeypatch.setattr(password_service, "is_proper_length", lambda _pw: False)
    with pytest.raises(ForgeError):
        password_service.check_password_length(password="short")


def test_check_is_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(password_service, "is_strong_password", lambda _pw: True)
    assert password_service.check_is_string(password="Strong1!") == 200

    monkeypatch.setattr(password_service, "is_strong_password", lambda _pw: False)
    with pytest.raises(ForgeError):
        password_service.check_is_string(password="weak")


def test_validate_password_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(password_service, "check_password_length", lambda _pw: 200)
    monkeypatch.setattr(password_service, "check_is_string", lambda _pw: 200)
    monkeypatch.setattr(password_service, "check_breach", lambda _pw: 200)
    assert password_service.validate_password_policy(password="Strong1!") == 200


def test_validate_password_policy_raises_on_any_check_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        password_service,
        "check_password_length",
        lambda _pw: (_ for _ in ()).throw(ForgeError("bad", 422)),
    )
    with pytest.raises(ForgeError):
        password_service.validate_password_policy(password="weak")


def test_generate_otp_secret() -> None:
    secret = password_service.generate_otp_secret()
    assert isinstance(secret, str)
    assert len(secret) >= 16
