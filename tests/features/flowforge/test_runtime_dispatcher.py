from __future__ import annotations

from app.features.flowforge.runtime.dispatcher import FlowForgeRuntimeDispatcher
from app.features.flowforge.runtime.node_executor import NodeExecutionResult


class _RuntimeRepo:
    def __init__(self) -> None:
        self.run = {
            "id": 101,
            "workspace_id": "ws-1",
            "workflow_definition_id": 12,
            "workflow_version_id": 44,
            "status": "waiting",
            "current_node_id": "intake",
            "run_context_json": {"intake": {"fields": {"caseType": "new"}}},
        }
        self.events_by_key: dict[str, dict[str, object]] = {}
        self.status_updates: list[dict[str, object]] = []
        self.completed = None
        self.failed = None
        self.matching_evaluations: list[dict[str, object]] = []
        self.matching_candidates: list[dict[str, object]] = []
        self.context_updates: list[dict[str, object]] = []
        self.human_tasks: list[dict[str, object]] = []
        self.tokens: list[dict[str, object]] = []
        self.notifications: list[dict[str, object]] = []

    def get_run(self, *, workspace_id: str, run_id: int):
        if workspace_id != "ws-1" or run_id != 101:
            return None
        return dict(self.run)

    def update_run_status(self, **payload):
        self.status_updates.append(payload)
        self.run["status"] = payload["status"]
        self.run["current_node_id"] = payload["current_node_id"]
        return True

    def complete_run(self, **payload):
        self.completed = payload
        self.run["status"] = "completed"
        self.run["current_node_id"] = payload["current_node_id"]
        return True

    def fail_run(self, **payload):
        self.failed = payload
        self.run["status"] = "failed"
        self.run["current_node_id"] = payload["current_node_id"]
        return True

    def get_run_event_by_idempotency(self, *, workspace_id: str, idempotency_key: str):
        del workspace_id
        return self.events_by_key.get(idempotency_key)

    def append_run_event(self, **payload):
        event_id = len(self.events_by_key) + 1
        event = {**payload, "id": event_id}
        self.events_by_key[payload["idempotency_key"]] = event
        return event_id

    def create_matching_evaluation(self, **payload):
        evaluation_id = 700 + len(self.matching_evaluations)
        self.matching_evaluations.append({**payload, "id": evaluation_id})
        return evaluation_id

    def create_matching_evaluation_candidate(self, **payload):
        candidate_id = 800 + len(self.matching_candidates)
        self.matching_candidates.append({**payload, "id": candidate_id})
        return candidate_id

    def update_run_context(self, **payload):
        self.context_updates.append(payload)
        self.run["run_context_json"] = payload["run_context"]
        return True

    def create_human_task(self, **payload):
        task_id = 900 + len(self.human_tasks)
        self.human_tasks.append({**payload, "id": task_id})
        return task_id

    def create_signed_action_token(self, **payload):
        token_id = 1000 + len(self.tokens)
        self.tokens.append({**payload, "id": token_id})
        return token_id

    def create_notification(self, **payload):
        notification_id = 1100 + len(self.notifications)
        self.notifications.append({**payload, "id": notification_id})
        return notification_id


class _DataMovementRepo:
    def __init__(self) -> None:
        self.audits = []

    def create_data_movement_audit(self, **payload):
        self.audits.append(payload)
        return {**payload, "id": len(self.audits)}


class _WorkflowRepo:
    def __init__(self, graph: dict[str, object] | None = None) -> None:
        self.graph = graph or {
            "nodes": [
                {"id": "intake", "type": "intake"},
                {"id": "triage", "type": "decision"},
                {"id": "notify", "type": "notification"},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"id": "e1", "source": "intake", "target": "triage"},
                {"id": "e2", "source": "triage", "target": "notify"},
                {"id": "e3", "source": "notify", "target": "done"},
            ],
        }

    def get_workflow_version(
        self, *, workspace_id: str, workflow_definition_id: int, version_id: int
    ):
        assert workspace_id == "ws-1"
        assert workflow_definition_id == 12
        assert version_id == 44
        return {
            "id": 44,
            "workspace_id": workspace_id,
            "workflow_definition_id": workflow_definition_id,
            "graph_json": self.graph,
            "validation_status": "valid",
        }


