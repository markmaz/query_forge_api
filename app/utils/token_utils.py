from __future__ import annotations

from itsdangerous import URLSafeTimedSerializer

from app.config import JWT_SECRET

_INVITE_SALT = "qf-invite-link"


def _make_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key=JWT_SECRET, salt=_INVITE_SALT)


def generate_token(user_id: str) -> str:
    return _make_serializer().dumps(user_id)


def validate_token(token: str, max_age_seconds: int = 86400) -> str:
    return _make_serializer().loads(token, max_age=max_age_seconds)
