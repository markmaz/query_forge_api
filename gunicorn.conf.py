from __future__ import annotations

import os


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return value if value >= 0 else default


bind = os.getenv("QF_GUNICORN_BIND", "0.0.0.0:8000")
workers = max(1, _int_env("QF_GUNICORN_WORKERS", 1))
timeout = max(1, _int_env("QF_GUNICORN_TIMEOUT", 120))

# Recycle long-lived workers to contain slow Python/native-library leaks.
max_requests = _int_env("QF_GUNICORN_MAX_REQUESTS", 1000)
max_requests_jitter = _int_env("QF_GUNICORN_MAX_REQUESTS_JITTER", 100)

accesslog = os.getenv("QF_GUNICORN_ACCESS_LOG", "-")
errorlog = os.getenv("QF_GUNICORN_ERROR_LOG", "-")
loglevel = os.getenv("QF_GUNICORN_LOG_LEVEL", "info")
