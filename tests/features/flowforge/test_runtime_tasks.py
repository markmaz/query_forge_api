from __future__ import annotations

from app.tasks.flowforge_tasks import (
    dispatch_flowforge_due_schedules,
    dispatch_flowforge_due_timeouts,
    dispatch_flowforge_notifications,
    dispatch_flowforge_run,
)


def test_dispatch_flowforge_run_task_delegates_to_runtime_dispatcher(monkeypatch):
    observed: dict[str, object] = {}

    class _Dispatcher:
        def dispatch_run(self, *, workspace_id: str, run_id: int):
            observed["workspace_id"] = workspace_id
            observed["run_id"] = run_id
            return {"status": "completed", "run_id": run_id}

    monkeypatch.setattr("app.tasks.flowforge_tasks.FlowForgeRuntimeDispatcher", lambda: _Dispatcher())

    result = dispatch_flowforge_run("ws-1", 101)

    assert result == {"status": "completed", "run_id": 101}
    assert observed == {"workspace_id": "ws-1", "run_id": 101}


def test_dispatch_flowforge_notifications_task_delegates_to_notification_dispatcher(monkeypatch):
    observed: dict[str, object] = {}

    class _Dispatcher:
        def dispatch_pending(self):
            observed["called"] = True
            return {"status": "completed", "processed": 1, "sent": 1, "failed": 0}

    monkeypatch.setattr("app.tasks.flowforge_tasks.FlowForgeNotificationDispatcher", lambda: _Dispatcher())

    result = dispatch_flowforge_notifications()

    assert result == {"status": "completed", "processed": 1, "sent": 1, "failed": 0}
    assert observed == {"called": True}


def test_dispatch_flowforge_due_timeouts_task_delegates_to_human_response_runtime(monkeypatch):
    observed: dict[str, object] = {}

    class _Runtime:
        def dispatch_due_timeouts(self):
            observed["called"] = True
            return {"status": "completed", "processed": 1, "advanced": 1}

    monkeypatch.setattr("app.tasks.flowforge_tasks.FlowForgeHumanResponseRuntime", lambda: _Runtime())

    result = dispatch_flowforge_due_timeouts()

    assert result == {"status": "completed", "processed": 1, "advanced": 1}
    assert observed == {"called": True}


def test_dispatch_flowforge_due_schedules_task_delegates_to_schedule_runtime(monkeypatch):
    observed: dict[str, object] = {}

    class _Runtime:
        def dispatch_due_schedules(self, *, limit: int):
            observed["limit"] = limit
            return {"status": "completed", "scanned": 1, "due": 1, "created": 1, "skipped": []}

    monkeypatch.setattr("app.tasks.flowforge_tasks.FlowForgeScheduleRuntime", lambda: _Runtime())

    result = dispatch_flowforge_due_schedules(limit=25)

    assert result == {"status": "completed", "scanned": 1, "due": 1, "created": 1, "skipped": []}
    assert observed == {"limit": 25}
