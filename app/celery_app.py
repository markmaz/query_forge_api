import os
import platform

from celery import Celery

from app.config import VALKEY_CONFIG

_is_darwin = platform.system().lower() == "darwin"
# Celery CLI defaults to prefork if pool is not explicitly provided. On macOS,
# prefork with native ML libs (torch/sentence-transformers) can crash workers.
if _is_darwin:
    os.environ.setdefault("CELERYD_POOL", os.getenv("QF_CELERY_WORKER_POOL", "solo"))
    os.environ.setdefault("CELERYD_CONCURRENCY", os.getenv("QF_CELERY_WORKER_CONCURRENCY", "1"))

celery = Celery(__name__, broker=VALKEY_CONFIG, backend=VALKEY_CONFIG)
celery.autodiscover_tasks(["app.tasks"])

# Apply safe worker defaults at module import so they affect both:
# 1) Flask app runtime and
# 2) `celery -A app.celery_app worker` startup path.
_default_pool = "solo" if _is_darwin else "prefork"
_selected_pool = os.getenv("QF_CELERY_WORKER_POOL", _default_pool).strip().lower() or _default_pool
_conf_update = {"worker_pool": _selected_pool}
if _selected_pool == "solo":
    _conf_update["worker_concurrency"] = int(os.getenv("QF_CELERY_WORKER_CONCURRENCY", "1"))
celery.conf.update(_conf_update)

QF_TASK_NAMESPACE = "qf"


def configure_forge_celery(app):
    config_payload = dict(app.config)
    # Normalize old Celery key names to new names and drop legacy keys
    # to avoid "Cannot mix new and old setting keys" errors.
    legacy_broker = config_payload.pop("CELERY_BROKER_URL", None)
    legacy_backend = config_payload.pop("CELERY_RESULT_BACKEND", None)
    if legacy_broker and not config_payload.get("broker_url"):
        config_payload["broker_url"] = legacy_broker
    if legacy_backend and not config_payload.get("result_backend"):
        config_payload["result_backend"] = legacy_backend

    celery.conf.update(config_payload)
    # macOS + prefork + native ML libs (torch/sentence-transformers) can segfault.
    # Default to a safer pool for local development unless explicitly overridden.
    default_pool = "solo" if _is_darwin else "prefork"
    selected_pool = os.getenv("QF_CELERY_WORKER_POOL", default_pool).strip().lower() or default_pool
    celery.conf.worker_pool = selected_pool
    if selected_pool == "solo":
        celery.conf.worker_concurrency = int(os.getenv("QF_CELERY_WORKER_CONCURRENCY", "1"))


beat_schedule = dict(getattr(celery.conf, "beat_schedule", {}) or {})
beat_schedule["dispatch-due-skills"] = {
    "task": "qf.skills.dispatch_due",
    "schedule": 60.0,
}
celery.conf.beat_schedule = beat_schedule
