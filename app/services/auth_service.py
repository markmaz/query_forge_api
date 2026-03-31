from __future__ import annotations

import datetime
import hashlib
from typing import Any

import redis
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
from app.models.tenancy.user import User
from app.services.auth.credential_auth_service import CredentialAuthenticationService
from app.services.auth.password_reset_service import PasswordResetService
from app.services.auth.token_lifecycle_service import TokenLifecycleService
from app.services.user_service import UserService
from app.utils.token_utils import generate_token as generate

cache = redis.Redis.from_url(VALKEY_CONFIG, decode_responses=True)

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

    def _credentials(self) -> CredentialAuthenticationService:
        return CredentialAuthenticationService(
            user_service_factory=UserService,
            check_password_hash=check_password_hash,
            dummy_password_hash=_DUMMY_PASSWORD_HASH,
        )

    def _token_lifecycle(self) -> TokenLifecycleService:
        return TokenLifecycleService(
            secret=self.secret,
            algorithm=self.qf_algorithm,
            access_ttl_seconds=self.access_ttl_seconds,
            refresh_ttl_seconds=self.qf_refresh_ttl,
            leeway_seconds=self.leeway_seconds,
            verify_iat=self.verify_iat,
            refresh_prefix=REFRESH_PREFIX,
            cache=cache,
            access_claims_provider=lambda user_id, username=None: self.get_access_claims_for_user(
                user_id,
                username=username,
            ),
        )

    def _password_reset(self) -> PasswordResetService:
        from app.tasks.email_tasks import send_password_reset

        return PasswordResetService(
            cache=cache,
            ttl_seconds=TTL_SECONDS,
            token_generator=generate,
            cache_key=cache_key,
            cache_key_from_hashed=qf_get_cache_key,
            user_service_factory=UserService,
            send_password_reset_task=send_password_reset,
        )

    @validate_params("username", "password")
    def non_interactive_authentication(self, username: str, password: str) -> User:
        return self._credentials().non_interactive_authentication(username=username, password=password)

    @validate_params("username", "password")
    def authenticate(self, username: str, password: str) -> dict[str, Any]:
        return self._credentials().authenticate_response(username=username, password=password)

    @validate_params("user")
    def generate_token(self, user: User) -> str:
        return self.generate_access_token(
            user.user_id,
            extra_claims=self.get_access_claims_for_user(user.user_id, username=user.user_name),
        )

    def _encode(self, payload: dict[str, Any]) -> str:
        return self._token_lifecycle()._encode(payload)

    def _decode(self, token: str) -> dict[str, Any]:
        return self._token_lifecycle()._decode(token)

    def _log_token_timing(self, payload: dict[str, Any], context: str) -> None:
        self._token_lifecycle()._log_token_timing(payload, context)

    def decode_and_verify(self, token: str, *, expected_typ: str | None = None) -> dict[str, Any]:
        return self._token_lifecycle().decode_and_verify(token, expected_typ=expected_typ)

    def generate_access_token(self, user_id: str, extra_claims: dict[str, Any] | None = None) -> str:
        return self._token_lifecycle().generate_access_token(user_id, extra_claims=extra_claims)

    def _generate_refresh_token_with_jti(self, user_id: str) -> tuple[str, str]:
        return self._token_lifecycle()._generate_refresh_token_with_jti(user_id)

    def generate_refresh_token(self, user_id: str) -> str:
        return self._token_lifecycle().generate_refresh_token(user_id)

    def store_refresh_jti(self, jti: str, user_id: str, qf_ttl_seconds: int) -> None:
        self._token_lifecycle().store_refresh_jti(jti, user_id, qf_ttl_seconds)

    def revoke_refresh_jti(self, jti: str) -> None:
        self._token_lifecycle().revoke_refresh_jti(jti)

    def is_refresh_jti_valid(self, jti: str) -> bool:
        return self._token_lifecycle().is_refresh_jti_valid(jti)

    def issue_tokens(self, user: User) -> dict[str, Any]:
        return self._token_lifecycle().issue_tokens(user)

    def get_access_claims_for_user(self, user_id: str, *, username: str | None = None) -> dict[str, Any]:
        return self._credentials().get_access_claims_for_user(user_id, username=username)

    @staticmethod
    def _normalize_role_names(role_names: list[str]) -> list[str]:
        return CredentialAuthenticationService._normalize_role_names(role_names)

    def rotate_refresh_token(self, refresh_token: str) -> tuple[str, str]:
        return self._token_lifecycle().rotate_refresh_token(refresh_token)

    @validate_params("token")
    def verify_token(self, token: str):
        return self._token_lifecycle().verify_token(token)

    @validate_params("email")
    def send_reset_request(self, email: str) -> tuple[str, int]:
        return self._password_reset().send_reset_request(email)

    @validate_params("token")
    def validate_token(self, token: str):
        return self._password_reset().validate_token(token)

    @validate_params("password", "qf_hashed_token")
    def reset_password(self, password: str, qf_hashed_token: str):
        return self._password_reset().reset_password(password, qf_hashed_token)
