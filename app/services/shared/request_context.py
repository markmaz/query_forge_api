from flask import g


def     get_current_username(default: str = "unknown_user") -> str:
    user = getattr(g, "user_data", None)
    if not isinstance(user, dict):
        return default

    return user.get("username") or user.get("sub") or default