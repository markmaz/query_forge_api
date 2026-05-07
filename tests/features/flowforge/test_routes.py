from __future__ import annotations

from typing import Dict

import app.decorators.rbac as rbac_decorators
import app.decorators.security as security
import app.features.flowforge.routes as flowforge_routes
import app.features.flowforge.routes.workflows as flowforge_workflow_routes
from app.features.flowforge.service import FlowForgeService
import app.services.rbac_service as rbac_service


def _headers(monkeypatch, *, roles: set[str] | None = None, feature_enabled: bool = True) -> Dict[str, str]:
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "username": "user-1", "is_admin": False},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(
        rbac_service,
        "get_effective_roles",
        lambda user_id, workspace_id=None: set(roles or {"flowforge:user"}),
    )
    monkeypatch.setattr(rbac_decorators, "workspace_has_feature", lambda workspace_id, feature_key: feature_enabled)
    return {"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-1"}


class _IntegrationCatalogRepo:
    def list_integration_configs(self, *, workspace_id: str, provider: str | None = None):
        del provider
        return [
            {
                "id": 10,
                "workspace_id": workspace_id,
                "provider": "jotform",
                "integration_key": "intake-form",
                "display_name": "Intake Form",
                "external_form_id": "form-1",
                "enabled": True,
                "mode": "test",
                "webhook_public_id": "ffj_public",
                "settings_json": {
                    "source_events": [{"event_key": "intake_submitted", "display_name": "Intake Submitted"}],
                    "source_fields": [{"path": "serviceRequested", "label": "Requested Service", "type": "text"}],
                },
            }
        ]


def test_flowforge_workflow_list_returns_persisted_workflows(client, monkeypatch):
    service = _RunService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)
    resp = client.get("/api/v1/flowforge/workflows", headers=_headers(monkeypatch))

    assert resp.status_code == 200
    assert resp.json[0]["id"] == "42"
    assert resp.json[0]["graph"]["nodes"][0]["id"] == "intake"


def test_flowforge_workflow_detail_returns_404_for_unknown_workflow(client, monkeypatch):
    resp = client.get("/api/v1/flowforge/workflows/unknown", headers=_headers(monkeypatch))

    assert resp.status_code == 404


def test_flowforge_validation_returns_loop_warning(client, monkeypatch):
    service = FlowForgeService(integration_repository=_IntegrationCatalogRepo())
    monkeypatch.setattr(flowforge_workflow_routes, "_service", lambda: service)
    payload = {
        "graph": {
            "nodes": [
                {
                    "id": "a",
                    "type": "intake",
                    "label": "A",
                    "position": {"x": 0, "y": 0},
                    "data": {"source": "intake-form", "event": "intake_submitted"},
                },
                {"id": "b", "type": "decision", "label": "B", "position": {"x": 1, "y": 1}, "data": {}},
            ],
            "edges": [
                {"id": "a-b", "source": "a", "target": "b"},
                {"id": "b-a", "source": "b", "target": "a"},
            ],
        }
    }

    resp = client.post(
        "/api/v1/flowforge/workflows/validate",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
        json=payload,
    )

    assert resp.status_code == 200
    assert resp.json["valid"] is True
    assert "loop" in resp.json["warnings"][0].lower()


def test_flowforge_routes_require_feature_enablement(client, monkeypatch):
    resp = client.get("/api/v1/flowforge/workflows", headers=_headers(monkeypatch, feature_enabled=False))

    assert resp.status_code == 403


def test_flowforge_viewer_role_can_read_but_not_design(client, monkeypatch):
    service = _RunService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    read_resp = client.get(
        "/api/v1/flowforge/workflows",
        headers=_headers(monkeypatch, roles={"flowforge:viewer"}),
    )
    write_resp = client.post(
        "/api/v1/flowforge/workflows",
        headers=_headers(monkeypatch, roles={"flowforge:viewer"}),
        json={"name": "Routing", "workflow_key": "routing", "graph": {"nodes": [], "edges": []}},
    )

    assert read_resp.status_code == 200
    assert write_resp.status_code == 403
    assert "flowforge:designer" in write_resp.json["message"]


def test_flowforge_legacy_user_role_maps_to_viewer_only(client, monkeypatch):
    service = _RunService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    read_resp = client.get(
        "/api/v1/flowforge/workflows",
        headers=_headers(monkeypatch, roles={"flowforge:user"}),
    )
    write_resp = client.post(
        "/api/v1/flowforge/runs/90/notes",
        headers=_headers(monkeypatch, roles={"flowforge:user"}),
        json={"note": "Needs a manual follow-up."},
    )

    assert read_resp.status_code == 200
    assert write_resp.status_code == 403
    assert "flowforge:operator" in write_resp.json["message"]


def test_flowforge_designer_and_operator_roles_are_separate(client, monkeypatch):
    service = _RunService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    designer_resp = client.post(
        "/api/v1/flowforge/workflows",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
        json={"name": "Routing", "workflow_key": "routing", "graph": {"nodes": [], "edges": []}},
    )
    operator_design_resp = client.post(
        "/api/v1/flowforge/workflows",
        headers=_headers(monkeypatch, roles={"flowforge:operator"}),
        json={"name": "Routing", "workflow_key": "routing", "graph": {"nodes": [], "edges": []}},
    )
    operator_note_resp = client.post(
        "/api/v1/flowforge/runs/90/notes",
        headers=_headers(monkeypatch, roles={"flowforge:operator"}),
        json={"note": "Needs a manual follow-up."},
    )

    assert designer_resp.status_code == 201
    assert operator_design_resp.status_code == 403
    assert operator_note_resp.status_code == 201


def test_flowforge_communication_template_routes_create_validate_and_activate(client, monkeypatch):
    service = _TemplateService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)
    headers = _headers(monkeypatch, roles={"flowforge:designer"})
    payload = {
        "template_key": "therapist-task",
        "display_name": "Therapist Task",
        "channel": "email",
        "purpose": "human_task",
        "resource_set_id": 30,
        "subject": "New task for {{resource.display_name}}",
        "body_blocks": [{"type": "action_buttons", "actions": ["accept", "decline"]}],
    }

    list_resp = client.get("/api/v1/flowforge/communication-templates?status=active", headers=headers)
    create_resp = client.post("/api/v1/flowforge/communication-templates", headers=headers, json=payload)
    validate_resp = client.post(
        "/api/v1/flowforge/communication-templates/501/validate",
        headers=headers,
        json={"preview_context": {"resource": {"display_name": "Dr. Lane"}}},
    )
    activate_resp = client.post("/api/v1/flowforge/communication-templates/501/activate", headers=headers)

    assert list_resp.status_code == 200
    assert create_resp.status_code == 201
    assert create_resp.json["template_key"] == "therapist-task"
    assert service.created_payload["workspace_id"] == "ws-1"
    assert validate_resp.status_code == 200
    assert validate_resp.json["preview"]["subject"] == "New task for Dr. Lane"
    assert activate_resp.status_code == 200
    assert activate_resp.json["status"] == "active"


def test_flowforge_communication_template_ai_draft_route_creates_draft(client, monkeypatch):
    service = _TemplateService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.post(
        "/api/v1/flowforge/communication-templates/ai-drafts",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
        json={
            "prompt": "Write a task email.",
            "purpose": "human_task",
            "channel": "email",
            "resource_set_id": 30,
            "required_actions": ["accept", "decline"],
            "tone": "concise",
        },
    )

    assert resp.status_code == 201
    assert resp.json["subject"] == "Action requested"
    assert service.created_ai_draft["workspace_id"] == "ws-1"
    assert service.created_ai_draft["actor_user_id"] == "user-1"


def test_flowforge_run_inspector_returns_design_preview(client, monkeypatch):
    service = _RunService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)
    resp = client.get(
        "/api/v1/flowforge/workflows/42/run-inspector",
        headers=_headers(monkeypatch),
    )

    assert resp.status_code == 200
    assert resp.json["workflow_id"] == "42"
    assert resp.json["mode"] == "design_preview"
    assert resp.json["events"][0]["event_type"].startswith("workflow.preview.")


