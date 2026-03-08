from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.exceptions.forge_error import ForgeError
from app.services import otp_service


class _EmailTask:
    def __init__(self) -> None:
        self.calls = []

    def delay(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


class _FakeRedis:
    def __init__(self) -> None:
        self.hashes = {}
        self.counts = {}

    def incr(self, key: str) -> int:
        self.counts[key] = int(self.counts.get(key, 0)) + 1
        return self.counts[key]

    def expire(self, key: str, _ttl: int) -> bool:
        return key in self.hashes or key in self.counts

    def hset(self, key: str, *args, **kwargs):
        bucket = self.hashes.setdefault(key, {})
        mapping = kwargs.get("mapping")
        if mapping:
            for k, v in mapping.items():
                bucket[str(k)] = str(v)
            return len(mapping)
        if len(args) == 2:
            field, value = args
            bucket[str(field)] = str(value)
            return 1
        return 0

    def hgetall(self, key: str):
        return dict(self.hashes.get(key, {}))

    def delete(self, key: str) -> int:
        existed = key in self.hashes
        self.hashes.pop(key, None)
        return 1 if existed else 0


def test_issue_otp_challenge_sends_email_and_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(user_id="u1", otp_secret="secret", email="a@example.com")
    redis_fake = _FakeRedis()

    class DummyUserService:
        def get_user(self, _user_id: str):
            return user

    class DummyTotp:
        def __init__(self, secret: str) -> None:
            self.secret = secret

        def now(self) -> str:
            return "123456"

    task = _EmailTask()
    monkeypatch.setattr(otp_service, "r", redis_fake)
    monkeypatch.setattr(otp_service, "UserService", DummyUserService)
    monkeypatch.setattr(otp_service.pyotp, "TOTP", DummyTotp)
    monkeypatch.setattr("app.tasks.email_tasks.send_otp_email", task)

    challenge_id = otp_service.issue_otp_challenge(user_id="u1", ip_address="1.2.3.4", user_agent="ua")
    assert challenge_id
    assert task.calls
    challenge = redis_fake.hgetall(otp_service._challenge_key(challenge_id))
    assert challenge["user_id"] == "u1"
    assert challenge["attempts"] == "0"


def test_issue_otp_challenge_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(user_id="u1", otp_secret="secret", email="a@example.com")
    redis_fake = _FakeRedis()

    class DummyUserService:
        def get_user(self, _user_id: str):
            return user

    class DummyTotp:
        def __init__(self, secret: str) -> None:
            self.secret = secret

        def now(self) -> str:
            return "123456"

    task = _EmailTask()
    monkeypatch.setattr(otp_service, "r", redis_fake)
    monkeypatch.setattr(otp_service, "UserService", DummyUserService)
    monkeypatch.setattr(otp_service.pyotp, "TOTP", DummyTotp)
    monkeypatch.setattr("app.tasks.email_tasks.send_otp_email", task)
    monkeypatch.setattr(otp_service, "OTP_ISSUE_MAX_PER_USER", 1)

    otp_service.issue_otp_challenge(user_id="u1")
    with pytest.raises(ForgeError):
        otp_service.issue_otp_challenge(user_id="u1")


def test_verify_otp_challenge_success(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(user_id="u1", otp_secret="secret", email="a@example.com")
    redis_fake = _FakeRedis()

    class DummyUserService:
        def get_user(self, _user_id: str):
            return user

    class DummyTotp:
        def __init__(self, secret: str) -> None:
            self.secret = secret

        def verify(self, _otp: str, valid_window: int = 1) -> bool:
            return True

    monkeypatch.setattr(otp_service, "r", redis_fake)
    monkeypatch.setattr(otp_service, "UserService", DummyUserService)
    monkeypatch.setattr(otp_service.pyotp, "TOTP", DummyTotp)

    redis_fake.hset("auth:otp:challenge:abc", mapping={"user_id": "u1", "attempts": "0"})
    out = otp_service.verify_otp_challenge(challenge_id="abc", otp="123456")
    assert out == user
    assert redis_fake.hgetall("auth:otp:challenge:abc") == {}


def test_verify_otp_challenge_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(user_id="u1", otp_secret="secret", email="a@example.com")
    redis_fake = _FakeRedis()

    class DummyUserService:
        def get_user(self, _user_id: str):
            return user

    class DummyTotp:
        def __init__(self, secret: str) -> None:
            self.secret = secret

        def verify(self, _otp: str, valid_window: int = 1) -> bool:
            return False

    monkeypatch.setattr(otp_service, "r", redis_fake)
    monkeypatch.setattr(otp_service, "UserService", DummyUserService)
    monkeypatch.setattr(otp_service.pyotp, "TOTP", DummyTotp)
    monkeypatch.setattr(otp_service, "OTP_CHALLENGE_MAX_ATTEMPTS", 2)

    redis_fake.hset("auth:otp:challenge:abc", mapping={"user_id": "u1", "attempts": "0"})
    assert otp_service.verify_otp_challenge(challenge_id="abc", otp="111111") is None
    assert otp_service.verify_otp_challenge(challenge_id="abc", otp="111111") is None
    assert redis_fake.hgetall("auth:otp:challenge:abc") == {}
