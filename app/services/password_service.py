import logging

import pyotp

from app.config import MIN_PASSWORD_LENGTH
from app.decorators.validate import validate_params
from app.exceptions.service_error import ServiceError
from app.utils.password_check import check_password_pwned, is_proper_length, is_strong_password

logger = logging.getLogger(__name__)

@validate_params("password")
def check_breach(password):
    if check_password_pwned(password) > 0:
        raise ServiceError("That password has been exposed in a breach. Please choose another password.", 422)
    else:
        return 200

def check_password_length(password):
    if is_proper_length(password):
        return 200
    else:
        raise ServiceError(f"Password does not meet the minimum number of characters - {MIN_PASSWORD_LENGTH}", 422)

def check_is_string(password):
    if is_strong_password(password):
        return 200
    else:
        raise ServiceError("Password does not contain at least 1 upper case letter, 1 lower case letter, or 1 special symbol", 422)
    

def validate_password_policy(password: str) -> int:
    check_password_length(password)
    check_is_string(password)
    check_breach(password)
    return 200


def generate_otp_secret():
    return pyotp.random_base32()
