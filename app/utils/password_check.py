# utils/hibp.py
import hashlib
import re

import requests

from app.config import MIN_PASSWORD_LENGTH, PASSWORD_CHECK_URL

pattern = re.compile(
    r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[\W_]).{8,}$'
)

def is_strong_password(password):
    return bool(pattern.match(password))

def is_proper_length(password) -> bool:
    return len(password) >= int(MIN_PASSWORD_LENGTH)

def is_good_password(password: str) -> bool:
    if not is_proper_length(password):
        return False
    
    if not is_strong_password(password):
        return False
    
    if check_password_pwned(password) > 0:
        return False
    
    return True

def check_password_pwned(password: str) -> int:
    sha1 = hashlib.sha1(password.encode('utf-8')).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]

    url = f"{PASSWORD_CHECK_URL}{prefix}"
    response = requests.get(url)

    if response.status_code != 200:
        raise Exception("Error querying HIBP")

    hashes = (line.split(":") for line in response.text.splitlines())
    for hash_suffix, count in hashes:
        if hash_suffix == suffix:
            return int(count)

    return 0