def test_dispatcher_advances_simple_run_to_completion_with_idempotent_events():
    runtime_repo = _RuntimeRepo()
    dispatcher = FlowForgeRuntimeDispatcher(
        runtime_repository=runtime_repo,
        workflow_repository=_WorkflowRepo(),
    )

    result = dispatcher.dispatch_run(workspace_id="ws-1", run_id=101)
    duplicate = dispatcher.dispatch_run(workspace_id="ws-1", run_id=101)

    assert result["status"] == "completed"
    assert result["visited_node_ids"] == ["intake", "triage", "notify", "done"]
    assert runtime_repo.completed["run_id"] == 101
    assert runtime_repo.completed["current_node_id"] == "done"
    assert len(runtime_repo.events_by_key) == 10
    assert duplicate["status"] == "skipped"
    assert duplicate["reason"] == "terminal_status"
    assert len(runtime_repo.events_by_key) == 10


def test_dispatcher_pauses_wait_node_without_completing_run():
    runtime_repo = _RuntimeRepo()
    dispatcher = FlowForgeRuntimeDispatcher(
        runtime_repository=runtime_repo,
        workflow_repository=_WorkflowRepo(
            graph={
                "nodes": [
                    {"id": "intake", "type": "intake"},
                    {"id": "wait-for-response", "type": "wait"},
                    {"id": "done", "type": "end"},
                ],
                "edges": [
                    {"id": "e1", "source": "intake", "target": "wait-for-response"},
                    {"id": "e2", "source": "wait-for-response", "target": "done"},
                ],
            }
        ),
    )

    result = dispatcher.dispatch_run(workspace_id="ws-1", run_id=101)

    assert result["status"] == "waiting"
    assert result["visited_node_ids"] == ["intake", "wait-for-response"]
    assert runtime_repo.completed is None
    assert runtime_repo.run["current_node_id"] == "wait-for-response"


def test_dispatcher_supports_assignment_iterator_and_event_capture_nodes():
    runtime_repo = _RuntimeRepo()
    dispatcher = FlowForgeRuntimeDispatcher(
        runtime_repository=runtime_repo,
        workflow_repository=_WorkflowRepo(
            graph={
                "nodes": [
                    {"id": "capture", "type": "event_capture"},
                    {"id": "next", "type": "iterator"},
                    {"id": "assign", "type": "assignment"},
                ],
                "edges": [
                    {"id": "e1", "source": "capture", "target": "next"},
                    {"id": "e2", "source": "next", "target": "assign"},
                ],
            }
        ),
    )
    runtime_repo.run["current_node_id"] = "capture"

    result = dispatcher.dispatch_run(workspace_id="ws-1", run_id=101)

    assert result["status"] == "completed"
    assert result["visited_node_ids"] == ["capture", "next", "assign"]
    assert runtime_repo.completed["current_node_id"] == "assign"