class _TemplateService:
    def __init__(self) -> None:
        self.created_payload = None
        self.created_ai_draft = None

    def list_communication_templates(self, *, workspace_id: str, status: str | None, purpose: str | None, channel: str | None, resource_set_id: int | None):
        return [
            {
                "id": 501,
                "workspace_id": workspace_id,
                "template_key": "therapist-task",
                "display_name": "Therapist Task",
                "description": None,
                "channel": channel or "email",
                "purpose": purpose or "human_task",
                "resource_set_id": resource_set_id,
                "subject": "New task for {{resource.display_name}}",
                "body_blocks": [{"type": "action_buttons", "actions": ["accept", "decline"]}],
                "status": status or "active",
                "validation_status": "valid",
                "validation_result": {"valid": True, "errors": [], "warnings": []},
                "metadata": {},
            }
        ]

    def create_communication_template(self, *, workspace_id: str, payload, actor_user_id: str):
        self.created_payload = {"workspace_id": workspace_id, "payload": payload, "actor_user_id": actor_user_id}
        return {
            "id": 501,
            "workspace_id": workspace_id,
            "template_key": payload["template_key"],
            "display_name": payload["display_name"],
            "description": None,
            "channel": payload["channel"],
            "purpose": payload["purpose"],
            "resource_set_id": payload["resource_set_id"],
            "subject": payload["subject"],
            "body_blocks": payload["body_blocks"],
            "status": "draft",
            "validation_status": "valid",
            "validation_result": {"valid": True, "errors": [], "warnings": []},
            "metadata": {},
        }

    def create_communication_template_ai_draft(self, *, workspace_id: str, payload, actor_user_id: str):
        self.created_ai_draft = {"workspace_id": workspace_id, "payload": payload, "actor_user_id": actor_user_id}
        return {
            "id": 601,
            "workspace_id": workspace_id,
            "purpose": payload["purpose"],
            "channel": payload["channel"],
            "resource_set_id": payload["resource_set_id"],
            "prompt": payload["prompt"],
            "tone": payload["tone"],
            "required_actions": payload["required_actions"],
            "subject": "Action requested",
            "body_blocks": [{"type": "action_buttons", "actions": ["accept", "decline"]}],
            "plain_language_summary": "Generated a task email.",
            "validation_status": "valid",
            "validation_result": {"valid": True, "errors": [], "warnings": []},
            "model_provider": "heuristic",
            "model_name": "flowforge-local-communication-template-draft-generator",
            "status": "drafted",
            "draft_source": "heuristic",
        }

    def validate_communication_template(self, *, workspace_id: str, template_id: int, payload):
        return {
            "valid": True,
            "errors": [],
            "warnings": [],
            "referenced_fields": ["resource.display_name"],
            "referenced_actions": ["accept", "decline"],
            "preview": {"subject": "New task for Dr. Lane", "html": "<p>Preview</p>"},
        }

    def activate_communication_template(self, *, workspace_id: str, template_id: int, actor_user_id: str):
        template = self.list_communication_templates(
            workspace_id=workspace_id,
            status="active",
            purpose="human_task",
            channel="email",
            resource_set_id=None,
        )[0]
        template["status"] = "active"
        return template


