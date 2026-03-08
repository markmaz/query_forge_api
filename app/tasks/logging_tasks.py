try:
    from flask import current_app

    celery = current_app.config.get("CELERY")
except Exception:
    celery = None


def flush_query_log():
    return None


if celery is not None:
    flush_query_log = celery.task(flush_query_log)