def test_dispatcher_advances_data_movement_nodes_and_waits_for_approval():
    runtime_repo = _RuntimeRepo()
    data_movement_repo = _DataMovementRepo()

    class _QueryExtractExecutor:
        def execute(
            self,
            *,
            workspace_id: str,
            run_id: int,
            node: dict,
            outgoing_edges: list,
            run_context: dict,
        ):
            del workspace_id, run_id, node, run_context
            return NodeExecutionResult(
                status="advance",
                next_node_id="transform",
                event_payload={
                    "node_type": "query_extract",
                    "data_movement": {
                        "source": {"saved_query_id": "saved-query-1"},
                        "artifact": {"artifact_id": 501},
                    },
                },
                run_context_update={"artifacts": {"extract": {"artifact_id": 501}}},
            )

    class _MapTransformExecutor:
        def execute(
            self,
            *,
            workspace_id: str,
            run_id: int,
            node: dict,
            outgoing_edges: list,
            run_context: dict,
        ):
            del workspace_id, run_id, node, outgoing_edges, run_context
            return NodeExecutionResult(
                status="advance",
                next_node_id="export",
                event_payload={
                    "node_type": "map_transform",
                    "data_movement": {
                        "artifact": {"artifact_id": 601},
                        "validation_summary": {"rejected_row_count": 1},
                    },
                },
                run_context_update={
                    "artifacts": {"transform": {"artifact_id": 601}},
                    "last_artifact": {"artifact_id": 601},
                },
            )

    class _ExportExecutor:
        def execute(
            self,
            *,
            workspace_id: str,
            run_id: int,
            node: dict,
            outgoing_edges: list,
            run_context: dict,
        ):
            del workspace_id, run_id, node, outgoing_edges, run_context
            return NodeExecutionResult(
                status="advance",
                next_node_id="approve",
                event_payload={
                    "node_type": "export",
                    "data_movement": {
                        "destination": {"destination_key": "ops-sftp"},
                        "artifact": {"artifact_id": 701},
                    },
                },
                run_context_update={
                    "artifacts": {"export": {"artifact_id": 701}},
                    "last_artifact": {"artifact_id": 701},
                },
            )

    dispatcher = FlowForgeRuntimeDispatcher(
        runtime_repository=runtime_repo,
        workflow_repository=_WorkflowRepo(
            graph={
                "nodes": [
                    {
                        "id": "schedule",
                        "type": "schedule_trigger",
                        "data": {"rrule": "FREQ=DAILY;INTERVAL=1"},
                    },
                    {
                        "id": "extract",
                        "type": "query_extract",
                        "data": {"saved_query_id": "saved-query-1"},
                    },
                    {
                        "id": "transform",
                        "type": "map_transform",
                        "data": {"field_mapping": {"email": "patient_email"}},
                    },
                    {
                        "id": "export",
                        "type": "export",
                        "data": {"destination_key": "ops-sftp"},
                    },
                    {
                        "id": "approve",
                        "type": "approval",
                        "data": {"approval_group": "ops"},
                    },
                    {"id": "done", "type": "end"},
                ],
                "edges": [
                    {"id": "e1", "source": "schedule", "target": "extract"},
                    {"id": "e2", "source": "extract", "target": "transform"},
                    {"id": "e3", "source": "transform", "target": "export"},
                    {"id": "e4", "source": "export", "target": "approve"},
                    {"id": "e5", "source": "approve", "target": "done"},
                ],
            }
        ),
        query_extract_executor=_QueryExtractExecutor(),
        map_transform_executor=_MapTransformExecutor(),
        export_executor=_ExportExecutor(),
        data_movement_repository=data_movement_repo,
    )
    runtime_repo.run["current_node_id"] = "schedule"

    result = dispatcher.dispatch_run(workspace_id="ws-1", run_id=101)

    assert result["status"] == "waiting"
    assert result["visited_node_ids"] == [
        "schedule",
        "extract",
        "transform",
        "export",
        "approve",
    ]
    assert runtime_repo.run["current_node_id"] == "approve"
    assert runtime_repo.human_tasks[0]["task_type"] == "approval"
    assert runtime_repo.human_tasks[0]["assigned_to_principal_id"] == "ops"
    assert data_movement_repo.audits[0]["action_type"] == "approval"
    assert data_movement_repo.audits[0]["status"] == "waiting"
    completed_events = [
        event
        for event in runtime_repo.events_by_key.values()
        if event["event_type"] == "workflow.node.completed"
    ]
    assert (
        completed_events[0]["event_payload"]["trigger"]["trigger_type"]
        == "schedule_trigger"
    )
    assert (
        completed_events[1]["event_payload"]["data_movement"]["source"][
            "saved_query_id"
        ]
        == "saved-query-1"
    )
    assert (
        completed_events[2]["event_payload"]["data_movement"]["validation_summary"][
            "rejected_row_count"
        ]
        == 1
    )
    assert (
        completed_events[3]["event_payload"]["data_movement"]["destination"][
            "destination_key"
        ]
        == "ops-sftp"
    )
    assert (
        runtime_repo.context_updates[0]["run_context"]["artifacts"]["extract"][
            "artifact_id"
        ]
        == 501
    )
    assert (
        runtime_repo.context_updates[1]["run_context"]["artifacts"]["transform"][
            "artifact_id"
        ]
        == 601
    )
    assert (
        runtime_repo.context_updates[2]["run_context"]["artifacts"]["export"][
            "artifact_id"
        ]
        == 701
    )


