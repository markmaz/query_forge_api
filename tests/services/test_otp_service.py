from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import otp_service


class _EmailTask:
    def __init__(self) -> None:
        self.calls = []

    def delay(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


def test_generate_otp_sends_email(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(otp_secret="secret", email="a@example.com")

    class DummyUserService:
        def get_user(self, _user_id: str):
            return user

    class DummyTotp:
        def __init__(self, secret: str) -> None:
            self.secret = secret

        def now(self) -> str:
            return "123456"

    task = _EmailTask()
    monkeypatch.setattr(otp_service, "UserService", DummyUserService)
    monkeypatch.setattr(otp_service.pyotp, "TOTP", DummyTotp)
    monkeypatch.setattr("app.tasks.email_tasks.send_otp_email", task)

    code = otp_service.generate_otp("u1")
    assert code == "123456"
    assert task.calls


def test_verify_otp_no_user(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyUserService:
        def get_user(self, _user_id: str):
            return None

    monkeypatch.setattr(otp_service, "UserService", DummyUserService)
    assert otp_service.verify_otp("u1", "123") is None


def test_verify_otp_missing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(otp_secret=None)

    class DummyUserService:
        def get_user(self, _user_id: str):
            return user

    monkeypatch.setattr(otp_service, "UserService", DummyUserService)
    assert otp_service.verify_otp("u1", "123") is False


def test_verify_otp_success(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(otp_secret="secret")

    class DummyUserService:
        def get_user(self, _user_id: str):
            return user

    class DummyTotp:
        def __init__(self, secret: str) -> None:
            self.secret = secret

        def verify(self, _otp: str, valid_window: int = 1) -> bool:
            return True

    class DummyAuth:
        def generate_token(self, _user):
            return "token"

    monkeypatch.setattr(otp_service, "UserService", DummyUserService)
    monkeypatch.setattr(otp_service.pyotp, "TOTP", DummyTotp)
    monkeypatch.setattr(otp_service, "AuthService", lambda: DummyAuth())

    assert otp_service.verify_otp("u1", "123") == "token"
