from __future__ import annotations

import datetime
import hashlib
import logging
import time
import uuid
from typing import Any

import jwt
import redis
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from app.config import (
    ACCESS_TOKEN_TTL_SECONDS,
    JWT_ALGORITHM,
    JWT_EXP_DELTA_HOURS,
    JWT_LEEWAY_SECONDS,
    JWT_SECRET,
    JWT_VERIFY_IAT,
    REFRESH_TOKEN_TTL_SECONDS,
    VALKEY_CONFIG,
)
from app.utils.param_guard import validate_params
from app.exceptions.forge_error import ForgeError
from app.models.tenancy.user import User
from app.services.user_service import UserService
from app.utils.jwt_claims import claim_has_role
from app.utils.token_utils import generate_token as generate

cache = redis.Redis.from_url(VALKEY_CONFIG, decode_responses=True)
logger = logging.getLogger(__name__)

TTL_SECONDS = 3600
KEY_PREFIX = "qf:reset:"
REFRESH_PREFIX = "qf:refresh:"
DEFAULT_LEEWAY_SECONDS = 30
_DUMMY_PASSWORD_HASH = generate_password_hash("dummy-password-value")


def hash_token(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def qf_get_cache_key(qf_hashed_token: str) -> str:
    return f"{KEY_PREFIX}{qf_hashed_token}"


def cache_key(t: str) -> str:
    return qf_get_cache_key(hash_token(t))


class AuthService:
    def __init__(self):
        self.secret = JWT_SECRET
        self.qf_algorithm = JWT_ALGORITHM
        self.exp_delta = datetime.timedelta(hours=JWT_EXP_DELTA_HOURS)
        self.access_ttl_seconds = int(ACCESS_TOKEN_TTL_SECONDS or (JWT_EXP_DELTA_HOURS * 3600))
        self.qf_refresh_ttl = int(REFRESH_TOKEN_TTL_SECONDS or (14 * 24 * 3600))
        self.leeway_seconds = int(JWT_LEEWAY_SECONDS or DEFAULT_LEEWAY_SECONDS)
        self.verify_iat = bool(JWT_VERIFY_IAT)

    def _norm_status(self, value: object) -> str:
        return str(value or "").strip().lower()

    def _consume_password_check_for_missing_user(self, password: str) -> None:
        check_password_hash(_DUMMY_PASSWORD_HASH, password or "")

    def _raise_invalid_credentials(self, username: str) -> None:
        logger.info("Invalid credentials for username=%s", username)
        raise ForgeError("Invalid credentials", status_code=401)

    def _authenticate_user(self, username: str, password: str):
        try:
            user = UserService().find_user_by_username(username)
            if not user:
                self._consume_password_check_for_missing_user(password)
                self._raise_invalid_credentials(username)

            if self._norm_status(getattr(user, "status", None)) == "deactivated":
                self._consume_password_check_for_missing_user(password)
                self._raise_invalid_credentials(username)

            if not check_password_hash(user.password, password):
                self._raise_invalid_credentials(username)
            return user
        except OperationalError as exc:
            logger.error("Operation failed: %s", exc)
            raise ForgeError("Operation failed: Connection failure.", status_code=500) from exc
        except SQLAlchemyError as exc:
            logger.error("Operation failed: %s", exc)
            raise ForgeError("Database operation failed: Database failure.", status_code=500) from exc

    @validate_params("username", "password")
    def non_interactive_authentication(self, username: str, password: str) -> User:
        user = self._authenticate_user(username, password)
        UserService().update_last_login(user.user_id)
        return user

    @validate_params("username", "password")
    def authenticate(self, username: str, password: str) -> dict[str, Any]:
        user = self._authenticate_user(username, password)
        UserService().update_last_login(user.user_id)
        workspaces = getattr(user, "workspaces", None) or []
        default_ws = next((w for w in workspaces if getattr(w, "is_default", False)), None)
        workspace_id = getattr(default_ws, "workspace_id", None)
        return {
            "user_id": user.user_id,
            "requires_otp": True,
            "email": user.email,
            "workspace_id": workspace_id,
            "workspaceId": workspace_id,
        }

    @validate_params("user")
    def generate_token(self, user: User) -> str:
        return self.generate_access_token(
            user.user_id,
            extra_claims=self.get_access_claims_for_user(user.user_id, username=user.user_name),
        )

    def _encode(self, payload: dict[str, Any]) -> str:
        return jwt.encode(payload, self.secret, algorithm=self.qf_algorithm)

    def _decode(self, token: str) -> dict[str, Any]:
        return jwt.decode(
            token,
            self.secret,
            algorithms=[self.qf_algorithm],
            leeway=self.leeway_seconds,
            options={"verify_iat": self.verify_iat},
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
            self.leeway_seconds,
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
            defaults = self.get_access_claims_for_user(
                user_id,
                username=claims.get("username"),
            )
            for key, value in defaults.items():
                claims.setdefault(key, value)

        now = datetime.datetime.now(datetime.UTC)
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "typ": "access",
            "jti": uuid.uuid4().hex,
            "iat": int(now.timestamp()),
            "exp": now + datetime.timedelta(seconds=self.access_ttl_seconds),
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
            "exp": now + datetime.timedelta(seconds=self.qf_refresh_ttl),
        }
        return self._encode(payload), jti

    def generate_refresh_token(self, user_id: str) -> str:
        token, _ = self._generate_refresh_token_with_jti(user_id)
        return token

    def store_refresh_jti(self, jti: str, user_id: str, qf_ttl_seconds: int) -> None:
        cache.setex(f"{REFRESH_PREFIX}{jti}", int(qf_ttl_seconds), str(user_id))

    def revoke_refresh_jti(self, jti: str) -> None:
        cache.delete(f"{REFRESH_PREFIX}{jti}")

    def is_refresh_jti_valid(self, jti: str) -> bool:
        return bool(cache.exists(f"{REFRESH_PREFIX}{jti}"))

    def issue_tokens(self, user: User) -> dict[str, Any]:
        claims = self.get_access_claims_for_user(user.user_id, username=user.user_name)
        access_token = self.generate_access_token(user.user_id, extra_claims=claims)
        refresh_token, jti = self._generate_refresh_token_with_jti(user.user_id)
        self.store_refresh_jti(jti, user.user_id, self.qf_refresh_ttl)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": self.access_ttl_seconds,
        }

    def get_access_claims_for_user(self, user_id: str, *, username: str | None = None) -> dict[str, Any]:
        claims: dict[str, Any] = {}
        if username:
            claims["username"] = str(username)

        role_names: list[str] = []
        try:
            role_names = UserService().get_user_effective_role_names(str(user_id))
        except Exception as exc:
            logger.warning("Unable to load RBAC roles for user_id=%s: %s", user_id, exc)

        normalized_roles = self._normalize_role_names(role_names)
        claims["roles"] = normalized_roles
        claims["is_admin"] = claim_has_role({"roles": normalized_roles}, "admin")
        return claims

    @staticmethod
    def _normalize_role_names(role_names: list[str]) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for role_name in role_names or []:
            text = str(role_name or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            values.append(text)
        return values

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
        self.store_refresh_jti(new_jti, user_id, self.qf_refresh_ttl)
        return new_refresh_token, user_id

    @validate_params("token")
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

    @validate_params("email")
    def send_reset_request(self, email: str) -> tuple[str, int]:
        service = UserService()
        user = service.find_user_by_username(email)

        if user:
            token = generate(user.user_id)
            key = cache_key(token)
            cache.hset(
                key,
                mapping={
                    "user_id": user.user_id,
                    "purpose": "password_reset",
                    "created": str(int(time.time())),
                    "attempts": "0",
                },
            )
            cache.expire(key, TTL_SECONDS)

            from app.tasks.email_tasks import send_password_reset

            send_password_reset.delay(user.email, token)

        return "", 204

    @validate_params("token")
    def validate_token(self, token: str):
        return cache.exists(cache_key(token))

    @validate_params("password", "qf_hashed_token")
    def reset_password(self, password: str, qf_hashed_token: str):
        key = qf_get_cache_key(qf_hashed_token)

        pipeline = cache.pipeline()
        pipeline.hgetall(key)
        pipeline.delete(key)
        data, _ = pipeline.execute()

        if not data or data.get("purpose") != "password_reset":
            return "", 400

        user_id = data.get("user_id")
        user = User(user_id=user_id, password=password)
        updated = UserService().update_user(user_id, user)
        if updated:
            return "", 204