def test_dispatcher_routes_import_nodes_through_import_executor():
    runtime_repo = _RuntimeRepo()

    class _ImportExecutor:
        def execute(
            self,
            *,
            workspace_id: str,
            run_id: int,
            node: dict,
            outgoing_edges: list,
            run_context: dict,
        ):
            del workspace_id, run_id, node, outgoing_edges, run_context
            return NodeExecutionResult(
                status="advance",
                next_node_id="done",
                event_payload={
                    "node_type": "import",
                    "data_movement": {
                        "artifact": {"artifact_id": 701},
                        "activation": {"resource_set_id": 20},
                    },
                },
                run_context_update={
                    "artifacts": {"import": {"artifact_id": 701}},
                    "last_artifact": {"artifact_id": 701},
                },
            )

    dispatcher = FlowForgeRuntimeDispatcher(
        runtime_repository=runtime_repo,
        workflow_repository=_WorkflowRepo(
            graph={
                "nodes": [
                    {"id": "import", "type": "import"},
                    {"id": "done", "type": "end"},
                ],
                "edges": [{"id": "e1", "source": "import", "target": "done"}],
            }
        ),
        import_executor=_ImportExecutor(),
    )
    runtime_repo.run["current_node_id"] = "import"

    result = dispatcher.dispatch_run(workspace_id="ws-1", run_id=101)

    assert result["status"] == "completed"
    assert result["visited_node_ids"] == ["import", "done"]
    assert (
        runtime_repo.context_updates[0]["run_context"]["artifacts"]["import"][
            "artifact_id"
        ]
        == 701
    )


