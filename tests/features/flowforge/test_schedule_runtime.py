from __future__ import annotations

from datetime import datetime, timezone

from app.features.flowforge.runtime.schedules import FlowForgeScheduleRuntime


class _WorkflowRepo:
    def __init__(self, *, rows=None) -> None:
        self.rows = list(rows or [])

    def list_published_schedule_workflow_versions(self, *, limit: int):
        return self.rows[:limit]


class _DataMovementRepo:
    def __init__(self) -> None:
        self.schedule_runs_by_key: dict[str, dict[str, object]] = {}
        self.created_schedule_runs: list[dict[str, object]] = []
        self.updated_schedule_runs: list[dict[str, object]] = []

    def get_schedule_run_by_idempotency(self, *, workspace_id: str, idempotency_key: str):
        del workspace_id
        return self.schedule_runs_by_key.get(idempotency_key)

    def create_schedule_run(self, **payload):
        schedule_run_id = 700 + len(self.created_schedule_runs)
        row = {**payload, "id": schedule_run_id}
        self.created_schedule_runs.append(row)
        self.schedule_runs_by_key[payload["idempotency_key"]] = row
        return schedule_run_id

    def update_schedule_run_status(self, **payload):
        self.updated_schedule_runs.append(payload)
        for row in self.schedule_runs_by_key.values():
            if row["id"] == payload["schedule_run_id"]:
                row["status"] = payload["status"]
                row["run_id"] = payload["run_id"]
                return True
        return False


class _RuntimeRepo:
    def __init__(self) -> None:
        self.runs_by_key: dict[str, dict[str, object]] = {}
        self.created_runs: list[dict[str, object]] = []
        self.events: list[dict[str, object]] = []

    def get_run_by_idempotency(self, *, workspace_id: str, idempotency_key: str):
        del workspace_id
        return self.runs_by_key.get(idempotency_key)

    def create_run(self, **payload):
        run_id = 900 + len(self.created_runs)
        row = {**payload, "id": run_id}
        self.created_runs.append(row)
        self.runs_by_key[payload["idempotency_key"]] = row
        return run_id

    def append_run_event(self, **payload):
        self.events.append(payload)
        return 800 + len(self.events)


def _workflow_row(*, nodes: list[dict[str, object]], workflow_key: str = "daily-provider-refresh"):
    return {
        "workspace_id": "ws-1",
        "workflow_definition_id": 12,
        "workflow_version_id": 44,
        "workflow_key": workflow_key,
        "graph_json": {"nodes": nodes, "edges": []},
        "settings_json": {},
        "published_at": datetime(2026, 5, 5, 8, 0, tzinfo=timezone.utc),
    }


def test_schedule_runtime_creates_one_run_for_due_window_and_enqueues_dispatch():
    data_repo = _DataMovementRepo()
    runtime_repo = _RuntimeRepo()
    enqueued: list[dict[str, object]] = []
    runtime = FlowForgeScheduleRuntime(
        workflow_repository=_WorkflowRepo(
            rows=[
                _workflow_row(
                    nodes=[
                        {
                            "id": "schedule",
                            "type": "schedule_trigger",
                            "data": {"interval_minutes": 60},
                        }
                    ]
                )
            ]
        ),
        data_movement_repository=data_repo,
        runtime_repository=runtime_repo,
        now_provider=lambda: datetime(2026, 5, 6, 12, 34, tzinfo=timezone.utc),
        enqueue_dispatch=lambda **payload: enqueued.append(payload),
    )

    result = runtime.dispatch_due_schedules(limit=25)

    assert result["status"] == "completed"
    assert result["scanned"] == 1
    assert result["due"] == 1
    assert result["created"] == 1
    assert data_repo.created_schedule_runs[0]["trigger_node_id"] == "schedule"
    assert data_repo.created_schedule_runs[0]["window_start"].isoformat() == "2026-05-06T12:00:00"
    assert runtime_repo.created_runs[0]["current_node_id"] == "schedule"
    assert runtime_repo.created_runs[0]["mode"] == "production"
    assert runtime_repo.events[0]["event_type"] == "workflow.run.created"
    assert runtime_repo.events[0]["event_payload"]["trigger_type"] == "schedule_trigger"
    assert enqueued == [{"workspace_id": "ws-1", "run_id": 900}]


def test_schedule_runtime_is_idempotent_for_duplicate_window():
    data_repo = _DataMovementRepo()
    runtime_repo = _RuntimeRepo()
    now = datetime(2026, 5, 6, 12, 34, tzinfo=timezone.utc)
    workflow_repo = _WorkflowRepo(
        rows=[
            _workflow_row(
                nodes=[
                    {
                        "id": "schedule",
                        "type": "schedule_trigger",
                        "data": {"interval_minutes": 60},
                    }
                ]
            )
        ]
    )
    runtime = FlowForgeScheduleRuntime(
        workflow_repository=workflow_repo,
        data_movement_repository=data_repo,
        runtime_repository=runtime_repo,
        now_provider=lambda: now,
        enqueue_dispatch=lambda **payload: None,
    )

    first = runtime.dispatch_due_schedules()
    second = runtime.dispatch_due_schedules()

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["due"] == 1
    assert second["skipped"][0]["reason"] == "duplicate_window"
    assert len(runtime_repo.created_runs) == 1


def test_schedule_runtime_skips_disabled_and_test_ineligible_nodes():
    runtime = FlowForgeScheduleRuntime(
        workflow_repository=_WorkflowRepo(
            rows=[
                _workflow_row(
                    nodes=[
                        {"id": "disabled", "type": "schedule_trigger", "data": {"interval_minutes": 60, "enabled": False}},
                        {"id": "test", "type": "schedule_trigger", "data": {"interval_minutes": 60, "mode": "test"}},
                    ]
                )
            ]
        ),
        data_movement_repository=_DataMovementRepo(),
        runtime_repository=_RuntimeRepo(),
        now_provider=lambda: datetime(2026, 5, 6, 12, 34, tzinfo=timezone.utc),
        enqueue_dispatch=lambda **payload: None,
    )

    result = runtime.dispatch_due_schedules()

    assert result["created"] == 0
    assert [row["reason"] for row in result["skipped"]] == ["disabled", "test_ineligible"]


def test_schedule_runtime_allows_explicit_test_dispatch_and_rrule_windows():
    data_repo = _DataMovementRepo()
    runtime_repo = _RuntimeRepo()
    runtime = FlowForgeScheduleRuntime(
        workflow_repository=_WorkflowRepo(
            rows=[
                _workflow_row(
                    nodes=[
                        {
                            "id": "daily",
                            "type": "schedule_trigger",
                            "data": {
                                "rrule": "FREQ=DAILY;INTERVAL=1",
                                "start_at": "2026-05-05T08:00:00+00:00",
                                "mode": "test",
                                "allow_test_dispatch": True,
                            },
                        }
                    ]
                )
            ]
        ),
        data_movement_repository=data_repo,
        runtime_repository=runtime_repo,
        now_provider=lambda: datetime(2026, 5, 6, 9, 15, tzinfo=timezone.utc),
        enqueue_dispatch=lambda **payload: None,
    )

    result = runtime.dispatch_due_schedules()

    assert result["created"] == 1
    assert runtime_repo.created_runs[0]["mode"] == "test"
    assert data_repo.created_schedule_runs[0]["window_start"].isoformat() == "2026-05-06T08:00:00"
    assert data_repo.created_schedule_runs[0]["window_end"].isoformat() == "2026-05-07T08:00:00"
