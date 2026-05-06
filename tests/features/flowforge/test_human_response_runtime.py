from __future__ import annotations

from app.features.flowforge.runtime.human_responses import FlowForgeHumanResponseRuntime


class _RuntimeRepo:
    def __init__(self) -> None:
        self.run = {
            "id": 101,
            "workspace_id": "ws-1",
            "workflow_definition_id": 12,
            "workflow_version_id": 44,
            "status": "waiting",
            "current_node_id": "wait-for-response",
            "run_context_json": {
                "flowforge_matching": {
                    "resource_set_id": 20,
                    "snapshot_batch_id": 30,
                    "candidate_keys": ["resource-1", "resource-2"],
                    "current_candidate_index": 0,
                    "exhausted_candidate_keys": [],
                    "offer_timeout_minutes": 90,
                    "communication_template_key": "flowforge.next_task",
                }
            },
        }
        self.status_updates = []
        self.events = []
        self.task_updates = []
        self.context_updates = []
        self.human_tasks = []
        self.tokens = []
        self.notifications = []
        self.assignments = []
        self.due_tasks = [
            {
                "id": 301,
                "workspace_id": "ws-1",
                "run_id": 101,
                "task_type": "offer",
                "status": "pending",
                "resource_set_id": 20,
                "source_record_key": "resource-1",
            }
        ]

    def get_run(self, *, workspace_id: str, run_id: int):
        if workspace_id != "ws-1" or run_id != 101:
            return None
        return dict(self.run)

    def update_run_status(self, **payload):
        self.status_updates.append(payload)
        self.run["status"] = payload["status"]
        self.run["current_node_id"] = payload["current_node_id"]
        return True

    def append_run_event(self, **payload):
        self.events.append(payload)
        return len(self.events)

    def list_due_human_tasks(self, *, limit: int):
        assert limit == 50
        return list(self.due_tasks)

    def update_human_task_response(self, **payload):
        self.task_updates.append(payload)
        return True

    def update_run_context(self, **payload):
        self.context_updates.append(payload)
        self.run["run_context_json"] = payload["run_context"]
        return True

    def create_human_task(self, **payload):
        task_id = 900 + len(self.human_tasks)
        self.human_tasks.append({**payload, "id": task_id})
        return task_id

    def create_signed_action_token(self, **payload):
        self.tokens.append(payload)
        return 1000 + len(self.tokens)

    def create_notification(self, **payload):
        self.notifications.append(payload)
        return 1100 + len(self.notifications)

    def create_assignment(self, **payload):
        self.assignments.append(payload)
        return 1200 + len(self.assignments)


class _ResourceRepo:
    def __init__(self) -> None:
        self.assigned = []
        self.declined = []
        self.offered = []

    def get_snapshot_record(self, *, workspace_id: str, resource_set_id: int, snapshot_batch_id: int, source_record_key: str):
        assert workspace_id == "ws-1"
        assert resource_set_id == 20
        assert snapshot_batch_id == 30
        if source_record_key != "resource-2":
            return None
        return {
            "source_record_key": "resource-2",
            "display_name": "Next Resource",
            "primary_email": "next@example.com",
        }

    def mark_resource_assigned(self, **payload):
        self.assigned.append(payload)
        return True

    def mark_resource_declined(self, **payload):
        self.declined.append(payload)
        return True

    def mark_resource_offered(self, **payload):
        self.offered.append(payload)
        return True


class _WorkflowRepo:
    def get_workflow_version(self, *, workspace_id: str, workflow_definition_id: int, version_id: int):
        assert workspace_id == "ws-1"
        assert workflow_definition_id == 12
        assert version_id == 44
        return {
            "id": 44,
            "graph_json": {
                "nodes": [
                    {"id": "wait-for-response", "type": "wait"},
                    {"id": "assign", "type": "end"},
                    {"id": "next-candidate", "type": "end"},
                    {"id": "timeout-branch", "type": "end"},
                    {"id": "no-match", "type": "end"},
                ],
                "edges": [
                    {"id": "e1", "source": "wait-for-response", "target": "assign", "branch": "accept"},
                    {"id": "e2", "source": "wait-for-response", "target": "next-candidate", "branch": "decline"},
                    {"id": "e3", "source": "wait-for-response", "target": "timeout-branch", "branch": "timeout"},
                    {"id": "e4", "source": "wait-for-response", "target": "no-match", "branch": "no_match"},
                ],
            },
        }


