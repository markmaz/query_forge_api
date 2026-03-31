from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.exceptions.forge_error import ForgeError
from app.models.tenancy.user import User
from app.utils.jwt_claims import claim_has_role

logger = logging.getLogger(__name__)


class CredentialAuthenticationService:
    def __init__(
        self,
        *,
        user_service_factory: Callable[[], Any],
        check_password_hash: Callable[[str, str], bool],
        dummy_password_hash: str,
    ) -> None:
        self._user_service_factory = user_service_factory
        self._check_password_hash = check_password_hash
        self._dummy_password_hash = dummy_password_hash

    @staticmethod
    def _normalize_status(value: object) -> str:
        return str(value or "").strip().lower()

    def _consume_password_check_for_missing_user(self, password: str) -> None:
        self._check_password_hash(self._dummy_password_hash, password or "")

    @staticmethod
    def _raise_invalid_credentials(username: str) -> None:
        logger.info("Invalid credentials for username=%s", username)
        raise ForgeError("Invalid credentials", status_code=401)

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

    def authenticate_user(self, *, username: str, password: str) -> User:
        try:
            user_service = self._user_service_factory()
            user = user_service.find_user_by_username(username)
            if not user:
                self._consume_password_check_for_missing_user(password)
                self._raise_invalid_credentials(username)

            if self._normalize_status(getattr(user, "status", None)) == "deactivated":
                self._consume_password_check_for_missing_user(password)
                self._raise_invalid_credentials(username)

            if not self._check_password_hash(user.password, password):
                self._raise_invalid_credentials(username)
            return user
        except OperationalError as exc:
            logger.error("Operation failed: %s", exc)
            raise ForgeError("Operation failed: Connection failure.", status_code=500) from exc
        except SQLAlchemyError as exc:
            logger.error("Operation failed: %s", exc)
            raise ForgeError("Database operation failed: Database failure.", status_code=500) from exc

    def authenticate_response(self, *, username: str, password: str) -> dict[str, Any]:
        user = self.authenticate_user(username=username, password=password)
        self._user_service_factory().update_last_login(user.user_id)
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

    def non_interactive_authentication(self, *, username: str, password: str) -> User:
        user = self.authenticate_user(username=username, password=password)
        self._user_service_factory().update_last_login(user.user_id)
        return user

    def get_access_claims_for_user(self, user_id: str, *, username: str | None = None) -> dict[str, Any]:
        claims: dict[str, Any] = {}
        if username:
            claims["username"] = str(username)

        role_names: list[str] = []
        try:
            role_names = self._user_service_factory().get_user_effective_role_names(str(user_id))
        except Exception as exc:
            logger.warning("Unable to load RBAC roles for user_id=%s: %s", user_id, exc)

        normalized_roles = self._normalize_role_names(role_names)
        claims["roles"] = normalized_roles
        claims["is_admin"] = claim_has_role({"roles": normalized_roles}, "admin")
        return claims
