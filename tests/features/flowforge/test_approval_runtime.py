from __future__ import annotations

from app.features.flowforge.runtime.approval import FlowForgeApprovalGateExecutor
from app.features.flowforge.service import FlowForgeService


class _RuntimeRepo:
    def __init__(self) -> None:
        self.run = {
            "id": 101,
            "workspace_id": "ws-1",
            "workflow_definition_id": 12,
            "workflow_version_id": 44,
            "status": "waiting",
            "current_node_id": "approve-export",
            "run_context_json": {
                "last_artifact": {
                    "artifact_id": 701,
                    "artifact_key": "run:101:node:transform:map_transform",
                    "artifact_type": "transform",
                    "row_count": 2,
                    "destination": {"destination_key": "ops-export"},
                }
            },
        }
        self.tasks = []
        self.task_updates = []
        self.events = []
        self.status_updates = []
        self.failed = None

    def create_human_task(self, **payload):
        task_id = 401 + len(self.tasks)
        self.tasks.append({**payload, "id": task_id})
        return task_id

    def get_human_task(self, *, workspace_id: str, human_task_id: int):
        if workspace_id != "ws-1" or human_task_id != 401:
            return None
        return {
            "id": human_task_id,
            "workspace_id": workspace_id,
            "run_id": 101,
            "task_type": "approval",
            "status": "waiting",
            "resource_set_id": None,
            "source_record_key": None,
            "response_json": {
                "allowed_actions": ["approve", "decline"],
                "approval": {
                    "dataset_artifact_id": 701,
                    "destination_key": "ops-export",
                },
            },
        }

    def update_human_task_response(self, **payload):
        self.task_updates.append(payload)
        return True

    def append_run_event(self, **payload):
        self.events.append(payload)
        return len(self.events)

    def get_run(self, *, workspace_id: str, run_id: int):
        if workspace_id != "ws-1" or run_id != 101:
            return None
        return dict(self.run)

    def update_run_status(self, **payload):
        self.status_updates.append(payload)
        self.run["status"] = payload["status"]
        self.run["current_node_id"] = payload["current_node_id"]
        return True

    def fail_run(self, **payload):
        self.failed = payload
        self.run["status"] = "failed"
        return True


class _DataMovementRepo:
    def __init__(self) -> None:
        self.audits = []

    def create_data_movement_audit(self, **payload):
        self.audits.append(payload)
        return {**payload, "id": len(self.audits)}


class _WorkflowRepo:
    def __init__(self, *, include_decline_branch: bool = True) -> None:
        self.include_decline_branch = include_decline_branch

    def get_workflow_version(self, *, workspace_id: str, workflow_definition_id: int, version_id: int):
        edges = [
            {"id": "e1", "source": "approve-export", "target": "export", "branch": "approved"},
        ]
        if self.include_decline_branch:
            edges.append({"id": "e2", "source": "approve-export", "target": "stopped", "branch": "declined"})
        return {
            "id": version_id,
            "workspace_id": workspace_id,
            "workflow_definition_id": workflow_definition_id,
            "graph_json": {
                "nodes": [
                    {"id": "approve-export", "type": "approval"},
                    {"id": "export", "type": "export"},
                    {"id": "stopped", "type": "end"},
                ],
                "edges": edges,
            },
        }


def test_approval_gate_executor_creates_waiting_task_and_audit():
    runtime_repo = _RuntimeRepo()
    data_repo = _DataMovementRepo()
    executor = FlowForgeApprovalGateExecutor(
        runtime_repository=runtime_repo,
        data_movement_repository=data_repo,
    )

    result = executor.execute(
        workspace_id="ws-1",
        run_id=101,
        node={
            "id": "approve-export",
            "type": "approval",
            "data": {"approval_group": "ops", "destination_key": "ops-export"},
        },
        run_context=runtime_repo.run["run_context_json"],
    )

    assert result.status == "waiting"
    assert result.event_payload["human_task_id"] == 401
    assert runtime_repo.tasks[0]["task_type"] == "approval"
    assert runtime_repo.tasks[0]["assigned_to_principal_type"] == "group"
    assert runtime_repo.tasks[0]["assigned_to_principal_id"] == "ops"
    assert runtime_repo.tasks[0]["response"]["approval"]["dataset_artifact_id"] == 701
    assert data_repo.audits[0]["action_type"] == "approval"
    assert data_repo.audits[0]["status"] == "waiting"
    assert data_repo.audits[0]["destination_key"] == "ops-export"


def test_approval_task_service_approves_and_resumes_workflow(monkeypatch):
    runtime_repo = _RuntimeRepo()
    data_repo = _DataMovementRepo()
    enqueued = []
    monkeypatch.setattr(
        "app.tasks.flowforge_tasks.enqueue_flowforge_run_dispatch",
        lambda *, workspace_id, run_id: enqueued.append((workspace_id, run_id)),
    )
    service = FlowForgeService(
        runtime_repository=runtime_repo,
        workflow_repository=_WorkflowRepo(),
        data_movement_repository=data_repo,
    )

    result = service.complete_approval_task(
        workspace_id="ws-1",
        human_task_id=401,
        action="approve",
        payload={"decision_note": "Looks right."},
        actor_user_id="user-1",
    )

    assert result["status"] == "approved"
    assert result["runtime"]["status"] == "advanced"
    assert result["runtime"]["to_node_id"] == "export"
    assert runtime_repo.task_updates[0]["status"] == "approved"
    assert runtime_repo.task_updates[0]["response"]["decided_by"] == "user-1"
    assert data_repo.audits[0]["status"] == "approved"
    assert runtime_repo.status_updates[0]["current_node_id"] == "export"
    assert enqueued == [("ws-1", 101)]


def test_approval_task_service_decline_without_branch_fails_run(monkeypatch):
    runtime_repo = _RuntimeRepo()
    data_repo = _DataMovementRepo()
    monkeypatch.setattr(
        "app.tasks.flowforge_tasks.enqueue_flowforge_run_dispatch",
        lambda *, workspace_id, run_id: None,
    )
    service = FlowForgeService(
        runtime_repository=runtime_repo,
        workflow_repository=_WorkflowRepo(include_decline_branch=False),
        data_movement_repository=data_repo,
    )

    result = service.complete_approval_task(
        workspace_id="ws-1",
        human_task_id=401,
        action="decline",
        payload={"decline_reason": "Wrong destination."},
        actor_user_id="user-1",
    )

    assert result["status"] == "declined"
    assert result["runtime"]["status"] == "failed"
    assert result["runtime"]["reason"] == "approval_declined"
    assert runtime_repo.task_updates[0]["status"] == "declined"
    assert data_repo.audits[0]["status"] == "declined"
    assert runtime_repo.failed["error_code"] == "approval_declined"
    assert runtime_repo.events[-1]["event_type"] == "workflow.approval.decline_failed_run"
