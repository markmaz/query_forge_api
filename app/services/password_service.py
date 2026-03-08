from __future__ import annotations

import logging
from collections.abc import Callable

import pyotp

from app.config import MIN_PASSWORD_LENGTH
from app.decorators.validate import validate_params
from app.exceptions.forge_error import ForgeError
from app.utils.password_check import pwned_count, is_proper_length, is_strong_password

logger = logging.getLogger(__name__)


class _PasswordPolicy:
    def __init__(self) -> None:
        self._checks: list[Callable[[str], int]] = [
            check_password_length,
            check_is_string,
            check_breach,
        ]

    def validate(self, password: str) -> int:
        for check in self._checks:
            check(password)
        return 200


@validate_params("password")
def check_breach(password: str) -> int:
    breach_count = pwned_count(password)
    if breach_count > 0:
        raise ForgeError(
            "That password has been exposed in a breach. Please choose another password.",
            status_code=422,
        )
    return 200


def check_password_length(password: str) -> int:
    if not is_proper_length(password):
        raise ForgeError(
            f"Password does not meet the minimum number of characters - {MIN_PASSWORD_LENGTH}",
            status_code=422,
        )
    return 200


def check_is_string(password: str) -> int:
    if not is_strong_password(password):
        raise ForgeError(
            "Password does not contain at least 1 upper case letter, 1 lower case letter, or 1 special symbol",
            status_code=422,
        )
    return 200


def validate_password_policy(password: str) -> int:
    policy = _PasswordPolicy()
    return policy.validate(password)


def generate_otp_secret() -> str:
    return pyotp.random_base32()
