from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any, Callable

import jwt

from app.exceptions.forge_error import ForgeError

logger = logging.getLogger(__name__)


class TokenLifecycleService:
    def __init__(
        self,
        *,
        secret: str,
        algorithm: str,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
        leeway_seconds: int,
        verify_iat: bool,
        refresh_prefix: str,
        cache,
        access_claims_provider: Callable[[str, str | None], dict[str, Any]],
    ) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._access_ttl_seconds = access_ttl_seconds
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._leeway_seconds = leeway_seconds
        self._verify_iat = verify_iat
        self._refresh_prefix = refresh_prefix
        self._cache = cache
        self._access_claims_provider = access_claims_provider

    def _encode(self, payload: dict[str, Any]) -> str:
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def _decode(self, token: str) -> dict[str, Any]:
        return jwt.decode(
            token,
            self._secret,
            algorithms=[self._algorithm],
            leeway=self._leeway_seconds,
            options={"verify_iat": self._verify_iat, "verify_aud": False},
        )

    def _log_token_timing(self, payload: dict[str, Any], context: str) -> None:
        issued_at = payload.get("iat")
        expiry = payload.get("exp")
        if isinstance(issued_at, datetime.datetime):
            issued_at = int(issued_at.timestamp())
        if isinstance(expiry, datetime.datetime):
            expiry = int(expiry.timestamp())

        now_ts = int(datetime.datetime.now(datetime.UTC).timestamp())
        logger.debug(
            "Token timing (%s): sub=%s typ=%s iat=%s exp=%s now=%s leeway=%s",
            context,
            payload.get("sub"),
            payload.get("typ"),
            issued_at,
            expiry,
            now_ts,
            self._leeway_seconds,
        )

    def decode_and_verify(self, token: str, *, expected_typ: str | None = None) -> dict[str, Any]:
        try:
            payload = self._decode(token)
        except jwt.ExpiredSignatureError as exc:
            logger.warning("JWT decode failed: expired token")
            raise ForgeError("Token expired", status_code=401) from exc
        except jwt.InvalidTokenError as exc:
            logger.warning("JWT decode failed: %s", exc)
            raise ForgeError("Invalid token", status_code=401) from exc

        if expected_typ and payload.get("typ") != expected_typ:
            raise ForgeError("Invalid token type", status_code=401)

        self._log_token_timing(payload, "decode_and_verify")
        return payload

    def generate_access_token(self, user_id: str, extra_claims: dict[str, Any] | None = None) -> str:
        claims = dict(extra_claims or {})
        if "roles" not in claims or "is_admin" not in claims:
            defaults = self._access_claims_provider(user_id, claims.get("username"))
            for key, value in defaults.items():
                claims.setdefault(key, value)

        now = datetime.datetime.now(datetime.UTC)
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "typ": "access",
            "jti": uuid.uuid4().hex,
            "iat": int(now.timestamp()),
            "exp": now + datetime.timedelta(seconds=self._access_ttl_seconds),
        }
        if claims:
            payload.update(claims)
        return self._encode(payload)

    def _generate_refresh_token_with_jti(self, user_id: str) -> tuple[str, str]:
        now = datetime.datetime.now(datetime.UTC)
        jti = uuid.uuid4().hex
        payload = {
            "sub": str(user_id),
            "typ": "refresh",
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": now + datetime.timedelta(seconds=self._refresh_ttl_seconds),
        }
        return self._encode(payload), jti

    def generate_refresh_token(self, user_id: str) -> str:
        token, _ = self._generate_refresh_token_with_jti(user_id)
        return token

    def store_refresh_jti(self, jti: str, user_id: str, ttl_seconds: int) -> None:
        self._cache.setex(f"{self._refresh_prefix}{jti}", int(ttl_seconds), str(user_id))

    def revoke_refresh_jti(self, jti: str) -> None:
        self._cache.delete(f"{self._refresh_prefix}{jti}")

    def is_refresh_jti_valid(self, jti: str) -> bool:
        return bool(self._cache.exists(f"{self._refresh_prefix}{jti}"))

    def issue_tokens(self, user) -> dict[str, Any]:
        claims = self._access_claims_provider(user.user_id, getattr(user, "user_name", None))
        access_token = self.generate_access_token(user.user_id, extra_claims=claims)
        refresh_token, jti = self._generate_refresh_token_with_jti(user.user_id)
        self.store_refresh_jti(jti, user.user_id, self._refresh_ttl_seconds)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": self._access_ttl_seconds,
        }

    def rotate_refresh_token(self, refresh_token: str) -> tuple[str, str]:
        payload = self.decode_and_verify(refresh_token, expected_typ="refresh")
        jti = payload.get("jti")
        if not jti:
            raise ForgeError("Invalid refresh token", status_code=401)
        if not self.is_refresh_jti_valid(jti):
            raise ForgeError("Refresh token revoked", status_code=401)

        user_id = str(payload.get("sub") or "")
        if not user_id:
            raise ForgeError("Invalid refresh token", status_code=401)

        self.revoke_refresh_jti(jti)
        new_refresh_token, new_jti = self._generate_refresh_token_with_jti(user_id)
        self.store_refresh_jti(new_jti, user_id, self._refresh_ttl_seconds)
        return new_refresh_token, user_id

    def verify_token(self, token: str):
        try:
            payload = self._decode(token)
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
        if payload.get("typ") != "access":
            return None
        self._log_token_timing(payload, "verify_token")
        return payload