def test_human_response_runtime_advances_wait_node_and_enqueues_dispatch():
    repo = _RuntimeRepo()
    enqueued = []
    runtime = FlowForgeHumanResponseRuntime(
        runtime_repository=repo,
        workflow_repository=_WorkflowRepo(),
        resource_repository=_ResourceRepo(),
        enqueue_dispatch=lambda workspace_id, run_id: enqueued.append((workspace_id, run_id)),
    )

    result = runtime.advance_after_human_action(
        workspace_id="ws-1",
        run_id=101,
        action="accept",
        human_task_id=301,
        resource_set_id=20,
        source_record_key="resource-1",
    )

    assert result["status"] == "advanced"
    assert result["to_node_id"] == "assign"
    assert result["assignment_id"] == 1201
    assert repo.status_updates[0]["status"] == "waiting"
    assert repo.status_updates[0]["current_node_id"] == "assign"
    assert repo.events[0]["event_type"] == "workflow.human_response.advance"
    assert repo.assignments[0]["source_record_key"] == "resource-1"
    assert repo.assignments[0]["idempotency_key"] == "run:101:assignment:resource-1"
    assert enqueued == [("ws-1", 101)]


def test_human_response_runtime_approval_action_uses_approved_or_unbranched_edge():
    repo = _RuntimeRepo()
    enqueued = []
    runtime = FlowForgeHumanResponseRuntime(
        runtime_repository=repo,
        workflow_repository=_WorkflowRepo(),
        resource_repository=_ResourceRepo(),
        enqueue_dispatch=lambda workspace_id, run_id: enqueued.append((workspace_id, run_id)),
    )

    result = runtime.advance_after_human_action(
        workspace_id="ws-1",
        run_id=101,
        action="approve",
        human_task_id=301,
    )

    assert result["status"] == "advanced"
    assert result["to_node_id"] == "assign"
    assert repo.status_updates[0]["current_node_id"] == "assign"
    assert enqueued == [("ws-1", 101)]


def test_human_response_runtime_decline_creates_next_candidate_offer_without_advancing_branch():
    repo = _RuntimeRepo()
    resource_repo = _ResourceRepo()
    enqueued = []
    runtime = FlowForgeHumanResponseRuntime(
        runtime_repository=repo,
        workflow_repository=_WorkflowRepo(),
        resource_repository=resource_repo,
        enqueue_dispatch=lambda workspace_id, run_id: enqueued.append((workspace_id, run_id)),
    )

    result = runtime.advance_after_human_action(
        workspace_id="ws-1",
        run_id=101,
        action="decline",
        human_task_id=301,
        resource_set_id=20,
        source_record_key="resource-1",
    )

    assert result["status"] == "next_candidate_offered"
    assert result["source_record_key"] == "resource-2"
    assert repo.context_updates[0]["run_context"]["flowforge_matching"]["current_candidate_index"] == 1
    assert repo.context_updates[0]["run_context"]["flowforge_matching"]["exhausted_candidate_keys"] == ["resource-1"]
    assert repo.human_tasks[0]["source_record_key"] == "resource-2"
    assert repo.human_tasks[0]["idempotency_key"] == "run:101:offer:resource-2:task"
    assert repo.notifications[0]["template_key"] == "flowforge.next_task"
    assert repo.notifications[0]["recipient"] == "next@example.com"
    assert resource_repo.declined[0]["source_record_key"] == "resource-1"
    assert resource_repo.offered[0]["source_record_key"] == "resource-2"
    assert enqueued == []


def test_human_response_runtime_decline_advances_to_no_match_when_candidate_pool_exhausted():
    repo = _RuntimeRepo()
    repo.run["run_context_json"]["flowforge_matching"]["candidate_keys"] = ["resource-1"]
    enqueued = []
    runtime = FlowForgeHumanResponseRuntime(
        runtime_repository=repo,
        workflow_repository=_WorkflowRepo(),
        resource_repository=_ResourceRepo(),
        enqueue_dispatch=lambda workspace_id, run_id: enqueued.append((workspace_id, run_id)),
    )

    result = runtime.advance_after_human_action(
        workspace_id="ws-1",
        run_id=101,
        action="decline",
        human_task_id=301,
        resource_set_id=20,
        source_record_key="resource-1",
    )

    assert result["status"] == "advanced"
    assert result["to_node_id"] == "no-match"
    assert repo.context_updates[0]["run_context"]["flowforge_matching"]["selected_source_record_key"] is None
    assert repo.status_updates[0]["current_node_id"] == "no-match"
    assert enqueued == [("ws-1", 101)]


def test_human_response_runtime_marks_due_tasks_timed_out_and_advances():
    repo = _RuntimeRepo()
    enqueued = []
    runtime = FlowForgeHumanResponseRuntime(
        runtime_repository=repo,
        workflow_repository=_WorkflowRepo(),
        resource_repository=_ResourceRepo(),
        enqueue_dispatch=lambda workspace_id, run_id: enqueued.append((workspace_id, run_id)),
    )

    result = runtime.dispatch_due_timeouts(limit=50)

    assert result == {"status": "completed", "processed": 1, "advanced": 0}
    assert repo.task_updates[0]["status"] == "timed_out"
    assert repo.task_updates[0]["response"] == {"action": "timeout", "timeout": True}
    assert repo.events[0]["event_type"] == "workflow.human_task.timed_out"
    assert repo.human_tasks[0]["source_record_key"] == "resource-2"
    assert enqueued == []
