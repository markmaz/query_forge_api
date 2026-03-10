from __future__ import annotations

import hashlib
import re

import requests

from app.config import MIN_PASSWORD_LENGTH, PASSWORD_CHECK_URL

_PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[\W_]).{8,}$")


def is_strong_password(password: str) -> bool:
    return bool(_PASSWORD_PATTERN.match(password or ""))


def is_proper_length(password: str) -> bool:
    return len(password or "") >= int(MIN_PASSWORD_LENGTH)


def is_good_password(password: str) -> bool:
    if not is_proper_length(password):
        return False
    if not is_strong_password(password):
        return False
    return pwned_count(password) <= 0


def pwned_count(password: str) -> int:
    digest = hashlib.sha1((password or "").encode("utf-8")).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]

    response = requests.get(f"{PASSWORD_CHECK_URL}{prefix}")
    if int(response.status_code) != 200:
        raise Exception("Error querying HIBP")

    for line in (response.text or "").splitlines():
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        candidate_suffix, count = parts
        if candidate_suffix == suffix:
            return int(count)
    return 0