def test_dispatcher_executes_matching_node_and_persists_candidate_results():
    runtime_repo = _RuntimeRepo()
    runtime_repo.run["run_context_json"] = {
        "intake": {"fields": {"caseType": "new"}},
        "communication_context": {
            "intake": {
                "requested_service": "Anxiety therapy",
                "preferred_days": "Monday",
            }
        },
        "communication_fields": ["intake.requested_service", "intake.preferred_days"],
    }

    class _MatchingRepo:
        def get_policy_version(self, *, workspace_id: str, version_id: int):
            assert workspace_id == "ws-1"
            assert version_id == 77
            return {
                "id": 77,
                "workspace_id": workspace_id,
                "resource_set_id": 20,
                "version_status": "published",
                "policy_json": {
                    "version": 1,
                    "eligibility": [
                        {
                            "field": "effective_status",
                            "operator": "equals",
                            "value": "active",
                        }
                    ],
                    "scoring": [
                        {
                            "field": "languages",
                            "operator": "contains",
                            "value": "Spanish",
                            "weight": 5,
                        }
                    ],
                },
            }

    class _ResourceRepo:
        def __init__(self) -> None:
            self.offered = []

        def get_resource_set(self, *, workspace_id: str, resource_set_id: int):
            assert workspace_id == "ws-1"
            assert resource_set_id == 20
            return {"id": 20, "active_snapshot_batch_id": 30}

        def list_snapshot_records_for_batch(
            self,
            *,
            workspace_id: str,
            resource_set_id: int,
            snapshot_batch_id: int,
            limit: int,
        ):
            assert workspace_id == "ws-1"
            assert resource_set_id == 20
            assert snapshot_batch_id == 30
            assert limit == 5000
            return [
                {
                    "source_record_key": "resource-1",
                    "display_name": "Jane Resource",
                    "primary_email": "jane@example.com",
                    "effective_status": "active",
                    "attributes_json": {"languages": ["Spanish"]},
                },
                {
                    "source_record_key": "resource-2",
                    "display_name": "Inactive Resource",
                    "effective_status": "inactive",
                    "attributes_json": {"languages": ["Spanish"]},
                },
            ]

        def mark_resource_offered(self, **payload):
            self.offered.append(payload)
            return True

    resource_repo = _ResourceRepo()
    dispatcher = FlowForgeRuntimeDispatcher(
        runtime_repository=runtime_repo,
        workflow_repository=_WorkflowRepo(
            graph={
                "nodes": [
                    {"id": "intake", "type": "intake"},
                    {
                        "id": "match",
                        "type": "matching",
                        "data": {
                            "matching_policy_version_id": 77,
                        },
                    },
                    {
                        "id": "offer",
                        "type": "human_task",
                        "data": {
                            "communication_template_key": "flowforge.custom_task",
                            "timeout_minutes": 60,
                        },
                    },
                    {"id": "done", "type": "end"},
                    {"id": "no-match", "type": "end"},
                ],
                "edges": [
                    {"id": "e1", "source": "intake", "target": "match"},
                    {
                        "id": "e2",
                        "source": "match",
                        "target": "offer",
                        "branch": "matched",
                    },
                    {"id": "e4", "source": "offer", "target": "done"},
                    {
                        "id": "e3",
                        "source": "match",
                        "target": "no-match",
                        "branch": "no_match",
                    },
                ],
            }
        ),
        matching_repository=_MatchingRepo(),
        resource_repository=resource_repo,
    )

    result = dispatcher.dispatch_run(workspace_id="ws-1", run_id=101)

    assert result["status"] == "waiting"
    assert result["visited_node_ids"] == ["intake", "match", "offer"]
    assert (
        runtime_repo.matching_evaluations[0]["selected_source_record_key"]
        == "resource-1"
    )
    assert runtime_repo.matching_evaluations[0]["snapshot_batch_id"] == 30
    assert len(runtime_repo.matching_candidates) == 2
    assert runtime_repo.matching_candidates[0]["selected"] is True
    assert runtime_repo.context_updates[0]["run_context"]["flowforge_matching"][
        "candidate_keys"
    ] == ["resource-1"]
    assert (
        runtime_repo.context_updates[0]["run_context"]["flowforge_matching"][
            "communication_template_key"
        ]
        == "flowforge.custom_task"
    )
    assert (
        runtime_repo.context_updates[0]["run_context"]["flowforge_matching"][
            "offer_timeout_minutes"
        ]
        == 60
    )
    assert runtime_repo.human_tasks[0]["source_record_key"] == "resource-1"
    assert (
        runtime_repo.human_tasks[0]["idempotency_key"]
        == "run:101:offer:resource-1:task"
    )
    assert runtime_repo.tokens[0]["allowed_actions"] == ["accept", "decline"]
    assert runtime_repo.notifications[0]["recipient"] == "jane@example.com"
    assert runtime_repo.notifications[0]["template_key"] == "flowforge.custom_task"
    assert runtime_repo.notifications[0]["payload_summary"]["intake"] == {
        "requested_service": "Anxiety therapy",
        "preferred_days": "Monday",
    }
    assert runtime_repo.notifications[0]["payload_summary"]["selected_resource"]["display_name"] == "Jane Resource"
    assert "action_url" in runtime_repo.notifications[0]["payload_summary"]
    action_url = runtime_repo.notifications[0]["payload_summary"]["action_url"]
    assert runtime_repo.notifications[0]["payload_summary"]["action_urls"] == {
        "open_task": action_url,
        "accept": f"{action_url}?action=accept",
        "decline": f"{action_url}?action=decline",
    }
    assert resource_repo.offered[0]["source_record_key"] == "resource-1"


def test_dispatcher_marks_run_failed_when_workflow_version_is_missing():
    runtime_repo = _RuntimeRepo()

    class _MissingWorkflowRepo:
        def get_workflow_version(self, **kwargs):
            return None

    dispatcher = FlowForgeRuntimeDispatcher(
        runtime_repository=runtime_repo,
        workflow_repository=_MissingWorkflowRepo(),
    )

    result = dispatcher.dispatch_run(workspace_id="ws-1", run_id=101)

    assert result["status"] == "failed"
    assert runtime_repo.failed["error_code"] == "workflow_version_missing"
    assert runtime_repo.failed["current_node_id"] == "intake"


def test_dispatcher_marks_run_failed_for_unknown_node_type():
    runtime_repo = _RuntimeRepo()
    dispatcher = FlowForgeRuntimeDispatcher(
        runtime_repository=runtime_repo,
        workflow_repository=_WorkflowRepo(
            graph={
                "nodes": [{"id": "intake", "type": "custom_unsupported"}],
                "edges": [],
            }
        ),
    )

    result = dispatcher.dispatch_run(workspace_id="ws-1", run_id=101)

    assert result["status"] == "failed"
    assert runtime_repo.failed["error_code"] == "node_execution_failed"
    assert "Unsupported FlowForge node type" in runtime_repo.failed["error_message"]
