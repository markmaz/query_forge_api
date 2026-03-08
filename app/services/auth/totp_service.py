from __future__ import annotations

import io
import logging
import os
from typing import Any, Dict, Optional

import pyotp
import redis
from werkzeug.security import check_password_hash

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import OTP_VALID_WINDOW, VALKEY_CONFIG
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)

TOTP_PENDING_TTL_S = int(os.getenv("TOTP_PENDING_TTL_SECONDS", "600"))
TOTP_ISSUER_NAME = (os.getenv("TOTP_ISSUER_NAME", "Query Forge") or "Query Forge").strip() or "Query Forge"
_PENDING_PREFIX = "totp:pending:"


class TotpService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, redis_client: Any | None = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._redis = redis_client or redis.Redis.from_url(VALKEY_CONFIG, decode_responses=True)
        self._valid_window = int(OTP_VALID_WINDOW)

    def start_totp_enrollment(self, user_id: str) -> Dict[str, Any]:
        user = self._get_user_auth_row(user_id)
        if not user:
            raise ForgeError("Unable to start TOTP enrollment", status_code=400)

        secret = pyotp.random_base32()
        self._redis.setex(self._pending_key(user_id), TOTP_PENDING_TTL_S, secret)

        name = str(user.get("email") or user.get("username") or user_id).strip() or str(user_id)
        otpauth_uri = pyotp.TOTP(secret).provisioning_uri(name=name, issuer_name=TOTP_ISSUER_NAME)
        qr_svg = self._to_qr_svg(otpauth_uri)
        self._audit("totp_start", user_id=user_id)
        return {
            "otpauth_uri": otpauth_uri,
            "qr_svg": qr_svg,
            "manual_secret_masked": self._mask_secret(secret),
            "expires_in_seconds": TOTP_PENDING_TTL_S,
        }

    def confirm_totp_enrollment(self, user_id: str, code: str) -> Dict[str, Any]:
        normalized_code = self._normalize_code(code)
        if not normalized_code:
            raise ForgeError("code is required", status_code=400)

        pending_secret = str(self._redis.get(self._pending_key(user_id)) or "").strip()
        if not pending_secret:
            raise ForgeError("Enrollment has expired. Start setup again.", status_code=400)

        verified = pyotp.TOTP(pending_secret).verify(normalized_code, valid_window=self._valid_window)
        if not verified:
            self._audit("totp_verify_fail", user_id=user_id, extra={"context": "enrollment_confirm"})
            raise ForgeError("Invalid code", status_code=401)

        sql = """
            UPDATE users
            SET otp_totp_secret = :secret,
                otp_totp_enabled = 1,
                otp_totp_confirmed_at = UTC_TIMESTAMP(),
                otp_mfa_method = 'totp',
                two_factor_preference = 'Authenticator'
            WHERE user_id = :user_id
        """
        with self._sql.transaction() as tx:
            tx.execute_write(sql, {"secret": pending_secret, "user_id": str(user_id)})

        self._redis.delete(self._pending_key(user_id))
        self._audit("totp_confirm", user_id=user_id)
        return {"enabled": True}

    def verify_totp_code(self, user_id: str, code: str) -> bool:
        normalized_code = self._normalize_code(code)
        if not normalized_code:
            self._audit("totp_verify_fail", user_id=user_id, extra={"context": "login"})
            return False

        user = self._get_user_auth_row(user_id)
        if not user:
            self._audit("totp_verify_fail", user_id=user_id, extra={"context": "login"})
            return False

        if not bool(user.get("otp_totp_enabled")):
            self._audit("totp_verify_fail", user_id=user_id, extra={"context": "login"})
            return False

        secret = str(user.get("otp_totp_secret") or "").strip()
        if not secret:
            self._audit("totp_verify_fail", user_id=user_id, extra={"context": "login"})
            return False

        verified = pyotp.TOTP(secret).verify(normalized_code, valid_window=self._valid_window)
        self._audit("totp_verify_success" if verified else "totp_verify_fail", user_id=user_id, extra={"context": "login"})
        return bool(verified)

    def disable_totp(self, user_id: str, password: str, code: str) -> Dict[str, Any]:
        user = self._get_user_auth_row(user_id)
        if not user:
            raise ForgeError("Unable to disable TOTP", status_code=400)

        if not bool(user.get("otp_totp_enabled")):
            return {"enabled": False}

        hashed_password = str(user.get("password") or "")
        if not hashed_password or not check_password_hash(hashed_password, password or ""):
            raise ForgeError("Invalid credentials", status_code=401)

        if not self.verify_totp_code(user_id, code):
            raise ForgeError("Invalid code", status_code=401)

        sql = """
            UPDATE users
            SET otp_totp_secret = NULL,
                otp_totp_enabled = 0,
                otp_totp_confirmed_at = NULL,
                otp_mfa_method = NULL,
                two_factor_preference = 'Email'
            WHERE user_id = :user_id
        """
        with self._sql.transaction() as tx:
            tx.execute_write(sql, {"user_id": str(user_id)})

        self._redis.delete(self._pending_key(user_id))
        self._audit("totp_disable", user_id=user_id)
        return {"enabled": False}

    def is_totp_enabled(self, user_id: str) -> bool:
        user = self._get_user_auth_row(user_id)
        return bool(user and user.get("otp_totp_enabled"))

    def _get_user_auth_row(self, user_id: str) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT user_id, username, email, password,
                   otp_totp_secret, otp_totp_enabled, otp_totp_confirmed_at,
                   two_factor_preference, otp_mfa_method
            FROM users
            WHERE user_id = :user_id
            LIMIT 1
        """
        rows = self._sql.execute_query_mappings(sql, {"user_id": str(user_id)})
        return dict(rows[0]) if rows else None

    @staticmethod
    def _normalize_code(code: str) -> str:
        digits = "".join(ch for ch in str(code or "") if ch.isdigit())
        if not digits:
            return ""
        if len(digits) < 6:
            return digits.zfill(6)
        return digits[:8]

    @staticmethod
    def _pending_key(user_id: str) -> str:
        return f"{_PENDING_PREFIX}{str(user_id or '').strip()}"

    @staticmethod
    def _mask_secret(secret: str) -> str:
        text = str(secret or "").strip()
        if len(text) <= 8:
            return "*" * len(text)
        return f"{text[:4]}{'*' * (len(text) - 8)}{text[-4:]}"

    @staticmethod
    def _to_qr_svg(content: str) -> str:
        try:
            import qrcode  # type: ignore
            from qrcode.image.svg import SvgPathImage  # type: ignore
        except Exception as exc:
            raise ForgeError("QR code generation is unavailable", status_code=500) from exc

        image = qrcode.make(content, image_factory=SvgPathImage)
        buff = io.BytesIO()
        image.save(buff)
        return buff.getvalue().decode("utf-8")

    def _audit(self, event: str, *, user_id: str, extra: Optional[Dict[str, Any]] = None) -> None:
        meta = extra or {}
        logger.info("mfa_event=%s user_id=%s meta=%s", event, str(user_id), meta)
