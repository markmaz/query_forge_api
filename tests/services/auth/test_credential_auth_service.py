from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.services.auth.credential_auth_service import CredentialAuthenticationService


class _UserService:
    def __init__(self, *, roles=None, role_exc: Exception | None = None) -> None:
        self._roles = list(roles or [])
        self._role_exc = role_exc

    def find_user_by_username(self, username: str):
        del username
        return None

    def update_last_login(self, user_id: str) -> None:
        del user_id

    def get_user_effective_role_names(self, user_id: str):
        del user_id
        if self._role_exc is not None:
            raise self._role_exc
        return list(self._roles)


def _service(*, roles=None, role_exc: Exception | None = None) -> CredentialAuthenticationService:
    return CredentialAuthenticationService(
        user_service_factory=lambda: _UserService(roles=roles, role_exc=role_exc),
        check_password_hash=lambda _stored, _provided: False,
        dummy_password_hash="dummy",
    )


def test_get_access_claims_for_user_falls_back_on_expected_role_load_errors() -> None:
    svc = _service(role_exc=SQLAlchemyError("db unavailable"))

    claims = svc.get_access_claims_for_user("u1", username="ada")

    assert claims == {"username": "ada", "roles": [], "is_admin": False}


def test_get_access_claims_for_user_surfaces_unexpected_role_load_errors() -> None:
    svc = _service(role_exc=AssertionError("unexpected role lookup bug"))

    with pytest.raises(AssertionError, match="unexpected role lookup bug"):
        svc.get_access_claims_for_user("u1")
