from __future__ import annotations

from typing import Any

from app.celery_app import celery
from app.features.flowforge.repositories import FlowForgeIntegrationRepository
from app.features.flowforge.runtime import FlowForgeRuntimeDispatcher
from app.features.flowforge.runtime.health import record_flowforge_worker_heartbeat
from app.features.flowforge.runtime.human_responses import FlowForgeHumanResponseRuntime
from app.features.flowforge.runtime.notifications import FlowForgeNotificationDispatcher
from app.features.flowforge.runtime.schedules import FlowForgeScheduleRuntime


@celery.task(name="qf.flowforge.dispatch_run")
def dispatch_flowforge_run(workspace_id: str, run_id: int) -> dict[str, Any]:
    record_flowforge_worker_heartbeat(task_name="qf.flowforge.dispatch_run")
    dispatcher = FlowForgeRuntimeDispatcher()
    return dispatcher.dispatch_run(workspace_id=workspace_id, run_id=int(run_id))


@celery.task(name="qf.flowforge.dispatch_due_timeouts")
def dispatch_flowforge_due_timeouts() -> dict[str, Any]:
    record_flowforge_worker_heartbeat(task_name="qf.flowforge.dispatch_due_timeouts")
    dispatcher = FlowForgeHumanResponseRuntime()
    return dispatcher.dispatch_due_timeouts()


@celery.task(name="qf.flowforge.dispatch_notifications")
def dispatch_flowforge_notifications() -> dict[str, Any]:
    record_flowforge_worker_heartbeat(task_name="qf.flowforge.dispatch_notifications")
    dispatcher = FlowForgeNotificationDispatcher()
    return dispatcher.dispatch_pending()


@celery.task(name="qf.flowforge.dispatch_due_schedules")
def dispatch_flowforge_due_schedules(limit: int = 100) -> dict[str, Any]:
    record_flowforge_worker_heartbeat(task_name="qf.flowforge.dispatch_due_schedules")
    runtime = FlowForgeScheduleRuntime()
    return runtime.dispatch_due_schedules(limit=int(limit or 100))


@celery.task(name="qf.flowforge.purge_expired_raw_payloads")
def purge_flowforge_expired_raw_payloads(limit: int = 500) -> dict[str, Any]:
    record_flowforge_worker_heartbeat(task_name="qf.flowforge.purge_expired_raw_payloads")
    purged = FlowForgeIntegrationRepository().purge_expired_raw_payloads(limit=int(limit or 500))
    return {"purged": purged}


def enqueue_flowforge_run_dispatch(*, workspace_id: str, run_id: int) -> None:
    dispatch_flowforge_run.apply_async(args=[workspace_id, int(run_id)])
