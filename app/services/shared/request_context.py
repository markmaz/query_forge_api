from __future__ import annotations

from flask import g, has_app_context


def resolve_request_username(default: str = "unknown_user") -> str:
    if not has_app_context():
        return default

    payload = getattr(g, "user_data", None)
    if not isinstance(payload, dict):
        return default

    preferred = payload.get("username")
    if isinstance(preferred, str) and preferred:
        return preferred

    subject = payload.get("sub")
    if isinstance(subject, str) and subject:
        return subject

    return default
