try:
    from flask import current_app

    celery = current_app.config.get("CELERY")
except Exception:
    celery = None


def persist_log():
    return None


if celery is not None:
    persist_log = celery.task(persist_log)
