from celery import Celery

from app.config import VALKEY_CONFIG

celery = Celery(__name__, broker=VALKEY_CONFIG, backend=VALKEY_CONFIG)
celery.autodiscover_tasks(["app.tasks"])

QF_TASK_NAMESPACE = "qf"


def configure_forge_celery(app):
    celery.conf.update(app.config)

