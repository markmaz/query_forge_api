from __future__ import annotations

import os
import uuid
from typing import Optional

import pyotp
import redis

from app.config import OTP_VALID_WINDOW, VALKEY_ADDRESS, VALKEY_PORT
from app.exceptions.forge_error import ForgeError
from app.services.user_service import UserService

OTP_CHALLENGE_TTL_S = int(os.getenv("OTP_CHALLENGE_TTL_SECONDS", "300"))
OTP_CHALLENGE_MAX_ATTEMPTS = int(os.getenv("OTP_CHALLENGE_MAX_ATTEMPTS", "5"))
OTP_ISSUE_RATE_WINDOW_S = int(os.getenv("OTP_ISSUE_RATE_WINDOW_SECONDS", "300"))
OTP_ISSUE_MAX_PER_USER = int(os.getenv("OTP_ISSUE_MAX_PER_USER", "5"))
OTP_ISSUE_MAX_PER_IP = int(os.getenv("OTP_ISSUE_MAX_PER_IP", "20"))

_CHALLENGE_PREFIX = "auth:otp:challenge:"
_RATE_USER_PREFIX = "auth:otp:issue:user:"
_RATE_IP_PREFIX = "auth:otp:issue:ip:"

r = redis.Redis(host=VALKEY_ADDRESS, port=VALKEY_PORT, db=0, decode_responses=True)


def _challenge_key(challenge_id: str) -> str:
    return f"{_CHALLENGE_PREFIX}{challenge_id}"


def _incr_with_ttl(key: str, ttl_s: int) -> int:
    count = int(r.incr(key))
    if count == 1:
        r.expire(key, int(ttl_s))
    return count


def _enforce_issue_rate_limit(*, user_id: str, ip_address: Optional[str]) -> None:
    user_count = _incr_with_ttl(f"{_RATE_USER_PREFIX}{user_id}", OTP_ISSUE_RATE_WINDOW_S)
    if user_count > OTP_ISSUE_MAX_PER_USER:
        raise ForgeError("Too many OTP requests", status_code=429)

    ip = (ip_address or "").strip()
    if ip:
        ip_count = _incr_with_ttl(f"{_RATE_IP_PREFIX}{ip}", OTP_ISSUE_RATE_WINDOW_S)
        if ip_count > OTP_ISSUE_MAX_PER_IP:
            raise ForgeError("Too many OTP requests", status_code=429)


def issue_otp_challenge(*, user_id: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> str:
    user_service = UserService()
    user = user_service.get_user(user_id)
    if not user or not user.otp_secret or not user.email:
        raise ForgeError("Unable to start OTP challenge", status_code=400)

    _enforce_issue_rate_limit(user_id=user_id, ip_address=ip_address)

    totp = pyotp.TOTP(user.otp_secret)
    code = totp.now()

    from app.tasks.email_tasks import send_otp_email

    send_otp_email.delay(user.email, code)

    challenge_id = uuid.uuid4().hex
    payload = {
        "user_id": str(user.user_id),
        "attempts": "0",
    }
    if ip_address:
        payload["ip_address"] = str(ip_address).strip()[:128]
    if user_agent:
        payload["user_agent"] = str(user_agent)[:512]

    key = _challenge_key(challenge_id)
    r.hset(key, mapping=payload)
    r.expire(key, OTP_CHALLENGE_TTL_S)
    return challenge_id


def verify_otp_challenge(
    *,
    challenge_id: str,
    otp: str,
    ip_address: Optional[str] = None,
) -> Optional[object]:
    key = _challenge_key(str(challenge_id or "").strip())
    challenge = r.hgetall(key)
    if not challenge:
        return None

    expected_ip = (challenge.get("ip_address") or "").strip()
    if expected_ip and (ip_address or "").strip() and expected_ip != (ip_address or "").strip():
        return None

    attempts = int(challenge.get("attempts") or "0")
    if attempts >= OTP_CHALLENGE_MAX_ATTEMPTS:
        r.delete(key)
        return None

    attempts += 1
    r.hset(key, "attempts", str(attempts))

    user_id = (challenge.get("user_id") or "").strip()
    if not user_id:
        r.delete(key)
        return None

    user_service = UserService()
    user = user_service.get_user(user_id)
    if not user or not user.otp_secret:
        r.delete(key)
        return None

    totp = pyotp.TOTP(user.otp_secret)
    if totp.verify(otp, valid_window=OTP_VALID_WINDOW):
        r.delete(key)
        return user

    if attempts >= OTP_CHALLENGE_MAX_ATTEMPTS:
        r.delete(key)
    return None