class _RunService:
    def __init__(self) -> None:
        self.note_payload = None
        self.signed_action_payload = None
        self.approval_payload = None
        self.no_match_payload = None
        self.settings_payload = None

    def list_definitions(self, *, workspace_id: str):
        return [
            {
                "id": "42",
                "name": "Persisted Intake Routing",
                "description": "Routes intake submissions.",
                "status": "draft",
                "graph": {"nodes": [{"id": "intake"}], "edges": []},
            }
        ]

    def get_run_inspector(self, *, workspace_id: str, workflow_id: str):
        return {
            "workflow_id": workflow_id,
            "mode": "design_preview",
            "status": "ready",
            "events": [
                {
                    "id": "preview-1",
                    "event_type": "workflow.preview.intake",
                    "node_id": "intake",
                    "message": "Intake is part of the design preview.",
                    "timestamp": "2026-05-04T10:00:00Z",
                    "data": {"status": "preview"},
                }
            ],
            "notes": ["This preview summarizes the workflow graph before runtime execution."],
        }

    def list_runs(self, *, workspace_id: str, status: str | None, mode: str | None, limit: int, offset: int):
        return {
            "workspace_id": workspace_id,
            "status": status,
            "mode": mode,
            "limit": limit,
            "offset": offset,
            "runs": [
                {
                    "id": 90,
                    "workspace_id": workspace_id,
                    "workflow_definition_id": 12,
                    "workflow_version_id": 13,
                    "intake_event_id": 501,
                    "mode": "test",
                    "status": "waiting",
                    "current_node_id": "intake",
                    "run_context": {"trigger_key": "intake-routing"},
                }
            ],
        }

    def add_run_note(self, *, workspace_id: str, run_id: int, payload, actor_user_id: str):
        self.note_payload = {
            "workspace_id": workspace_id,
            "run_id": run_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": 802,
            "workspace_id": workspace_id,
            "run_id": run_id,
            "event_type": "workflow.operator.note",
            "node_id": None,
            "message": "Operator note added.",
            "event_payload": {"note": payload["note"]},
            "actor_type": "user",
            "actor_id": actor_user_id,
        }

    def get_run(self, *, workspace_id: str, run_id: int):
        if run_id != 90:
            return None
        return self.list_runs(workspace_id=workspace_id, status=None, mode=None, limit=1, offset=0)["runs"][0]

    def list_run_events(self, *, workspace_id: str, run_id: int, limit: int):
        return {
            "workspace_id": workspace_id,
            "run_id": run_id,
            "limit": limit,
            "events": [
                {
                    "id": 801,
                    "workspace_id": workspace_id,
                    "run_id": run_id,
                    "event_type": "workflow.run.created",
                    "node_id": "intake",
                    "message": "Workflow run created from integration trigger.",
                    "event_payload": {"trigger_key": "intake-routing"},
                    "actor_type": "system",
                    "actor_id": "flowforge",
                }
            ],
        }

    def list_run_human_tasks(self, *, workspace_id: str, run_id: int, limit: int):
        return {
            "workspace_id": workspace_id,
            "run_id": run_id,
            "limit": limit,
            "tasks": [
                {
                    "id": 301,
                    "workspace_id": workspace_id,
                    "run_id": run_id,
                    "task_type": "offer",
                    "resource_set_id": 20,
                    "source_record_key": "resource-1",
                    "status": "pending",
                    "assigned_to_principal_type": "resource",
                    "assigned_to_principal_id": "resource-1",
                    "due_at": "2026-05-05 12:00:00",
                    "completed_at": None,
                    "response": {"allowed_actions": ["accept", "decline"]},
                }
            ],
        }

    def create_signed_action_token(self, *, workspace_id: str, human_task_id: int, payload, actor_user_id: str):
        self.signed_action_payload = {
            "workspace_id": workspace_id,
            "human_task_id": human_task_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "human_task_id": human_task_id,
            "token": "plain-token",
            "allowed_actions": payload["allowed_actions"],
            "expires_at": payload["expires_at"],
        }

    def complete_approval_task(self, *, workspace_id: str, human_task_id: int, action: str, payload, actor_user_id: str):
        self.approval_payload = {
            "workspace_id": workspace_id,
            "human_task_id": human_task_id,
            "action": action,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "human_task_id": human_task_id,
            "run_id": 90,
            "action": action,
            "status": "approved" if action == "approve" else "declined",
            "runtime": {"status": "advanced", "to_node_id": "export" if action == "approve" else "failed"},
        }

    def get_signed_action_details(self, *, token: str):
        return {
            "valid": token == "plain-token",
            "allowed_actions": ["accept", "decline"],
            "expires_at": "2099-01-01 00:00:00",
            "task": {
                "task_type": "offer",
                "status": "pending",
                "source_record_key": "resource-1",
            },
        }

    def complete_signed_action(self, *, token: str, action: str, payload, source_ip: str | None):
        return {
            "accepted": token == "plain-token",
            "action": action,
            "task": {"task_type": "offer", "status": "accepted" if action == "accept" else "declined"},
        }

    def list_run_notifications(self, *, workspace_id: str, run_id: int, limit: int):
        return {
            "workspace_id": workspace_id,
            "run_id": run_id,
            "limit": limit,
            "notifications": [
                {
                    "id": 701,
                    "workspace_id": workspace_id,
                    "run_id": run_id,
                    "human_task_id": None,
                    "channel": "email",
                    "recipient": "ops@example.com",
                    "template_key": "flowforge.no_match",
                    "status": "pending",
                    "payload_summary": {"reason": "No eligible resources."},
                }
            ],
        }

    def create_no_match_escalation(self, *, workspace_id: str, run_id: int, payload, actor_user_id: str):
        self.no_match_payload = {
            "workspace_id": workspace_id,
            "run_id": run_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "run_id": run_id,
            "status": "needs_attention",
            "reason": payload["reason"],
            "recipients": payload["recipients"],
            "notification_count": len(payload["recipients"]),
        }

    def get_workspace_settings(self, *, workspace_id: str):
        return {
            "workspace_id": workspace_id,
            "enabled": True,
            "allow_designer_publish": False,
            "block_sensitive_reporting_mcp": False,
            "raw_payload_retention_days": 30,
            "raw_payload_retention_max_days": 90,
            "default_offer_timeout_minutes": 1440,
            "default_no_match_recipients": ["ops@example.com"],
            "default_test_recipients": ["test@example.com"],
            "settings": {},
        }

    def update_workspace_settings(self, *, workspace_id: str, payload, actor_user_id: str):
        self.settings_payload = {
            "workspace_id": workspace_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {**self.get_workspace_settings(workspace_id=workspace_id), **payload}

    def list_reporting_domains(self, *, workspace_id: str):
        return [
            {
                "workspace_id": workspace_id,
                "domain_key": "flowforge_workflow_runs",
                "display_name": "FlowForge Workflow Runs",
                "description": "Run status and operational metrics.",
                "read_model": "v_flowforge_report_workflow_runs",
                "semantic_registered": True,
                "default_filters": [{"field": "mode", "operator": "equals", "value": "production"}],
                "sensitive_excluded_fields": ["run_context_json"],
                "query_studio_prompts": ["How many FlowForge runs completed this week?"],
                "metrics": [{"key": "run_count", "label": "Run Count"}],
                "dimensions": [{"key": "mode", "label": "Mode"}],
            },
            {
                "workspace_id": workspace_id,
                "domain_key": "flowforge_intake_events",
                "display_name": "FlowForge Intake Events",
                "description": "Safe intake metadata.",
                "read_model": "v_flowforge_report_intake_events",
                "semantic_registered": True,
                "default_filters": [{"field": "mode", "operator": "equals", "value": "production"}],
                "sensitive_excluded_fields": ["raw_payload_json"],
                "query_studio_prompts": ["How many intakes were received?"],
                "metrics": [{"key": "intake_event_count", "label": "Intake Event Count"}],
                "dimensions": [{"key": "provider", "label": "Provider"}],
            }
        ]

    def get_report_summary(self, *, workspace_id: str, mode: str | None):
        return {
            "workspace_id": workspace_id,
            "mode": mode or "production",
            "default_filters": [{"field": "mode", "operator": "equals", "value": mode or "production"}],
            "metrics": {"run_count": 10, "needs_attention_count": 2},
        }

    def get_report_dashboard(self, *, workspace_id: str, mode: str | None):
        normalized_mode = mode or "production"
        return {
            "workspace_id": workspace_id,
            "mode": normalized_mode,
            "default_filters": [{"field": "mode", "operator": "equals", "value": normalized_mode}],
            "metrics": {"run_count": 10, "offer_count": 6, "assignment_count": 4},
            "domains": self.list_reporting_domains(workspace_id=workspace_id),
        }

    def list_workflow_versions(self, *, workspace_id: str, workflow_definition_id: int):
        return [
            {
                "id": 44,
                "workspace_id": workspace_id,
                "workflow_definition_id": workflow_definition_id,
                "version_number": 1,
                "version_status": "draft",
                "graph": {"nodes": [{"id": "intake"}], "edges": []},
                "validation_status": "valid",
                "validation_result": {"errors": [], "warnings": []},
                "matching_policy_refs": [],
                "settings": {},
            }
        ]

    def create_workflow_definition(self, *, workspace_id: str, payload, actor_user_id: str):
        return {
            "id": "12",
            "name": payload["name"],
            "description": payload.get("description", ""),
            "status": "draft",
            "graph": payload["graph"],
        }

    def create_workflow_version(self, *, workspace_id: str, workflow_definition_id: int, payload, actor_user_id: str):
        return {
            "id": 45,
            "workspace_id": workspace_id,
            "workflow_definition_id": workflow_definition_id,
            "version_number": 2,
            "version_status": "draft",
            "graph": payload["graph"],
            "validation_status": "valid",
            "validation_result": {"errors": [], "warnings": []},
            "matching_policy_refs": [],
            "settings": {"created_by": actor_user_id},
        }

    def create_workflow_ai_draft(self, *, workspace_id: str, payload, actor_user_id: str):
        return {
            "prompt": payload["prompt"],
            "graph": {
                "nodes": [
                    {
                        "id": "intake",
                        "type": "intake",
                        "label": "Patient Intake",
                        "position": {"x": 40, "y": 120},
                        "data": {"source": "intake-form", "event": "intake_submitted"},
                    },
                    {
                        "id": "approval",
                        "type": "approval",
                        "label": "Approval Gate",
                        "position": {"x": 280, "y": 120},
                        "data": {"approver_role": "flowforge:operator"},
                    },
                ],
                "edges": [{"id": "intake-approval", "source": "intake", "target": "approval"}],
            },
            "plain_language_summary": f"Drafted by {actor_user_id} in {workspace_id}.",
            "validation_status": "valid",
            "validation_result": {"valid": True, "errors": [], "warnings": []},
            "model_provider": "openai",
            "model_name": "workflow-drafter",
            "draft_source": "llm",
        }

    def publish_workflow_version(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        version_id: int,
        actor_user_id: str,
    ):
        return {
            "id": version_id,
            "workspace_id": workspace_id,
            "workflow_definition_id": workflow_definition_id,
            "version_number": 1,
            "version_status": "published",
            "graph": {"nodes": [{"id": "intake"}], "edges": []},
            "validation_status": "valid",
            "validation_result": {"errors": [], "warnings": []},
            "matching_policy_refs": [],
            "settings": {"published_by": actor_user_id},
        }

    def delete_workflow_definition(self, *, workspace_id: str, workflow_definition_id: int, actor_user_id: str):
        del workspace_id, actor_user_id
        return {
            "deleted": True,
            "workflow_definition_id": workflow_definition_id,
        }


class _DataMovementService(_RunService):
    def __init__(self) -> None:
        super().__init__()
        self.source_payload = None
        self.destination_payload = None
        self.source_enabled_payload = None
        self.destination_enabled_payload = None

    def list_data_sources(self, *, workspace_id: str):
        return [
            {
                "id": 1,
                "workspace_id": workspace_id,
                "source_key": "local-import",
                "display_name": "Local Import",
                "source_type": "local_file_test",
                "enabled": True,
                "mode": "test",
                "config": {"base_dir": "/tmp/flowforge-imports"},
            }
        ]

    def upsert_data_source(self, *, workspace_id: str, payload, actor_user_id: str):
        self.source_payload = {
            "workspace_id": workspace_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": 2,
            "workspace_id": workspace_id,
            "source_key": payload["source_key"],
            "display_name": payload["display_name"],
            "source_type": payload["source_type"],
            "enabled": payload.get("enabled", True),
            "mode": payload.get("mode", "test"),
            "config": payload.get("config", {}),
        }

    def set_data_source_enabled(self, *, workspace_id: str, source_key: str, enabled: bool, actor_user_id: str):
        self.source_enabled_payload = {
            "workspace_id": workspace_id,
            "source_key": source_key,
            "enabled": enabled,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": 1,
            "workspace_id": workspace_id,
            "source_key": source_key,
            "display_name": "Local Import",
            "source_type": "local_file_test",
            "enabled": enabled,
            "mode": "test",
            "config": {"base_dir": "/tmp/flowforge-imports"},
        }

    def test_data_source(self, *, workspace_id: str, source_key: str):
        return {
            "ok": True,
            "key": source_key,
            "kind": "source",
            "type": "local_file_test",
            "mode": "test",
            "enabled": True,
            "message": f"Source '{source_key}' is enabled and has testable configuration.",
        }

    def list_data_destinations(self, *, workspace_id: str):
        return [
            {
                "id": 3,
                "workspace_id": workspace_id,
                "destination_key": "local-export",
                "display_name": "Local Export",
                "destination_type": "local_file_test",
                "enabled": True,
                "mode": "test",
                "config": {"base_dir": "/tmp/flowforge-exports"},
            }
        ]

    def upsert_data_destination(self, *, workspace_id: str, payload, actor_user_id: str):
        self.destination_payload = {
            "workspace_id": workspace_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": 4,
            "workspace_id": workspace_id,
            "destination_key": payload["destination_key"],
            "display_name": payload["display_name"],
            "destination_type": payload["destination_type"],
            "enabled": payload.get("enabled", True),
            "mode": payload.get("mode", "test"),
            "config": payload.get("config", {}),
        }

    def set_data_destination_enabled(
        self, *, workspace_id: str, destination_key: str, enabled: bool, actor_user_id: str
    ):
        self.destination_enabled_payload = {
            "workspace_id": workspace_id,
            "destination_key": destination_key,
            "enabled": enabled,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": 3,
            "workspace_id": workspace_id,
            "destination_key": destination_key,
            "display_name": "Local Export",
            "destination_type": "local_file_test",
            "enabled": enabled,
            "mode": "test",
            "config": {"base_dir": "/tmp/flowforge-exports"},
        }

    def test_data_destination(self, *, workspace_id: str, destination_key: str):
        return {
            "ok": True,
            "key": destination_key,
            "kind": "destination",
            "type": "local_file_test",
            "mode": "test",
            "enabled": True,
            "message": f"Destination '{destination_key}' is enabled and has testable configuration.",
        }

    def list_dataset_artifacts(self, *, workspace_id: str, run_id: int | None, limit: int, offset: int):
        return {
            "run_id": run_id,
            "limit": limit,
            "offset": offset,
            "artifacts": [
                {
                    "id": 701,
                    "workspace_id": workspace_id,
                    "run_id": run_id,
                    "node_id": "import",
                    "artifact_key": "run:90:node:import",
                    "artifact_type": "import",
                    "storage_kind": "preview_metadata",
                    "storage_ref": {"rows": [{"source_record_key": "r1"}]},
                    "schema": {"validation": {"invalid_row_count": 0, "invalid_rows": []}},
                    "row_count": 1,
                    "byte_count": 44,
                    "checksum": "abc",
                    "status": "staged",
                }
            ],
        }

    def get_dataset_artifact(self, *, workspace_id: str, artifact_id: int):
        return {
            "id": artifact_id,
            "workspace_id": workspace_id,
            "run_id": 90,
            "node_id": "import",
            "artifact_key": "run:90:node:import",
            "artifact_type": "import",
            "storage_kind": "preview_metadata",
            "storage_ref": {"rows": [{"display_name": "Missing Key"}]},
            "schema": {"validation": {"invalid_row_count": 1, "invalid_rows": [{"row_number": 1}]}},
            "row_count": 1,
            "byte_count": 22,
            "checksum": "def",
            "status": "validation_failed",
        }

    def list_data_movement_audit(self, *, workspace_id: str, run_id: int | None, limit: int, offset: int):
        return {
            "run_id": run_id,
            "limit": limit,
            "offset": offset,
            "audit": [
                {
                    "id": 901,
                    "workspace_id": workspace_id,
                    "run_id": run_id,
                    "node_id": "export",
                    "action_type": "export",
                    "status": "completed",
                    "source_key": "artifact:701",
                    "destination_key": "local-export",
                    "dataset_artifact_id": 702,
                    "resource_set_id": None,
                    "actor_type": "system",
                    "actor_id": "flowforge",
                    "request": {"format": "csv"},
                    "result": {"row_count": 1},
                    "error_message": None,
                }
            ],
        }


def test_flowforge_runs_route_lists_runs(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _RunService())

    resp = client.get("/api/v1/flowforge/runs?status=waiting&mode=test&limit=25&offset=5", headers=_headers(monkeypatch))

    assert resp.status_code == 200
    assert resp.json["status"] == "waiting"
    assert resp.json["mode"] == "test"
    assert resp.json["runs"][0]["id"] == 90


def test_flowforge_settings_routes_get_and_update_settings(client, monkeypatch):
    service = _RunService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    detail = client.get("/api/v1/flowforge/settings", headers=_headers(monkeypatch, roles={"flowforge:admin"}))
    updated = client.put(
        "/api/v1/flowforge/settings",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json={"enabled": True, "default_no_match_recipients": ["ops@example.com"]},
    )

    assert detail.status_code == 200
    assert detail.json["default_test_recipients"] == ["test@example.com"]
    assert updated.status_code == 200
    assert service.settings_payload["payload"]["default_no_match_recipients"] == ["ops@example.com"]


def test_flowforge_run_detail_and_events_routes(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _RunService())

    detail = client.get("/api/v1/flowforge/runs/90", headers=_headers(monkeypatch))
    events = client.get("/api/v1/flowforge/runs/90/events?limit=10", headers=_headers(monkeypatch))
    missing = client.get("/api/v1/flowforge/runs/999", headers=_headers(monkeypatch))

    assert detail.status_code == 200
    assert detail.json["id"] == 90
    assert events.status_code == 200
    assert events.json["events"][0]["event_type"] == "workflow.run.created"
    assert missing.status_code == 404


def test_flowforge_run_note_route_appends_operator_note(client, monkeypatch):
    service = _RunService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.post(
        "/api/v1/flowforge/runs/90/notes",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json={"note": "Called intake coordinator.", "idempotency_key": "note-1"},
    )

    assert resp.status_code == 201
    assert resp.json["event_type"] == "workflow.operator.note"
    assert resp.json["event_payload"]["note"] == "Called intake coordinator."
    assert service.note_payload["run_id"] == 90
    assert service.note_payload["actor_user_id"] == "user-1"


def test_flowforge_run_human_tasks_route_lists_tasks(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _RunService())

    resp = client.get("/api/v1/flowforge/runs/90/human-tasks?limit=10", headers=_headers(monkeypatch))

    assert resp.status_code == 200
    assert resp.json["run_id"] == 90
    assert resp.json["tasks"][0]["task_type"] == "offer"
    assert resp.json["tasks"][0]["response"] == {"allowed_actions": ["accept", "decline"]}


def test_flowforge_human_task_signed_action_route_creates_token(client, monkeypatch):
    service = _RunService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.post(
        "/api/v1/flowforge/human-tasks/301/signed-actions",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json={"allowed_actions": ["accept", "decline"], "expires_at": "2099-01-01 00:00:00"},
    )

    assert resp.status_code == 201
    assert resp.json["token"] == "plain-token"
    assert service.signed_action_payload["human_task_id"] == 301


def test_flowforge_approval_task_routes_record_operator_decisions(client, monkeypatch):
    service = _RunService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    approved = client.post(
        "/api/v1/flowforge/human-tasks/401/approve",
        headers=_headers(monkeypatch, roles={"flowforge:operator"}),
        json={"decision_note": "Destination is approved."},
    )
    declined = client.post(
        "/api/v1/flowforge/human-tasks/402/decline",
        headers=_headers(monkeypatch, roles={"flowforge:operator"}),
        json={"decline_reason": "Wrong destination."},
    )

    assert approved.status_code == 200
    assert approved.json["status"] == "approved"
    assert approved.json["runtime"]["to_node_id"] == "export"
    assert declined.status_code == 200
    assert declined.json["status"] == "declined"
    assert service.approval_payload["human_task_id"] == 402
    assert service.approval_payload["actor_user_id"] == "user-1"


def test_flowforge_public_signed_action_routes(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _RunService())
    monkeypatch.setattr("app.features.flowforge.routes.human_tasks.RateLimitService.enforce", lambda *args, **kwargs: None)

    detail = client.get("/api/v1/flowforge/public/actions/plain-token")
    accepted = client.post(
        "/api/v1/flowforge/public/actions/plain-token/accept",
        json={"response_note": "I can take this referral."},
    )
    declined = client.post(
        "/api/v1/flowforge/public/actions/plain-token/decline",
        json={"decline_reason": "No availability."},
    )

    assert detail.status_code == 200
    assert detail.json["task"]["task_type"] == "offer"
    assert accepted.status_code == 200
    assert accepted.json["action"] == "accept"
    assert declined.status_code == 200
    assert declined.json["action"] == "decline"


def test_flowforge_public_signed_action_routes_are_rate_limited(client, monkeypatch):
    from app.exceptions.forge_error import ForgeError

    monkeypatch.setattr(flowforge_routes, "_service", lambda: _RunService())

    def _blocked(*args, **kwargs):
        raise ForgeError("Too many signed action attempts. Please try again later.", status_code=429)

    monkeypatch.setattr("app.features.flowforge.routes.human_tasks.RateLimitService.enforce", _blocked)

    resp = client.post("/api/v1/flowforge/public/actions/plain-token/accept", json={"response_note": "ok"})

    assert resp.status_code == 429


def test_flowforge_run_notifications_route_lists_notifications(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _RunService())

    resp = client.get("/api/v1/flowforge/runs/90/notifications?limit=10", headers=_headers(monkeypatch))

    assert resp.status_code == 200
    assert resp.json["notifications"][0]["template_key"] == "flowforge.no_match"
    assert resp.json["notifications"][0]["payload_summary"] == {"reason": "No eligible resources."}


def test_flowforge_data_source_routes_configure_toggle_and_test(client, monkeypatch):
    service = _DataMovementService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    listed = client.get("/api/v1/flowforge/data-sources", headers=_headers(monkeypatch))
    created = client.post(
        "/api/v1/flowforge/data-sources",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
        json={
            "source_key": "local-import",
            "display_name": "Local Import",
            "source_type": "local_file_test",
            "mode": "test",
            "enabled": True,
            "config": {"base_dir": "/tmp/flowforge-imports"},
        },
    )
    toggled = client.patch(
        "/api/v1/flowforge/data-sources/local-import",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
        json={"enabled": False},
    )
    tested = client.post(
        "/api/v1/flowforge/data-sources/local-import/test",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
    )

    assert listed.status_code == 200
    assert listed.json[0]["source_key"] == "local-import"
    assert created.status_code == 200
    assert service.source_payload["actor_user_id"] == "user-1"
    assert toggled.status_code == 200
    assert service.source_enabled_payload["enabled"] is False
    assert tested.status_code == 200
    assert tested.json["ok"] is True


def test_flowforge_data_destination_routes_configure_toggle_and_test(client, monkeypatch):
    service = _DataMovementService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    listed = client.get("/api/v1/flowforge/data-destinations", headers=_headers(monkeypatch))
    created = client.post(
        "/api/v1/flowforge/data-destinations",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
        json={
            "destination_key": "local-export",
            "display_name": "Local Export",
            "destination_type": "local_file_test",
            "mode": "test",
            "enabled": True,
            "config": {"base_dir": "/tmp/flowforge-exports"},
        },
    )
    toggled = client.patch(
        "/api/v1/flowforge/data-destinations/local-export",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
        json={"enabled": False},
    )
    tested = client.post(
        "/api/v1/flowforge/data-destinations/local-export/test",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
    )

    assert listed.status_code == 200
    assert listed.json[0]["destination_key"] == "local-export"
    assert created.status_code == 200
    assert service.destination_payload["actor_user_id"] == "user-1"
    assert toggled.status_code == 200
    assert service.destination_enabled_payload["enabled"] is False
    assert tested.status_code == 200
    assert tested.json["kind"] == "destination"


def test_flowforge_dataset_artifact_and_data_movement_audit_routes(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _DataMovementService())

    artifacts = client.get("/api/v1/flowforge/dataset-artifacts?run_id=90&limit=25&offset=5", headers=_headers(monkeypatch))
    artifact = client.get("/api/v1/flowforge/dataset-artifacts/701", headers=_headers(monkeypatch))
    audit = client.get("/api/v1/flowforge/data-movement-audit?run_id=90&limit=25&offset=5", headers=_headers(monkeypatch))

    assert artifacts.status_code == 200
    assert artifacts.json["run_id"] == 90
    assert artifacts.json["artifacts"][0]["status"] == "staged"
    assert artifact.status_code == 200
    assert artifact.json["schema"]["validation"]["invalid_row_count"] == 1
    assert audit.status_code == 200
    assert audit.json["audit"][0]["action_type"] == "export"
    assert audit.json["audit"][0]["destination_key"] == "local-export"


def test_flowforge_no_match_escalation_route_creates_notifications(client, monkeypatch):
    service = _RunService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.post(
        "/api/v1/flowforge/runs/90/no-match-escalations",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json={"reason": "No eligible resources.", "recipients": ["ops@example.com"]},
    )

    assert resp.status_code == 201
    assert resp.json["status"] == "needs_attention"
    assert resp.json["notification_count"] == 1
    assert service.no_match_payload["run_id"] == 90


def test_flowforge_reporting_routes_return_domains_and_summary(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _RunService())

    domains = client.get("/api/v1/flowforge/reports/domains", headers=_headers(monkeypatch))
    summary = client.get("/api/v1/flowforge/reports/summary", headers=_headers(monkeypatch))
    dashboard = client.get("/api/v1/flowforge/reports/dashboard", headers=_headers(monkeypatch))

    assert domains.status_code == 200
    assert domains.json[0]["domain_key"] == "flowforge_workflow_runs"
    assert domains.json[0]["semantic_registered"] is True
    assert "raw_payload_json" in {field for domain in domains.json for field in domain["sensitive_excluded_fields"]}
    assert summary.status_code == 200
    assert summary.json["mode"] == "production"
    assert summary.json["metrics"]["run_count"] == 10
    assert dashboard.status_code == 200
    assert dashboard.json["metrics"]["offer_count"] == 6
    assert dashboard.json["default_filters"][0]["value"] == "production"


def test_flowforge_workflow_version_routes_list_and_publish(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _RunService())

    versions = client.get("/api/v1/flowforge/workflows/12/versions", headers=_headers(monkeypatch))
    published = client.post(
        "/api/v1/flowforge/workflows/12/versions/44/publish",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
    )

    assert versions.status_code == 200
    assert versions.json[0]["id"] == 44
    assert published.status_code == 200
    assert published.json["version_status"] == "published"


def test_flowforge_workflow_authoring_routes_create_definition_and_version(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _RunService())
    graph = {
        "nodes": [
            {
                "id": "intake",
                "type": "intake",
                "label": "Patient Intake",
                "position": {"x": 40, "y": 120},
                "data": {"source": "", "event": ""},
            }
        ],
        "edges": [],
        "viewport": {"x": -220, "y": -110, "zoom": 0.62},
    }

    created = client.post(
        "/api/v1/flowforge/workflows",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json={"workflow_key": "new-routing", "name": "New Routing", "graph": graph},
    )
    version = client.post(
        "/api/v1/flowforge/workflows/12/versions",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json={"graph": graph},
    )

    assert created.status_code == 201
    assert created.json["id"] == "12"
    assert created.json["name"] == "New Routing"
    assert created.json["graph"]["nodes"][0]["id"] == "intake"
    assert created.json["graph"]["nodes"][0]["label"] == "Patient Intake"
    assert created.json["graph"]["edges"] == []
    assert created.json["graph"]["viewport"] == {"x": -220, "y": -110, "zoom": 0.62}
    assert version.status_code == 201
    assert version.json["version_number"] == 2
    assert version.json["graph"]["viewport"] == {"x": -220, "y": -110, "zoom": 0.62}


def test_flowforge_workflow_ai_draft_route_uses_workspace_llm_path(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _RunService())

    resp = client.post(
        "/api/v1/flowforge/workflows/ai-drafts",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
        json={
            "prompt": "Add an approval gate.",
            "use_llm": True,
            "graph": {"nodes": [{"id": "intake", "type": "intake"}], "edges": []},
        },
    )

    assert resp.status_code == 201
    assert resp.json["draft_source"] == "llm"
    assert resp.json["model_provider"] == "openai"
    assert resp.json["graph"]["nodes"][1]["type"] == "approval"
    assert resp.json["plain_language_summary"] == "Drafted by user-1 in ws-1."


def test_flowforge_workflow_delete_route_archives_definition(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _RunService())

    deleted = client.delete(
        "/api/v1/flowforge/workflows/12",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
    )

    assert deleted.status_code == 200
    assert deleted.json == {"deleted": True, "workflow_definition_id": 12}


class _ResourceService:
    def __init__(self) -> None:
        self.created_payload = None
        self.updated_payload = None
        self.deleted_payload = None
        self.updated_record_payload = None
        self.deleted_record_payload = None

    def list_resource_sets(self, *, workspace_id: str):
        return [
            {
                "id": 20,
                "workspace_id": workspace_id,
                "resource_set_key": "therapist-pool",
                "display_name": "Therapist Pool",
                "description": "Compiled provider records.",
                "source_type": "manual_csv",
                "enabled": True,
                "active_snapshot_batch_id": 30,
                "settings": {},
            }
        ]

    def create_resource_set(self, *, workspace_id: str, payload, actor_user_id: str):
        self.created_payload = {
            "workspace_id": workspace_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": 21,
            "workspace_id": workspace_id,
            "resource_set_key": payload["resource_set_key"],
            "display_name": payload["display_name"],
            "description": None,
            "source_type": "manual_csv",
            "enabled": True,
            "active_snapshot_batch_id": None,
            "settings": {},
        }

    def update_resource_set(self, *, workspace_id: str, resource_set_id: int, payload, actor_user_id: str):
        self.updated_payload = {
            "workspace_id": workspace_id,
            "resource_set_id": resource_set_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": resource_set_id,
            "workspace_id": workspace_id,
            "resource_set_key": "therapist-pool",
            "display_name": "Therapist Pool",
            "description": None,
            "source_type": "manual_csv",
            "enabled": bool(payload["enabled"]),
            "active_snapshot_batch_id": 30,
            "settings": {},
        }

    def delete_resource_set(self, *, workspace_id: str, resource_set_id: int, actor_user_id: str):
        self.deleted_payload = {
            "workspace_id": workspace_id,
            "resource_set_id": resource_set_id,
            "actor_user_id": actor_user_id,
        }
        return {"deleted": True, "resource_set_id": resource_set_id}

    def list_resource_records(self, *, workspace_id: str, resource_set_id: int, limit: int, offset: int):
        return {
            "resource_set_id": resource_set_id,
            "limit": limit,
            "offset": offset,
            "records": [
                {
                    "id": 300,
                    "workspace_id": workspace_id,
                    "resource_set_id": resource_set_id,
                    "source_record_key": "resource-1",
                    "display_name": "Jane Resource",
                    "primary_email": "jane@example.com",
                    "effective_status": "active",
                    "availability_status": "available",
                    "capacity_available": 2,
                    "source_missing": False,
                    "tags": ["telehealth"],
                    "attributes": {"languages": ["Spanish"]},
                    "normalized_profile": {"display_name": "Jane Resource"},
                }
            ],
        }

    def update_resource_record(self, *, workspace_id: str, resource_set_id: int, record_id: int, payload, actor_user_id: str):
        self.updated_record_payload = {
            "workspace_id": workspace_id,
            "resource_set_id": resource_set_id,
            "record_id": record_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": record_id,
            "workspace_id": workspace_id,
            "resource_set_id": resource_set_id,
            "source_record_key": "resource-1",
            "display_name": payload.get("display_name", "Jane Resource"),
            "primary_email": "jane@example.com",
            "effective_status": "active",
            "availability_status": "available",
            "capacity_available": 1,
            "source_missing": False,
            "tags": ["telehealth"],
            "attributes": {"languages": ["Spanish"]},
            "normalized_profile": {"display_name": payload.get("display_name", "Jane Resource")},
            "validation_errors": [],
        }

    def delete_resource_record(self, *, workspace_id: str, resource_set_id: int, record_id: int, actor_user_id: str):
        self.deleted_record_payload = {
            "workspace_id": workspace_id,
            "resource_set_id": resource_set_id,
            "record_id": record_id,
            "actor_user_id": actor_user_id,
        }
        return {"deleted": True, "resource_set_id": resource_set_id, "resource_record_id": record_id}

    def list_resource_snapshot_batches(self, *, workspace_id: str, resource_set_id: int, limit: int):
        return [
            {
                "id": 30,
                "workspace_id": workspace_id,
                "resource_set_id": resource_set_id,
                "batch_key": "manual-20260504",
                "source_type": "manual_csv",
                "mode": "test",
                "status": "completed",
                "record_count": 1,
                "valid_count": 1,
                "invalid_count": 0,
                "summary": {"message": "ok"},
            }
        ][:limit]

    def create_manual_resource_snapshot(self, *, workspace_id: str, resource_set_id: int, payload, actor_user_id: str):
        self.created_payload = {
            "workspace_id": workspace_id,
            "resource_set_id": resource_set_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "resource_set_id": resource_set_id,
            "snapshot_batch_id": 31,
            "status": "completed",
            "record_count": len(payload.get("records", [])),
            "valid_count": len(payload.get("records", [])),
            "invalid_count": 0,
            "activated": bool(payload.get("activate", True)),
        }


class _IntegrationService:
    def __init__(self) -> None:
        self.created_payload = None
        self.created_trigger = None
        self.accepted_webhook = None

    def list_integrations(self, *, workspace_id: str, provider: str | None = None):
        return [
            {
                "id": 10,
                "workspace_id": workspace_id,
                "provider": provider or "jotform",
                "integration_key": "intake-form",
                "display_name": "Intake Form",
                "external_form_id": "form-1",
                "enabled": True,
                "mode": "test",
                "webhook_public_id": "ffj_public",
                "webhook_path": "/api/v1/flowforge/webhooks/jotform/ffj_public",
                "webhook_url": "/api/v1/flowforge/webhooks/jotform/ffj_public",
                "field_mapping": {"patient": "patientName"},
                "source_events": [
                    {"event_key": "intake_submitted", "display_name": "Intake Submitted", "description": None}
                ],
                "source_fields": [
                    {"path": "serviceRequested", "label": "Requested Service", "type": "text", "required": True, "sensitive": False}
                ],
                "test_recipient_overrides": ["ops@example.com"],
                "settings": {},
            }
        ]

    def create_jotform_integration(self, *, workspace_id: str, payload, actor_user_id: str):
        self.created_payload = {
            "workspace_id": workspace_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": 11,
            "workspace_id": workspace_id,
            "provider": "jotform",
            "integration_key": payload["integration_key"],
            "display_name": payload["display_name"],
            "external_form_id": payload.get("external_form_id"),
            "enabled": True,
            "mode": payload.get("mode", "production"),
            "webhook_public_id": "ffj_public",
            "webhook_path": "/api/v1/flowforge/webhooks/jotform/ffj_public",
            "webhook_url": "/api/v1/flowforge/webhooks/jotform/ffj_public",
            "webhook_secret": "ffjot_secret",
            "field_mapping": payload.get("field_mapping", {}),
            "source_events": payload.get("source_events", []),
            "source_fields": payload.get("source_fields", []),
            "test_recipient_overrides": [],
            "settings": {},
        }

    def create_webhook_integration(self, *, workspace_id: str, payload, actor_user_id: str):
        self.created_payload = {
            "workspace_id": workspace_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": 12,
            "workspace_id": workspace_id,
            "provider": "webhook",
            "integration_key": payload["integration_key"],
            "display_name": payload["display_name"],
            "external_form_id": payload.get("external_form_id"),
            "enabled": True,
            "mode": payload.get("mode", "production"),
            "webhook_public_id": "ffw_public",
            "webhook_path": "/api/v1/flowforge/webhooks/generic/ffw_public",
            "webhook_url": "/api/v1/flowforge/webhooks/generic/ffw_public",
            "webhook_secret": "ffweb_secret",
            "field_mapping": payload.get("field_mapping", {}),
            "source_events": payload.get("source_events", []),
            "source_fields": payload.get("source_fields", []),
            "test_recipient_overrides": [],
            "settings": {},
        }

    def list_integration_triggers(self, *, workspace_id: str, integration_config_id: int):
        return [
            {
                "id": 66,
                "workspace_id": workspace_id,
                "integration_config_id": integration_config_id,
                "trigger_key": "intake-routing",
                "display_name": "Intake Routing",
                "enabled": True,
                "priority": 50,
                "trigger_mode": "always",
                "trigger_policy": "all_matching",
                "version_strategy": "pinned",
                "workflow_definition_id": 12,
                "workflow_version_id": 13,
                "condition": {},
                "field_mapping": {"patient_name": "fields.name"},
                "no_match_config": {"notify": ["ops@example.com"]},
            }
        ]

    def create_integration_trigger(self, *, workspace_id: str, integration_config_id: int, payload, actor_user_id: str):
        self.created_trigger = {
            "workspace_id": workspace_id,
            "integration_config_id": integration_config_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": 67,
            "workspace_id": workspace_id,
            "integration_config_id": integration_config_id,
            "trigger_key": payload["trigger_key"],
            "display_name": payload["display_name"],
            "enabled": True,
            "priority": payload.get("priority", 100),
            "trigger_mode": payload.get("trigger_mode", "always"),
            "trigger_policy": payload.get("trigger_policy", "all_matching"),
            "version_strategy": payload.get("version_strategy", "pinned"),
            "workflow_definition_id": payload["workflow_definition_id"],
            "workflow_version_id": payload.get("workflow_version_id"),
            "condition": payload.get("condition", {}),
            "field_mapping": payload.get("field_mapping", {}),
            "no_match_config": payload.get("no_match_config", {}),
        }

    def accept_jotform_integration_webhook(self, *, webhook_public_id: str, payload, token: str, source_ip, headers):
        self.accepted_webhook = {
            "webhook_public_id": webhook_public_id,
            "payload": payload,
            "token": token,
            "source_ip": source_ip,
            "headers": headers,
        }
        return {
            "accepted": True,
            "duplicate": False,
            "workspace_id": "ws-1",
            "integration_id": 10,
            "integration_key": "intake-form",
            "intake_event_id": 501,
            "mode": "test",
            "source": "jotform",
            "trigger_evaluation": {
                "matched_trigger_count": 1,
                "selected_trigger_count": 1,
                "selected_triggers": [{"id": 66, "trigger_key": "intake-routing"}],
                "workflow_run_creation": "created",
            },
            "workflow_runs": [{"run_id": 901, "trigger_id": 66, "status": "waiting"}],
            "event": {
                "id": "jotform:sub-123",
                "event_type": "flowforge.integration.jotform.submission_received",
                "node_id": "intake",
                "message": "Jotform intake submission received.",
                "timestamp": "2026-05-04T00:00:00Z",
                "data": {"submission_id": "sub-123"},
            },
            "notes": ["Persisted intake event stored."],
        }

    def accept_generic_integration_webhook(self, *, webhook_public_id: str, payload, token: str, source_ip, headers):
        self.accepted_webhook = {
            "webhook_public_id": webhook_public_id,
            "payload": payload,
            "token": token,
            "source_ip": source_ip,
            "headers": headers,
        }
        return {
            "accepted": True,
            "duplicate": False,
            "workspace_id": "ws-1",
            "integration_id": 12,
            "integration_key": "webhook-intake",
            "intake_event_id": 502,
            "mode": "test",
            "source": "webhook",
            "trigger_evaluation": {
                "matched_trigger_count": 1,
                "selected_trigger_count": 1,
                "selected_triggers": [{"id": 66, "trigger_key": "intake-routing"}],
                "workflow_run_creation": "created",
            },
            "workflow_runs": [{"run_id": 902, "trigger_id": 66, "status": "waiting"}],
            "event": {
                "id": "webhook:evt-123",
                "event_type": "flowforge.integration.webhook.received",
                "node_id": "intake",
                "message": "Webhook event received.",
                "timestamp": "2026-05-04T00:00:00Z",
                "data": {"external_event_id": "evt-123"},
            },
            "notes": ["Persisted intake event stored."],
        }


def test_flowforge_integrations_route_lists_configs(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _IntegrationService())

    resp = client.get(
        "/api/v1/flowforge/integrations?provider=jotform",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
    )

    assert resp.status_code == 200
    assert resp.json[0]["integration_key"] == "intake-form"
    assert resp.json[0]["webhook_path"] == "/api/v1/flowforge/webhooks/jotform/ffj_public"
    assert resp.json[0]["source_events"][0]["event_key"] == "intake_submitted"
    assert resp.json[0]["source_fields"][0]["path"] == "serviceRequested"
    assert "webhook_secret" not in resp.json[0]


def test_flowforge_jotform_integration_route_creates_config(client, monkeypatch):
    service = _IntegrationService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    payload = {
        "integration_key": "intake-form",
        "display_name": "Intake Form",
        "external_form_id": "form-1",
        "mode": "test",
        "field_mapping": {"patient": "patientName"},
        "source_events": [{"event_key": "intake_submitted", "display_name": "Intake Submitted"}],
        "source_fields": [{"path": "serviceRequested", "label": "Requested Service", "type": "text"}],
    }
    resp = client.post(
        "/api/v1/flowforge/integrations/jotform",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json=payload,
    )

    assert resp.status_code == 201
    assert resp.json["provider"] == "jotform"
    assert resp.json["webhook_secret"] == "ffjot_secret"
    assert service.created_payload == {
        "workspace_id": "ws-1",
        "payload": payload,
        "actor_user_id": "user-1",
    }


def test_flowforge_webhook_integration_route_creates_config(client, monkeypatch):
    service = _IntegrationService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    payload = {
        "integration_key": "webhook-intake",
        "display_name": "Webhook Intake",
        "mode": "test",
        "source_events": [{"event_key": "webhook_received", "display_name": "Webhook Received"}],
        "source_fields": [{"path": "fields.summary", "label": "Summary", "type": "text"}],
    }
    resp = client.post(
        "/api/v1/flowforge/integrations/webhook",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json=payload,
    )

    assert resp.status_code == 201
    assert resp.json["provider"] == "webhook"
    assert resp.json["webhook_path"] == "/api/v1/flowforge/webhooks/generic/ffw_public"
    assert resp.json["webhook_secret"] == "ffweb_secret"
    assert service.created_payload == {
        "workspace_id": "ws-1",
        "payload": payload,
        "actor_user_id": "user-1",
    }


def test_flowforge_integration_triggers_route_lists_triggers(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _IntegrationService())

    resp = client.get(
        "/api/v1/flowforge/integrations/10/triggers",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
    )

    assert resp.status_code == 200
    assert resp.json[0]["trigger_key"] == "intake-routing"
    assert resp.json[0]["workflow_definition_id"] == 12


def test_flowforge_integration_triggers_route_creates_trigger(client, monkeypatch):
    service = _IntegrationService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    payload = {
        "trigger_key": "intake-routing",
        "display_name": "Intake Routing",
        "workflow_definition_id": 12,
        "workflow_version_id": 13,
        "field_mapping": {"patient_name": "fields.name"},
    }
    resp = client.post(
        "/api/v1/flowforge/integrations/10/triggers",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json=payload,
    )

    assert resp.status_code == 201
    assert resp.json["id"] == 67
    assert service.created_trigger == {
        "workspace_id": "ws-1",
        "integration_config_id": 10,
        "payload": payload,
        "actor_user_id": "user-1",
    }


def test_flowforge_public_jotform_webhook_uses_persisted_integration(client, monkeypatch):
    service = _IntegrationService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.post(
        "/api/v1/flowforge/webhooks/jotform/ffj_public?token=ffjot_secret",
        json={"submissionID": "sub-123"},
    )

    assert resp.status_code == 202
    assert resp.json["accepted"] is True
    assert resp.json["intake_event_id"] == 501
    assert resp.json["duplicate"] is False
    assert resp.json["trigger_evaluation"]["matched_trigger_count"] == 1
    assert resp.json["workflow_runs"][0]["run_id"] == 901
    assert service.accepted_webhook["webhook_public_id"] == "ffj_public"
    assert service.accepted_webhook["token"] == "ffjot_secret"
    assert service.accepted_webhook["payload"] == {"submissionID": "sub-123"}


def test_flowforge_public_generic_webhook_uses_persisted_integration(client, monkeypatch):
    service = _IntegrationService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.post(
        "/api/v1/flowforge/webhooks/generic/ffw_public?token=ffweb_secret",
        json={"event_key": "webhook_received", "event_id": "evt-123", "fields": {"summary": "Ready"}},
    )

    assert resp.status_code == 202
    assert resp.json["accepted"] is True
    assert resp.json["source"] == "webhook"
    assert resp.json["intake_event_id"] == 502
    assert resp.json["workflow_runs"][0]["run_id"] == 902
    assert service.accepted_webhook["webhook_public_id"] == "ffw_public"
    assert service.accepted_webhook["token"] == "ffweb_secret"
    assert service.accepted_webhook["payload"] == {
        "event_key": "webhook_received",
        "event_id": "evt-123",
        "fields": {"summary": "Ready"},
    }


def test_flowforge_resource_sets_route_lists_resource_sets(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _ResourceService())

    resp = client.get("/api/v1/flowforge/resource-sets", headers=_headers(monkeypatch))

    assert resp.status_code == 200
    assert resp.json[0]["resource_set_key"] == "therapist-pool"
    assert resp.json[0]["active_snapshot_batch_id"] == 30


def test_flowforge_resource_sets_route_creates_resource_set(client, monkeypatch):
    service = _ResourceService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.post(
        "/api/v1/flowforge/resource-sets",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json={"resource_set_key": "resource-pool", "display_name": "Resource Pool"},
    )

    assert resp.status_code == 201
    assert resp.json["id"] == 21
    assert service.created_payload == {
        "workspace_id": "ws-1",
        "payload": {"resource_set_key": "resource-pool", "display_name": "Resource Pool"},
        "actor_user_id": "user-1",
    }


def test_flowforge_resource_set_route_updates_enabled_state(client, monkeypatch):
    service = _ResourceService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.patch(
        "/api/v1/flowforge/resource-sets/20",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json={"enabled": False},
    )

    assert resp.status_code == 200
    assert resp.json["enabled"] is False
    assert service.updated_payload == {
        "workspace_id": "ws-1",
        "resource_set_id": 20,
        "payload": {"enabled": False},
        "actor_user_id": "user-1",
    }


def test_flowforge_resource_set_route_deletes_resource_set(client, monkeypatch):
    service = _ResourceService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.delete(
        "/api/v1/flowforge/resource-sets/20",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
    )

    assert resp.status_code == 200
    assert resp.json == {"deleted": True, "resource_set_id": 20}
    assert service.deleted_payload == {
        "workspace_id": "ws-1",
        "resource_set_id": 20,
        "actor_user_id": "user-1",
    }


def test_flowforge_resource_records_route_lists_records(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _ResourceService())

    resp = client.get(
        "/api/v1/flowforge/resource-sets/20/records?limit=25&offset=5",
        headers=_headers(monkeypatch),
    )

    assert resp.status_code == 200
    assert resp.json["resource_set_id"] == 20
    assert resp.json["limit"] == 25
    assert resp.json["offset"] == 5
    assert resp.json["records"][0]["source_record_key"] == "resource-1"


def test_flowforge_resource_record_route_updates_record(client, monkeypatch):
    service = _ResourceService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.patch(
        "/api/v1/flowforge/resource-sets/20/records/300",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json={"display_name": "Jane Updated", "capacity_available": 1},
    )

    assert resp.status_code == 200
    assert resp.json["display_name"] == "Jane Updated"
    assert service.updated_record_payload == {
        "workspace_id": "ws-1",
        "resource_set_id": 20,
        "record_id": 300,
        "payload": {"display_name": "Jane Updated", "capacity_available": 1},
        "actor_user_id": "user-1",
    }


def test_flowforge_resource_record_route_deletes_record(client, monkeypatch):
    service = _ResourceService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.delete(
        "/api/v1/flowforge/resource-sets/20/records/300",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
    )

    assert resp.status_code == 200
    assert resp.json == {"deleted": True, "resource_set_id": 20, "resource_record_id": 300}
    assert service.deleted_record_payload == {
        "workspace_id": "ws-1",
        "resource_set_id": 20,
        "record_id": 300,
        "actor_user_id": "user-1",
    }


def test_flowforge_resource_snapshot_batches_route_lists_batches(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _ResourceService())

    resp = client.get(
        "/api/v1/flowforge/resource-sets/20/snapshot-batches",
        headers=_headers(monkeypatch),
    )

    assert resp.status_code == 200
    assert resp.json[0]["batch_key"] == "manual-20260504"
    assert resp.json[0]["summary"] == {"message": "ok"}


def test_flowforge_manual_resource_snapshot_route_creates_snapshot(client, monkeypatch):
    service = _ResourceService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.post(
        "/api/v1/flowforge/resource-sets/20/snapshot-batches/manual",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json={
            "mode": "test",
            "records": [{"source_record_key": "resource-1", "display_name": "Jane Resource"}],
        },
    )

    assert resp.status_code == 201
    assert resp.json["snapshot_batch_id"] == 31
    assert service.created_payload == {
        "workspace_id": "ws-1",
        "resource_set_id": 20,
        "payload": {
            "mode": "test",
            "records": [{"source_record_key": "resource-1", "display_name": "Jane Resource"}],
        },
        "actor_user_id": "user-1",
    }


class _MatchingService:
    def __init__(self) -> None:
        self.created_policy = None
        self.created_version = None
        self.created_llm_draft = None
        self.accepted_llm_draft = None
        self.deleted_policy = None

    def list_matching_policies(self, *, workspace_id: str):
        return [
            {
                "id": 5,
                "workspace_id": workspace_id,
                "policy_key": "routing-policy",
                "display_name": "Routing Policy",
                "description": "Default routing rules.",
                "resource_set_id": 20,
                "status": "draft",
                "current_draft_version_id": 77,
                "latest_published_version_id": None,
            }
        ]

    def get_matching_policy(self, *, workspace_id: str, matching_policy_id: int):
        if matching_policy_id != 5:
            return None
        return self.list_matching_policies(workspace_id=workspace_id)[0]

    def create_matching_policy(self, *, workspace_id: str, payload, actor_user_id: str):
        self.created_policy = {
            "workspace_id": workspace_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": 5,
            "workspace_id": workspace_id,
            "policy_key": payload["policy_key"],
            "display_name": payload["display_name"],
            "description": payload.get("description"),
            "resource_set_id": payload["resource_set_id"],
            "status": "draft",
            "current_draft_version_id": 77,
            "latest_published_version_id": None,
        }

    def delete_matching_policy(self, *, workspace_id: str, matching_policy_id: int, actor_user_id: str):
        self.deleted_policy = {
            "workspace_id": workspace_id,
            "matching_policy_id": matching_policy_id,
            "actor_user_id": actor_user_id,
        }
        return {
            "deleted": True,
            "matching_policy_id": matching_policy_id,
            "deleted_versions": 1,
        }

    def list_matching_policy_versions(self, *, workspace_id: str, matching_policy_id: int):
        return [
            {
                "id": 77,
                "workspace_id": workspace_id,
                "matching_policy_id": matching_policy_id,
                "resource_set_id": 20,
                "version_number": 1,
                "version_status": "draft",
                "policy": {"version": 1, "eligibility": []},
                "validation_status": "valid",
                "validation_result": {"errors": [], "warnings": []},
            }
        ]

    def create_matching_policy_version(self, *, workspace_id: str, matching_policy_id: int, payload, actor_user_id: str):
        self.created_version = {
            "workspace_id": workspace_id,
            "matching_policy_id": matching_policy_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": 78,
            "workspace_id": workspace_id,
            "matching_policy_id": matching_policy_id,
            "resource_set_id": 20,
            "version_number": 2,
            "version_status": "draft",
            "policy": payload["policy"],
            "validation_status": "valid",
            "validation_result": {"errors": [], "warnings": []},
        }

    def delete_matching_policy_version(
        self,
        *,
        workspace_id: str,
        matching_policy_id: int,
        matching_policy_version_id: int,
        actor_user_id: str,
    ):
        self.deleted_version = {
            "workspace_id": workspace_id,
            "matching_policy_id": matching_policy_id,
            "matching_policy_version_id": matching_policy_version_id,
            "actor_user_id": actor_user_id,
        }
        return {
            "deleted": True,
            "matching_policy_id": matching_policy_id,
            "matching_policy_version_id": matching_policy_version_id,
        }

    def list_matching_policy_llm_drafts(self, *, workspace_id: str, matching_policy_id: int):
        return [
            {
                "id": 91,
                "workspace_id": workspace_id,
                "matching_policy_id": matching_policy_id,
                "resource_set_id": 20,
                "prompt": "Prefer available resources.",
                "generated_policy": {"version": 1, "eligibility": []},
                "plain_language_summary": "A simple draft.",
                "validation_status": "valid",
                "validation_result": {"errors": [], "warnings": []},
                "model_provider": "heuristic",
                "model_name": "flowforge-local-draft-generator",
                "status": "drafted",
            }
        ]

    def create_matching_policy_llm_draft(self, *, workspace_id: str, matching_policy_id: int, payload, actor_user_id: str):
        self.created_llm_draft = {
            "workspace_id": workspace_id,
            "matching_policy_id": matching_policy_id,
            "payload": payload,
            "actor_user_id": actor_user_id,
        }
        return {
            "id": 92,
            "workspace_id": workspace_id,
            "matching_policy_id": matching_policy_id,
            "resource_set_id": 20,
            "prompt": payload["prompt"],
            "generated_policy": {"version": 1, "eligibility": []},
            "plain_language_summary": "Generated from prompt.",
            "validation_status": "valid",
            "validation_result": {"errors": [], "warnings": []},
            "model_provider": "heuristic",
            "model_name": "flowforge-local-draft-generator",
            "status": "drafted",
        }

    def accept_matching_policy_llm_draft(
        self,
        *,
        workspace_id: str,
        matching_policy_id: int,
        draft_id: int,
        actor_user_id: str,
    ):
        self.accepted_llm_draft = {
            "workspace_id": workspace_id,
            "matching_policy_id": matching_policy_id,
            "draft_id": draft_id,
            "actor_user_id": actor_user_id,
        }
        return {
            "draft": {
                "id": draft_id,
                "workspace_id": workspace_id,
                "matching_policy_id": matching_policy_id,
                "resource_set_id": 20,
                "prompt": "Prefer available resources.",
                "generated_policy": {"version": 1, "eligibility": []},
                "plain_language_summary": "A simple draft.",
                "validation_status": "valid",
                "validation_result": {"errors": [], "warnings": []},
                "model_provider": "heuristic",
                "model_name": "flowforge-local-draft-generator",
                "status": "accepted",
            },
            "version": {
                "id": 78,
                "workspace_id": workspace_id,
                "matching_policy_id": matching_policy_id,
                "resource_set_id": 20,
                "version_number": 2,
                "version_status": "draft",
                "policy": {"version": 1, "eligibility": []},
                "validation_status": "valid",
                "validation_result": {"errors": [], "warnings": []},
            },
        }

    def validate_matching_policy(self, *, workspace_id: str, payload):
        return {
            "workspace_id": workspace_id,
            "valid": True,
            "errors": [],
            "warnings": [],
            "policy": payload["policy"],
        }

    def simulate_matching_policy(self, *, workspace_id: str, payload):
        return {
            "workspace_id": workspace_id,
            "valid": True,
            "errors": [],
            "warnings": [],
            "eligible_candidates": [],
            "excluded_candidates": [],
            "ranked_candidates": [{"source_record_key": "resource-1", "score": 5, "rank_position": 1}],
            "selected_candidate": {"source_record_key": "resource-1", "score": 5, "rank_position": 1},
            "no_match_reason": None,
        }


def test_flowforge_matching_policy_validate_route(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _MatchingService())

    resp = client.post(
        "/api/v1/flowforge/matching-policies/validate",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json={"policy": {"version": 1, "eligibility": []}},
    )

    assert resp.status_code == 200
    assert resp.json["valid"] is True
    assert resp.json["workspace_id"] == "ws-1"


def test_flowforge_matching_policy_list_route(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _MatchingService())

    resp = client.get(
        "/api/v1/flowforge/matching-policies",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
    )

    assert resp.status_code == 200
    assert resp.json[0]["policy_key"] == "routing-policy"
    assert resp.json[0]["current_draft_version_id"] == 77


def test_flowforge_matching_policy_create_route(client, monkeypatch):
    service = _MatchingService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    payload = {
        "policy_key": "routing-policy",
        "display_name": "Routing Policy",
        "resource_set_id": 20,
        "policy": {"version": 1, "eligibility": []},
    }
    resp = client.post(
        "/api/v1/flowforge/matching-policies",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json=payload,
    )

    assert resp.status_code == 201
    assert resp.json["id"] == 5
    assert service.created_policy == {
        "workspace_id": "ws-1",
        "payload": payload,
        "actor_user_id": "user-1",
    }


def test_flowforge_matching_policy_detail_route(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _MatchingService())

    resp = client.get(
        "/api/v1/flowforge/matching-policies/5",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
    )

    assert resp.status_code == 200
    assert resp.json["display_name"] == "Routing Policy"


def test_flowforge_matching_policy_delete_route(client, monkeypatch):
    service = _MatchingService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.delete(
        "/api/v1/flowforge/matching-policies/5",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
    )

    assert resp.status_code == 200
    assert resp.json == {"deleted": True, "matching_policy_id": 5, "deleted_versions": 1}
    assert service.deleted_policy == {
        "workspace_id": "ws-1",
        "matching_policy_id": 5,
        "actor_user_id": "user-1",
    }


def test_flowforge_matching_policy_versions_route(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _MatchingService())

    resp = client.get(
        "/api/v1/flowforge/matching-policies/5/versions",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
    )

    assert resp.status_code == 200
    assert resp.json[0]["id"] == 77
    assert resp.json[0]["policy"] == {"version": 1, "eligibility": []}


def test_flowforge_matching_policy_version_create_route(client, monkeypatch):
    service = _MatchingService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    payload = {"policy": {"version": 1, "eligibility": []}}
    resp = client.post(
        "/api/v1/flowforge/matching-policies/5/versions",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json=payload,
    )

    assert resp.status_code == 201
    assert resp.json["id"] == 78
    assert service.created_version == {
        "workspace_id": "ws-1",
        "matching_policy_id": 5,
        "payload": payload,
        "actor_user_id": "user-1",
    }


def test_flowforge_matching_policy_version_delete_route(client, monkeypatch):
    service = _MatchingService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.delete(
        "/api/v1/flowforge/matching-policies/5/versions/77",
        headers=_headers(monkeypatch, roles={"flowforge:designer"}),
    )

    assert resp.status_code == 200
    assert resp.json == {
        "deleted": True,
        "matching_policy_id": 5,
        "matching_policy_version_id": 77,
    }
    assert service.deleted_version == {
        "workspace_id": "ws-1",
        "matching_policy_id": 5,
        "matching_policy_version_id": 77,
        "actor_user_id": "user-1",
    }


def test_flowforge_matching_policy_llm_drafts_route_lists_drafts(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _MatchingService())

    resp = client.get(
        "/api/v1/flowforge/matching-policies/5/llm-drafts",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
    )

    assert resp.status_code == 200
    assert resp.json[0]["id"] == 91
    assert resp.json[0]["validation_status"] == "valid"


def test_flowforge_matching_policy_llm_draft_create_route(client, monkeypatch):
    service = _MatchingService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    payload = {"prompt": "Prefer active resources with available capacity."}
    resp = client.post(
        "/api/v1/flowforge/matching-policies/5/llm-drafts",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json=payload,
    )

    assert resp.status_code == 201
    assert resp.json["id"] == 92
    assert service.created_llm_draft == {
        "workspace_id": "ws-1",
        "matching_policy_id": 5,
        "payload": payload,
        "actor_user_id": "user-1",
    }


def test_flowforge_matching_policy_llm_draft_accept_route(client, monkeypatch):
    service = _MatchingService()
    monkeypatch.setattr(flowforge_routes, "_service", lambda: service)

    resp = client.post(
        "/api/v1/flowforge/matching-policies/5/llm-drafts/91/accept",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
    )

    assert resp.status_code == 201
    assert resp.json["draft"]["status"] == "accepted"
    assert resp.json["version"]["id"] == 78
    assert service.accepted_llm_draft == {
        "workspace_id": "ws-1",
        "matching_policy_id": 5,
        "draft_id": 91,
        "actor_user_id": "user-1",
    }


def test_flowforge_matching_policy_simulate_route(client, monkeypatch):
    monkeypatch.setattr(flowforge_routes, "_service", lambda: _MatchingService())

    resp = client.post(
        "/api/v1/flowforge/matching-policies/simulate",
        headers=_headers(monkeypatch, roles={"flowforge:admin"}),
        json={
            "policy": {"version": 1, "eligibility": []},
            "resources": [{"source_record_key": "resource-1"}],
            "context": {},
        },
    )

    assert resp.status_code == 200
    assert resp.json["selected_candidate"]["source_record_key"] == "resource-1"
