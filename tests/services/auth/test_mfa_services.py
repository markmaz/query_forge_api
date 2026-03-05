from __future__ import annotations

from contextlib import contextmanager

import pyotp
import pytest
from werkzeug.security import generate_password_hash

from app.exceptions.service_error import ServiceError
from app.services.auth.login_challenge_service import LoginChallengeService
from app.services.auth.rate_limit_service import RateLimitService
from app.services.auth.totp_service import TotpService


class _FakeRedisPipeline:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store
        self._ops = []

    def get(self, key: str):
        self._ops.append(("get", key))
        return self

    def delete(self, key: str):
        self._ops.append(("delete", key))
        return self

    def execute(self):
        out = []
        for op, key in self._ops:
            if op == "get":
                out.append(self._store.get(key))
            else:
                out.append(1 if self._store.pop(key, None) is not None else 0)
        return out


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def setex(self, key: str, ttl: int, value: str) -> bool:
        self.store[key] = str(value)
        self.ttls[key] = int(ttl)
        return True

    def get(self, key: str):
        return self.store.get(key)

    def delete(self, key: str) -> int:
        existed = key in self.store
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return 1 if existed else 0

    def incr(self, key: str) -> int:
        self.counts[key] = int(self.counts.get(key, 0)) + 1
        return self.counts[key]

    def expire(self, key: str, ttl: int) -> bool:
        self.ttls[key] = int(ttl)
        return True

    def ttl(self, key: str) -> int:
        return int(self.ttls.get(key, 0))

    def pipeline(self):
        return _FakeRedisPipeline(self.store)


class _FakeTx:
    def __init__(self, row: dict[str, object], writes: list[tuple[str, dict]]) -> None:
        self._row = row
        self._writes = writes

    def execute_write(self, query: str, params: dict) -> int:
        self._writes.append((query, params))
        q = query.lower()
        if "set otp_totp_secret = :secret" in q:
            self._row["otp_totp_secret"] = params["secret"]
            self._row["otp_totp_enabled"] = 1
            self._row["otp_mfa_method"] = "totp"
            self._row["two_factor_preference"] = "Authenticator"
            self._row["otp_totp_confirmed_at"] = "now"
            return 1
        if "set otp_totp_secret = null" in q:
            self._row["otp_totp_secret"] = None
            self._row["otp_totp_enabled"] = 0
            self._row["otp_mfa_method"] = None
            self._row["two_factor_preference"] = "Email"
            self._row["otp_totp_confirmed_at"] = None
            return 1
        return 0


class _FakeSQL:
    def __init__(self, user_row: dict[str, object]) -> None:
        self.user_row = user_row
        self.writes: list[tuple[str, dict]] = []

    def execute_query_mappings(self, query: str, params: dict | None = None):
        del query
        wanted_user_id = str((params or {}).get("user_id") or "")
        if wanted_user_id and wanted_user_id == str(self.user_row.get("user_id")):
            return [dict(self.user_row)]
        return []

    @contextmanager
    def transaction(self):
        yield _FakeTx(self.user_row, self.writes)


def test_login_challenge_create_and_consume() -> None:
    redis_fake = _FakeRedis()
    svc = LoginChallengeService(redis_client=redis_fake)
    challenge_id = svc.create_challenge("u1")
    assert challenge_id
    assert redis_fake.get(f"login:challenge:{challenge_id}") == "u1"
    assert svc.consume_challenge(challenge_id) == "u1"
    assert svc.consume_challenge(challenge_id) is None


def test_rate_limit_enforce() -> None:
    redis_fake = _FakeRedis()
    svc = RateLimitService(redis_client=redis_fake)
    svc.enforce(scope="mfa:test", identifier="u1", max_attempts=2, window_s=60)
    svc.enforce(scope="mfa:test", identifier="u1", max_attempts=2, window_s=60)
    with pytest.raises(ServiceError) as exc:
        svc.enforce(scope="mfa:test", identifier="u1", max_attempts=2, window_s=60)
    assert exc.value.status_code == 429


def test_totp_start_and_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    user_row = {
        "user_id": "u1",
        "username": "u1@example.com",
        "email": "u1@example.com",
        "password": generate_password_hash("pw"),
        "otp_totp_secret": None,
        "otp_totp_enabled": 0,
        "otp_totp_confirmed_at": None,
        "otp_mfa_method": None,
        "two_factor_preference": "Email",
    }
    redis_fake = _FakeRedis()
    sql_fake = _FakeSQL(user_row)
    svc = TotpService(sql=sql_fake, redis_client=redis_fake)
    monkeypatch.setattr(TotpService, "_to_qr_svg", staticmethod(lambda _v: "<svg/>"))

    started = svc.start_totp_enrollment("u1")
    assert started["otpauth_uri"]
    pending_secret = redis_fake.get("totp:pending:u1")
    assert pending_secret
    code = pyotp.TOTP(pending_secret).now()

    confirmed = svc.confirm_totp_enrollment("u1", code)
    assert confirmed["enabled"] is True
    assert user_row["otp_totp_enabled"] == 1
    assert user_row["otp_totp_secret"] == pending_secret
    assert redis_fake.get("totp:pending:u1") is None


def test_totp_verify_and_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    del monkeypatch
    secret = pyotp.random_base32()
    user_row = {
        "user_id": "u1",
        "username": "u1@example.com",
        "email": "u1@example.com",
        "password": generate_password_hash("pw"),
        "otp_totp_secret": secret,
        "otp_totp_enabled": 1,
        "otp_totp_confirmed_at": "now",
        "otp_mfa_method": "totp",
        "two_factor_preference": "Authenticator",
    }
    redis_fake = _FakeRedis()
    sql_fake = _FakeSQL(user_row)
    svc = TotpService(sql=sql_fake, redis_client=redis_fake)

    ok_code = pyotp.TOTP(secret).now()
    assert svc.verify_totp_code("u1", ok_code) is True
    assert svc.verify_totp_code("u1", "000000") is False

    disabled = svc.disable_totp("u1", "pw", ok_code)
    assert disabled["enabled"] is False
    assert user_row["otp_totp_enabled"] == 0
    assert user_row["otp_totp_secret"] is None
