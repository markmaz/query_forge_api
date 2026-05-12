import json
from decimal import Decimal
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.exceptions.forge_error import ForgeError
from app.config.llm_resolver import ResolvedLLMRuntime
from app.features.flowforge.reporting.semantic_sync import FlowForgeSemanticSyncService
from app.features.flowforge.service import FlowForgeService


class _WorkflowDraftLLMClient:
    _model = "workflow-drafter"

    def __init__(self) -> None:
        self.calls = []

    def chat_json(self, **payload):
        self.calls.append(payload)
        return {
            "plain_language_summary": "Added an approval gate after intake.",
            "graph": {
                "nodes": [
                    {"id": "intake", "type": "intake", "label": "Intake", "position": {"x": 0, "y": 0}, "data": {}},
                    {
                        "id": "approval",
                        "type": "approval",
                        "label": "Approval Gate",
                        "position": {"x": 240, "y": 0},
                        "data": {"approver_role": "flowforge:operator"},
                    },
                ],
                "edges": [{"id": "intake-approval", "source": "intake", "target": "approval"}],
            },
        }


def _workflow_draft_runtime_builder(client: _WorkflowDraftLLMClient):
    def _builder(**payload):
        return ResolvedLLMRuntime(
            client=client,
            source="workspace_role",
            role=payload["role"],
            workspace_id=payload["workspace_id"],
            llm_id=88,
            provider="openai",
            model="workflow-drafter",
            endpoint="https://example.invalid/v1",
        )

    return _builder


class _ResourceRepo:
    def __init__(self, *, active_snapshot_batch_id: int | None = 30) -> None:
        self.active_snapshot_batch_id = active_snapshot_batch_id
        self.created_payload = None
        self.created_batch = None
        self.created_records = []
        self.upserted_records = []
        self.updated_enabled = None
        self.archived_resource_set = None
        self.updated_record = None
        self.deleted_record = None

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
                "active_snapshot_batch_id": self.active_snapshot_batch_id,
                "settings_json": {},
            }
        ]

    def create_resource_set(self, **payload):
        self.created_payload = payload
        return {
            "id": 21,
            "workspace_id": payload["workspace_id"],
            "resource_set_key": payload["resource_set_key"],
            "display_name": payload["display_name"],
            "description": payload["description"],
            "source_type": payload["source_type"],
            "enabled": True,
            "active_snapshot_batch_id": None,
            "settings_json": payload["settings"],
        }

    def list_snapshot_records(self, *, workspace_id: str, resource_set_id: int, limit: int, offset: int):
        return [
            {
                "id": 300,
                "workspace_id": workspace_id,
                "resource_set_id": resource_set_id,
                "source_record_key": "resource-1",
                "display_name": "Jane Resource",
                "primary_email": "jane@example.com",
                "effective_status": "active",
                "availability_status": "available",
                "status": "active",
                "capacity_total": Decimal("5.00"),
                "capacity_used": Decimal("2.50"),
                "capacity_available": Decimal("2.50"),
                "current_load": Decimal("2.50"),
                "service_area": "Austin",
                "timezone": "America/Chicago",
                "source_missing": False,
                "tags_json": ["telehealth"],
                "attributes_json": {"languages": ["Spanish"]},
                "normalized_profile_json": {"display_name": "Jane Resource"},
                "validation_status": "valid",
                "validation_errors_json": [],
            }
        ]

    def list_snapshot_batches(self, *, workspace_id: str, resource_set_id: int, limit: int):
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
                "summary_json": {"message": "ok"},
            }
        ][:limit]

    def create_snapshot_batch(self, **payload):
        self.created_batch = payload
        return 31

    def create_snapshot_record(self, **payload):
        self.created_records.append(payload)
        return 300 + len(self.created_records)

    def upsert_snapshot_record(self, **payload):
        self.upserted_records.append(payload)
        return 300 + len(self.upserted_records)

    def complete_snapshot_batch(self, **payload):
        return True

    def activate_snapshot_batch(self, **payload):
        return True

    def get_snapshot_record_by_id(self, *, workspace_id: str, resource_set_id: int, record_id: int):
        if record_id != 300:
            return None
        return self.list_snapshot_records(workspace_id=workspace_id, resource_set_id=resource_set_id, limit=1, offset=0)[0]

    def update_snapshot_record(self, **payload):
        self.updated_record = payload
        return True

    def delete_snapshot_record(self, **payload):
        self.deleted_record = payload
        return True

    def get_resource_set(self, *, workspace_id: str, resource_set_id: int):
        if resource_set_id != 20:
            return None
        return self.list_resource_sets(workspace_id=workspace_id)[0]

    def update_resource_set_enabled(self, **payload):
        self.updated_enabled = payload
        return True

    def archive_resource_set(self, **payload):
        self.archived_resource_set = payload
        return True


class _MatchingRepo:
    def __init__(self) -> None:
        self.created_policy = None
        self.created_version = None
        self.current_draft = None
        self.created_llm_draft = None
        self.reviewed_draft = None
        self.deleted_policy = None
        self.deleted_policy_versions = None
        self.deleted_version = None
        self.cleared_current_draft = None
        self.versions = [
            {
                "id": 77,
                "workspace_id": "ws-1",
                "matching_policy_id": 5,
                "resource_set_id": 20,
                "version_number": 1,
                "version_status": "draft",
                "policy_json": {"version": 1, "eligibility": []},
                "validation_status": "valid",
                "validation_result_json": {"errors": [], "warnings": []},
            }
        ]
        self.llm_drafts = [
            {
                "id": 91,
                "workspace_id": "ws-1",
                "matching_policy_id": 5,
                "resource_set_id": 20,
                "prompt": "Prefer available resources.",
                "generated_policy_json": {"version": 1, "eligibility": []},
                "plain_language_summary": "A simple draft.",
                "validation_status": "valid",
                "validation_result_json": {"errors": [], "warnings": []},
                "model_provider": "heuristic",
                "model_name": "flowforge-local-draft-generator",
                "status": "drafted",
            }
        ]

    def list_policies(self, *, workspace_id: str):
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

    def get_policy(self, *, workspace_id: str, matching_policy_id: int):
        if matching_policy_id != 5:
            return None
        return self.list_policies(workspace_id=workspace_id)[0]

    def create_policy(self, **payload):
        self.created_policy = payload
        return {
            "id": 5,
            "workspace_id": payload["workspace_id"],
            "policy_key": payload["policy_key"],
            "display_name": payload["display_name"],
            "description": payload["description"],
            "resource_set_id": payload["resource_set_id"],
            "status": "draft",
            "current_draft_version_id": None,
            "latest_published_version_id": None,
        }

    def archive_policy(self, **payload):
        self.deleted_policy = payload
        return True

    def delete_non_published_policy_versions(self, **payload):
        self.deleted_policy_versions = payload
        return 1

    def list_policy_versions(self, *, workspace_id: str, matching_policy_id: int):
        del workspace_id, matching_policy_id
        return list(self.versions)

    def create_policy_version(self, **payload):
        self.created_version = payload
        return 78

    def set_current_draft_version(self, **payload):
        self.current_draft = payload
        return True

    def get_policy_version(self, *, workspace_id: str, version_id: int):
        del workspace_id
        return next((row for row in self.versions if row["id"] == version_id), None)

    def delete_policy_version(self, **payload):
        self.deleted_version = payload
        return True

    def clear_current_draft_version(self, **payload):
        self.cleared_current_draft = payload
        return True

    def list_llm_drafts(self, *, workspace_id: str, matching_policy_id: int):
        del workspace_id, matching_policy_id
        return list(self.llm_drafts)

    def get_llm_draft(self, *, workspace_id: str, matching_policy_id: int, draft_id: int):
        del workspace_id, matching_policy_id
        return next((row for row in self.llm_drafts if row["id"] == draft_id), None)

    def create_llm_draft(self, **payload):
        self.created_llm_draft = payload
        return {
            "id": 92,
            "workspace_id": payload["workspace_id"],
            "matching_policy_id": payload["matching_policy_id"],
            "resource_set_id": payload["resource_set_id"],
            "prompt": payload["prompt"],
            "generated_policy_json": payload["generated_policy"],
            "plain_language_summary": payload["plain_language_summary"],
            "validation_status": payload["validation_status"],
            "validation_result_json": payload["validation_result"],
            "model_provider": payload["model_provider"],
            "model_name": payload["model_name"],
            "status": payload["status"],
        }

    def mark_llm_draft_reviewed(self, **payload):
        self.reviewed_draft = payload
        return True


class _WorkflowRepo:
    def __init__(self) -> None:
        self.published = None
        self.created_definition = None
        self.created_version = None
        self.current_draft = None
        self.grants = []
        self.revocations = []
        self.owner_update = None
        self.run_as_update = None
        self.acl = [
            {
                "id": 70,
                "principal_type": "user",
                "principal_id": "user-1",
                "permission": "owner",
                "granted_by": "user-1",
                "granted_at": datetime(2026, 5, 9, 12, 0, 0),
            }
        ]
        self.definitions = [
            {
                "id": 12,
                "workflow_key": "intake-routing",
                "name": "Intake Routing",
                "description": "Routes intake submissions.",
                "owner_user_id": "user-1",
                "owner_display_name": "Taylor Jordan",
                "created_by": "user-1",
                "run_as_principal_type": "user",
                "run_as_principal_id": "user-1",
                "run_as_user_display_name": "Taylor Jordan",
                "lifecycle": "development",
                "status": "draft",
                "graph_json": {"nodes": [{"id": "intake"}], "edges": []},
                "created_at": datetime(2026, 5, 7, 20, 27, 25),
                "updated_at": datetime(2026, 5, 8, 20, 27, 25),
            }
        ]
        self.versions = [
            {
                "id": 44,
                "workspace_id": "ws-1",
                "workflow_definition_id": 12,
                "version_number": 1,
                "version_status": "draft",
                "graph_json": {"nodes": [{"id": "intake"}], "edges": []},
                "validation_status": "valid",
                "validation_result_json": {"errors": [], "warnings": []},
                "matching_policy_refs_json": [],
                "settings_json": {},
                "created_at": datetime(2026, 5, 7, 20, 27, 25),
                "published_at": None,
            }
        ]

    def list_workflow_definitions(self, *, workspace_id: str):
        del workspace_id
        return list(self.definitions)

    def get_workflow_definition(self, *, workspace_id: str, workflow_definition_id: int):
        del workspace_id
        return next((row for row in self.definitions if row["id"] == workflow_definition_id), None)

    def create_workflow_definition(self, **payload):
        self.created_definition = payload
        return 12

    def grant_workflow_permission(self, **payload):
        self.granted_workflow_permission = payload
        self.grants.append(payload)
        return 70

    def revoke_workflow_permission(self, **payload):
        self.revocations.append(payload)
        return True

    def list_workflow_acl(self, *, workspace_id: str, workflow_definition_id: int):
        del workspace_id, workflow_definition_id
        return list(self.acl)

    def update_workflow_owner(self, **payload):
        self.owner_update = payload
        self.definitions[0]["owner_user_id"] = payload["owner_user_id"]
        return True

    def update_workflow_metadata(self, **payload):
        self.metadata_update = payload
        self.definitions[0]["name"] = payload["name"]
        self.definitions[0]["description"] = payload["description"]
        return True

    def update_workflow_run_as(self, **payload):
        self.run_as_update = payload
        self.definitions[0]["run_as_principal_type"] = payload["principal_type"]
        self.definitions[0]["run_as_principal_id"] = payload["principal_id"]
        return True

    def create_workflow_version(self, **payload):
        self.created_version = payload
        return 45

    def set_current_draft_version(self, **payload):
        self.current_draft = payload
        return True

    def list_workflow_versions(self, *, workspace_id: str, workflow_definition_id: int):
        del workspace_id, workflow_definition_id
        return list(self.versions)

    def get_workflow_version(self, *, workspace_id: str, workflow_definition_id: int, version_id: int):
        del workspace_id, workflow_definition_id
        return next((row for row in self.versions if row["id"] == version_id), None)

    def publish_workflow_version(self, **payload):
        self.published = payload
        return True

    def archive_workflow_definition(self, **payload):
        self.archived_definition = payload
        return True


class _WorkflowPermissionService:
    def __init__(self, *, viewable_ids=None, denied_permissions=None) -> None:
        self.viewable_ids = {int(value) for value in (viewable_ids or [])}
        self.denied_permissions = set(denied_permissions or [])
        self.ensure_calls = []
        self.view_calls = []

    def can_view_workflow(self, *, workflow_definition, **payload):
        self.view_calls.append({"workflow_definition": workflow_definition, **payload})
        return int(workflow_definition["id"]) in self.viewable_ids

    def effective_permission(self, **payload):
        del payload
        return "owner"

    def ensure(self, *, required_permission: str, **payload):
        self.ensure_calls.append({"required_permission": required_permission, **payload})
        if required_permission in self.denied_permissions:
            raise ForgeError(f"Workflow permission '{required_permission}' is required.", status_code=403)
        return required_permission


class _IntegrationRepo:
    def __init__(self) -> None:
        self.created_config = None
        self.created_intake_event = None
        self.created_trigger = None
        self.existing_intake_event = None
        self.updated_trigger_evaluation = None
        self.secret_hash = FlowForgeService()._hash_webhook_secret("ffjot_secret")

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
                "secret_hash": self.secret_hash,
                "field_mapping_json": {"patient": "patientName"},
                "test_recipient_overrides_json": ["ops@example.com"],
                "settings_json": {
                    "trigger_policy": "all_matching",
                    "source_events": [
                        {"event_key": "intake_submitted", "display_name": "Intake Submitted"},
                        {"event_key": "intake_updated", "display_name": "Intake Updated", "description": "Follow-up update."},
                    ],
                    "source_fields": [
                        {"path": "serviceRequested", "label": "Requested Service", "type": "text", "required": True},
                        {"path": "summary", "label": "Clinical Summary", "type": "text", "sensitive": True},
                    ],
                },
            }
        ]

    def create_integration_config(self, **payload):
        self.created_config = payload
        return {
            "id": 11,
            "workspace_id": payload["workspace_id"],
            "provider": payload["provider"],
            "integration_key": payload["integration_key"],
            "display_name": payload["display_name"],
            "external_form_id": payload["external_form_id"],
            "enabled": True,
            "mode": payload["mode"],
            "webhook_public_id": payload["webhook_public_id"],
            "field_mapping_json": payload["field_mapping"],
            "test_recipient_overrides_json": payload["test_recipient_overrides"],
            "settings_json": payload["settings"],
        }

    def get_integration_config_by_public_id(self, *, webhook_public_id: str):
        if webhook_public_id == "ffw_public":
            row = self.list_integration_configs(workspace_id="ws-1")[0]
            row["id"] = 12
            row["provider"] = "webhook"
            row["integration_key"] = "webhook-intake"
            row["display_name"] = "Webhook Intake"
            row["external_form_id"] = None
            row["webhook_public_id"] = "ffw_public"
            return row
        if webhook_public_id != "ffj_public":
            return None
        row = self.list_integration_configs(workspace_id="ws-1")[0]
        row["id"] = 10
        return row

    def get_integration_config(self, *, workspace_id: str, integration_config_id: int):
        if workspace_id != "ws-1" or integration_config_id != 10:
            return None
        return self.list_integration_configs(workspace_id=workspace_id)[0]

    def list_integration_triggers(self, *, workspace_id: str, integration_config_id: int):
        if workspace_id != "ws-1" or integration_config_id not in {10, 12}:
            return []
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
                "condition_json": {"fields.patientType": "new"},
                "field_mapping_json": {"patient_name": "fields.name"},
                "no_match_config_json": {"notify": ["ops@example.com"]},
            }
        ]

    def create_integration_trigger(self, **payload):
        self.created_trigger = payload
        return {
            "id": 67,
            "workspace_id": payload["workspace_id"],
            "integration_config_id": payload["integration_config_id"],
            "trigger_key": payload["trigger_key"],
            "display_name": payload["display_name"],
            "enabled": True,
            "priority": payload["priority"],
            "trigger_mode": payload["trigger_mode"],
            "trigger_policy": payload["trigger_policy"],
            "version_strategy": payload["version_strategy"],
            "workflow_definition_id": payload["workflow_definition_id"],
            "workflow_version_id": payload["workflow_version_id"],
            "condition_json": payload["condition"],
            "field_mapping_json": payload["field_mapping"],
            "no_match_config_json": payload["no_match_config"],
        }

    def get_intake_event_by_idempotency(self, *, workspace_id: str, idempotency_key: str):
        del workspace_id, idempotency_key
        return self.existing_intake_event

    def create_intake_event(self, **payload):
        self.created_intake_event = payload
        return 501

    def update_intake_event_trigger_evaluation(self, **payload):
        self.updated_trigger_evaluation = payload
        return True


class _RuntimeRepo:
    def __init__(self) -> None:
        self.created_runs = []
        self.created_events = []
        self.created_tokens = []
        self.created_notifications = []
        self.used_token = None
        self.updated_task = None
        self.updated_run_status = None
        self.existing_run = None
        self.runs = [
            {
                "id": 90,
                "workspace_id": "ws-1",
                "workflow_definition_id": 12,
                "workflow_version_id": 13,
                "intake_event_id": 501,
                "mode": "test",
                "run_as_principal_type": "user",
                "run_as_principal_id": "operator-1",
                "run_as_principal_display_name": "Olivia Operator",
                "triggered_by_user_id": "operator-1",
                "triggered_by_display_name": "Olivia Operator",
                "status": "waiting",
                "current_node_id": "intake",
                "idempotency_key": "intake:501:trigger:66",
                "run_context_json": {"trigger_key": "intake-routing"},
                "started_at": datetime(2026, 5, 11, 21, 6, 0),
                "completed_at": None,
                "failed_at": None,
                "created_at": datetime(2026, 5, 11, 21, 6, 0),
                "updated_at": datetime(2026, 5, 11, 21, 6, 1),
            }
        ]
        self.events = [
            {
                "id": 801,
                "workspace_id": "ws-1",
                "run_id": 90,
                "event_type": "workflow.run.created",
                "node_id": "intake",
                "message": "Workflow run created from integration trigger.",
                "event_payload_json": {"trigger_key": "intake-routing"},
                "actor_type": "system",
                "actor_id": "flowforge",
                "created_at": datetime(2026, 5, 11, 21, 6, 0),
            }
        ]
        self.human_tasks = [
            {
                "id": 301,
                "workspace_id": "ws-1",
                "run_id": 90,
                "task_type": "offer",
                "resource_set_id": 20,
                "source_record_key": "resource-1",
                "status": "pending",
                "assigned_to_principal_type": "resource",
                "assigned_to_principal_id": "resource-1",
                "due_at": datetime(2026, 5, 5, 12, 0, 0),
                "completed_at": None,
                "response_json": {"allowed_actions": ["accept", "decline"]},
                "created_at": datetime(2026, 5, 5, 10, 0, 0),
                "updated_at": datetime(2026, 5, 5, 10, 0, 1),
            },
            {
                "id": 302,
                "workspace_id": "ws-1",
                "run_id": 90,
                "task_type": "approval",
                "resource_set_id": None,
                "source_record_key": None,
                "status": "waiting",
                "assigned_to_principal_type": "group",
                "assigned_to_principal_id": "flowforge:operator",
                "due_at": None,
                "completed_at": None,
                "response_json": {
                    "allowed_actions": ["approve", "decline"],
                    "approval": {"approval_reason": "Review export.", "destination_key": "ops-export"},
                },
            },
        ]
        self.notifications = [
            {
                "id": 701,
                "workspace_id": "ws-1",
                "run_id": 90,
                "human_task_id": None,
                "channel": "email",
                "recipient": "ops@example.com",
                "template_key": "flowforge.no_match",
                "status": "pending",
                "idempotency_key": "no-match:90:ops@example.com",
                "payload_summary_json": {"reason": "No eligible resources."},
                "created_at": datetime(2026, 5, 12, 10, 11, 28),
                "sent_at": None,
                "failed_at": datetime(2026, 5, 12, 10, 11, 52),
            }
        ]

    def get_run_by_idempotency(self, *, workspace_id: str, idempotency_key: str):
        del workspace_id, idempotency_key
        return self.existing_run

    def create_run(self, **payload):
        self.created_runs.append(payload)
        return 900 + len(self.created_runs)

    def append_run_event(self, **payload):
        self.created_events.append(payload)
        return 800 + len(self.created_events)

    def list_runs(self, *, workspace_id: str, status: str | None, mode: str | None, limit: int, offset: int):
        del workspace_id, status, mode
        return self.runs[offset : offset + limit]

    def get_latest_run_for_workflow(self, *, workspace_id: str, workflow_definition_id: int):
        del workspace_id
        runs = [row for row in self.runs if row["workflow_definition_id"] == workflow_definition_id]
        return runs[-1] if runs else None

    def get_run(self, *, workspace_id: str, run_id: int):
        del workspace_id
        return next((row for row in self.runs if row["id"] == run_id), None)

    def list_run_events(self, *, workspace_id: str, run_id: int, limit: int):
        del workspace_id
        return [row for row in self.events if row["run_id"] == run_id][:limit]

    def list_run_human_tasks(self, *, workspace_id: str, run_id: int, limit: int):
        del workspace_id
        return [row for row in self.human_tasks if row["run_id"] == run_id][:limit]

    def list_human_tasks(self, *, workspace_id: str, task_type: str | None, statuses: list[str] | None, limit: int, offset: int):
        del workspace_id
        rows = self.human_tasks
        if task_type:
            rows = [row for row in rows if row["task_type"] == task_type]
        if statuses:
            rows = [row for row in rows if row["status"] in statuses]
        return rows[offset : offset + limit]

    def get_human_task(self, *, workspace_id: str, human_task_id: int):
        del workspace_id
        return next((row for row in self.human_tasks if row["id"] == human_task_id), None)

    def create_signed_action_token(self, **payload):
        self.created_tokens.append(payload)
        return 400 + len(self.created_tokens)

    def get_signed_action_token(self, *, token_hash: str):
        if token_hash != "token-hash":
            return None
        task = self.human_tasks[0]
        return {
            "id": 401,
            "workspace_id": "ws-1",
            "human_task_id": task["id"],
            "token_hash": token_hash,
            "allowed_actions_json": ["accept", "decline"],
            "expires_at": "2099-01-01 00:00:00",
            "used_at": None,
            "used_action": None,
            "revoked_at": None,
            "task_type": task["task_type"],
            "run_id": task["run_id"],
            "task_status": task["status"],
            "resource_set_id": task["resource_set_id"],
            "source_record_key": task["source_record_key"],
            "response_json": task["response_json"],
        }

    def mark_signed_action_token_used(self, **payload):
        self.used_token = payload
        return True

    def update_human_task_response(self, **payload):
        self.updated_task = payload
        return True

    def update_run_status(self, **payload):
        self.updated_run_status = payload
        return True

    def create_notification(self, **payload):
        self.created_notifications.append(payload)
        return 700 + len(self.created_notifications)

    def list_run_notifications(self, *, workspace_id: str, run_id: int, limit: int):
        del workspace_id
        return [row for row in self.notifications if row["run_id"] == run_id][:limit]

    def get_report_summary(self, *, workspace_id: str, mode: str | None):
        return {
            "workspace_id": workspace_id,
            "mode": mode,
            "run_count": 10,
            "active_run_count": 3,
            "completed_run_count": 4,
            "failed_run_count": 1,
            "needs_attention_count": 2,
            "test_run_count": 2,
            "production_run_count": 8,
        }

    def get_reporting_dashboard_metrics(self, *, workspace_id: str, mode: str):
        return {
            "workspace_id": workspace_id,
            "mode": mode,
            "run_count": 8,
            "active_run_count": 2,
            "completed_run_count": 4,
            "failed_run_count": 1,
            "needs_attention_count": 1,
            "intake_event_count": 9,
            "matching_evaluation_count": 7,
            "no_match_outcome_count": 2,
            "resource_snapshot_record_count": 25,
            "available_resource_count": 18,
            "offer_count": 6,
            "pending_offer_count": 1,
            "completed_offer_count": 5,
            "assignment_count": 4,
            "notification_count": 12,
            "pending_notification_count": 3,
            "failed_notification_count": 1,
            "dataset_artifact_count": 11,
            "expired_dataset_artifact_count": 2,
            "retention_pending_artifact_count": 1,
            "data_movement_audit_count": 13,
            "failed_import_count": 1,
            "failed_export_count": 2,
        }

    def list_intake_review_events(self, *, workspace_id: str, mode: str, days: int):
        today = date.today()
        return [
            {
                "intake_event_id": 501,
                "intake_date": today,
                "received_at": datetime.combine(today, datetime.min.time()),
                "provider": "jotform",
                "external_submission_id": "sub-501",
                "run_id": 90,
                "run_status": "completed",
                "workflow_key": "intake-routing",
                "assignment_id": 701,
                "assignment_status": "assigned",
                "accepted_resource_set_id": 20,
                "accepted_source_record_key": "dr-lane",
                "accepted_resource_display_name": "Dr. Lane",
                "no_match_reason": None,
                "raw_payload_redacted_at": None,
            },
            {
                "intake_event_id": 502,
                "intake_date": today,
                "received_at": datetime.combine(today, datetime.min.time()),
                "provider": "jotform",
                "external_submission_id": "sub-502",
                "run_id": 91,
                "run_status": "needs_attention",
                "workflow_key": "intake-routing",
                "assignment_id": None,
                "assignment_status": None,
                "accepted_resource_set_id": None,
                "accepted_source_record_key": None,
                "accepted_resource_display_name": None,
                "no_match_reason": "no_eligible_candidates",
                "raw_payload_redacted_at": None,
            },
        ]

    def get_intake_raw_form(self, *, workspace_id: str, intake_event_id: int):
        return {
            "intake_event_id": intake_event_id,
            "provider": "jotform",
            "external_form_id": "form-1",
            "external_submission_id": "sub-502",
            "mode": "production",
            "received_at": datetime(2026, 5, 5, 11, 0, 0),
            "raw_payload_available": True,
            "raw_payload_redacted_at": None,
            "raw_payload_redacted_by": None,
            "raw_payload_expires_at": datetime(2026, 6, 4, 11, 0, 0),
            "raw_payload_json": {"patient": {"first_name": "Jane"}},
            "normalized_payload_json": {"requested_service": "therapy"},
        }


class _SettingsRepo:
    def __init__(self) -> None:
        self.updated_payload = None
        self.current = {
            "workspace_id": "ws-1",
            "enabled": False,
            "allow_designer_publish": False,
            "block_sensitive_reporting_mcp": False,
            "allow_user_run_as_for_production": False,
            "require_service_principal_for_automated_triggers": True,
            "raw_payload_retention_days": 30,
            "raw_payload_retention_max_days": 90,
            "default_offer_timeout_minutes": 1440,
            "default_no_match_recipients": ["ops-default@example.com"],
            "default_test_recipients": [],
            "settings": {},
        }

    def get_settings(self, *, workspace_id: str):
        return {**self.current, "workspace_id": workspace_id}

    def upsert_settings(self, *, workspace_id: str, payload):
        self.updated_payload = {"workspace_id": workspace_id, "payload": payload}
        return {**self.get_settings(workspace_id=workspace_id), **payload}


class _DataMovementRepo:
    def __init__(self) -> None:
        self.created_artifact = None
        self.created_audit = None
        self.upserted_source = None
        self.upserted_destination = None
        self.updated_source_enabled = None
        self.updated_destination_enabled = None
        self.artifacts = [
            {
                "id": 10,
                "workspace_id": "ws-1",
                "run_id": 90,
                "node_id": "extract-1",
                "artifact_key": "run-90-extract",
                "artifact_type": "query_extract",
                "storage_kind": "metadata_only",
                "storage_ref_json": {"query_id": "saved-1"},
                "schema_json": {"columns": ["id"]},
                "row_count": 12,
                "byte_count": 512,
                "checksum": "sha256:abc",
                "status": "ready",
            }
        ]
        self.sources = [
            {
                "id": 20,
                "workspace_id": "ws-1",
                "source_key": "jotform-intake",
                "display_name": "Jotform Intake",
                "source_type": "jotform",
                "enabled": True,
                "mode": "test",
                "config_json": {"api_key": "secret", "form_id": "abc"},
            }
        ]
        self.destinations = [
            {
                "id": 21,
                "workspace_id": "ws-1",
                "destination_key": "ops-email",
                "display_name": "Ops Email",
                "destination_type": "email",
                "enabled": True,
                "mode": "test",
                "config_json": {"token": "secret", "to": ["ops@example.com"]},
            }
        ]

    def create_dataset_artifact(self, **payload):
        self.created_artifact = payload
        row = {
            "id": 11,
            "workspace_id": payload["workspace_id"],
            "run_id": payload["run_id"],
            "node_id": payload["node_id"],
            "artifact_key": payload["artifact_key"],
            "artifact_type": payload["artifact_type"],
            "storage_kind": payload["storage_kind"],
            "storage_ref_json": payload["storage_ref"],
            "schema_json": payload["schema"],
            "row_count": payload["row_count"],
            "byte_count": payload["byte_count"],
            "checksum": payload["checksum"],
            "status": payload["status"],
            "expires_at": payload["expires_at"],
        }
        self.artifacts.append(row)
        return row

    def list_dataset_artifacts(self, *, workspace_id: str, run_id: int | None, limit: int, offset: int):
        rows = [row for row in self.artifacts if row["workspace_id"] == workspace_id and (run_id is None or row["run_id"] == run_id)]
        return rows[offset : offset + limit]

    def get_dataset_artifact(self, *, workspace_id: str, artifact_id: int):
        return next((row for row in self.artifacts if row["workspace_id"] == workspace_id and row["id"] == artifact_id), None)

    def create_data_movement_audit(self, **payload):
        self.created_audit = payload
        return {
            "id": 30,
            "workspace_id": payload["workspace_id"],
            "run_id": payload["run_id"],
            "node_id": payload["node_id"],
            "action_type": payload["action_type"],
            "status": payload["status"],
            "source_key": payload["source_key"],
            "destination_key": payload["destination_key"],
            "dataset_artifact_id": payload["dataset_artifact_id"],
            "resource_set_id": payload["resource_set_id"],
            "actor_type": payload["actor_type"],
            "actor_id": payload["actor_id"],
            "request_json": payload["request"],
            "result_json": payload["result"],
            "error_message": payload["error_message"],
            "idempotency_key": payload["idempotency_key"],
            "completed_at": payload["completed_at"],
        }

    def list_data_movement_audit(self, *, workspace_id: str, run_id: int | None, limit: int, offset: int):
        del workspace_id, run_id, limit, offset
        return []

    def upsert_data_source(self, **payload):
        self.upserted_source = payload
        row = {
            "id": 22,
            "workspace_id": payload["workspace_id"],
            "source_key": payload["source_key"],
            "display_name": payload["display_name"],
            "source_type": payload["source_type"],
            "enabled": payload["enabled"],
            "mode": payload["mode"],
            "config_json": payload["config"],
        }
        self.sources = [existing for existing in self.sources if existing["source_key"] != row["source_key"]]
        self.sources.append(row)
        return row

    def list_data_sources(self, *, workspace_id: str):
        return [row for row in self.sources if row["workspace_id"] == workspace_id]

    def get_data_source_by_key(self, *, workspace_id: str, source_key: str):
        return next((row for row in self.sources if row["workspace_id"] == workspace_id and row["source_key"] == source_key), None)

    def update_data_source_enabled(self, **payload):
        self.updated_source_enabled = payload
        source = self.get_data_source_by_key(workspace_id=payload["workspace_id"], source_key=payload["source_key"])
        if not source:
            return False
        source["enabled"] = payload["enabled"]
        return True

    def upsert_data_destination(self, **payload):
        self.upserted_destination = payload
        row = {
            "id": 23,
            "workspace_id": payload["workspace_id"],
            "destination_key": payload["destination_key"],
            "display_name": payload["display_name"],
            "destination_type": payload["destination_type"],
            "enabled": payload["enabled"],
            "mode": payload["mode"],
            "config_json": payload["config"],
        }
        self.destinations = [existing for existing in self.destinations if existing["destination_key"] != row["destination_key"]]
        self.destinations.append(row)
        return row

    def list_data_destinations(self, *, workspace_id: str):
        return [row for row in self.destinations if row["workspace_id"] == workspace_id]

    def get_data_destination_by_key(self, *, workspace_id: str, destination_key: str):
        return next((row for row in self.destinations if row["workspace_id"] == workspace_id and row["destination_key"] == destination_key), None)

    def update_data_destination_enabled(self, **payload):
        self.updated_destination_enabled = payload
        destination = self.get_data_destination_by_key(
            workspace_id=payload["workspace_id"],
            destination_key=payload["destination_key"],
        )
        if not destination:
            return False
        destination["enabled"] = payload["enabled"]
        return True


class _DraftGenerator:
    def __init__(self, *, generated_policy=None) -> None:
        self.generated_policy = generated_policy or {
            "version": 1,
            "resource_set_id": 20,
            "eligibility": [{"field": "effective_status", "operator": "equals", "value": "active"}],
        }
        self.calls = []

    def generate(self, **payload):
        self.calls.append(payload)
        return {
            "generated_policy": self.generated_policy,
            "plain_language_summary": "Generated from prompt.",
            "model_provider": "test",
            "model_name": "fake-model",
            "draft_source": "llm",
        }


class _FakeFlowForgeRuleDraftingLLM:
    _model = "fake-flowforge-model"

    def chat_json(self, **payload):
        return {
            "policy": {
                "version": 1,
                "resource_set_id": 20,
                "eligibility": {
                    "all": [
                        {"field": "effective_status", "op": "eq", "value": "active"},
                        {
                            "field": "languages",
                            "op": "contains_any",
                            "value_from": "inputs.preferred_languages",
                        },
                    ]
                },
                "scoring": {
                    "rules": [
                        {
                            "name": "Capacity available",
                            "when": {"field": "capacity_available", "op": "gt", "value": 0},
                            "points": 5,
                        }
                    ]
                },
            },
            "plain_language_summary": "Generated from workspace-configured FlowForge LLM.",
        }


class _EmptyWorkflowRepo:
    def list_workflow_definitions(self, *, workspace_id: str):
        del workspace_id
        return []


def test_flowforge_service_lists_only_persisted_workflows():
    workflows = FlowForgeService(workflow_repository=_EmptyWorkflowRepo()).list_definitions(workspace_id="ws-1")

    assert workflows == []


def test_flowforge_service_lists_persisted_workflows_without_builtin_starters():
    service = FlowForgeService(workflow_repository=_WorkflowRepo())

    workflows = service.list_definitions(workspace_id="ws-1")

    assert [workflow["id"] for workflow in workflows] == ["12"]
    assert workflows[0]["name"] == "Intake Routing"
    assert workflows[0]["created_at"] == "2026-05-07T20:27:25"
    assert workflows[0]["updated_at"] == "2026-05-08T20:27:25"


def test_flowforge_service_returns_design_preview_for_persisted_workflow():
    service = FlowForgeService(workflow_repository=_WorkflowRepo())

    result = service.get_run_inspector(workspace_id="ws-1", workflow_id="12")

    assert result is not None
    assert result["mode"] == "design_preview"
    assert result["status"] == "ready"
    assert result["events"][0]["event_type"] == "workflow.preview.node"
    assert result["notes"][0] == "This preview summarizes the workflow graph before runtime execution."


def test_flowforge_validation_allows_loops_as_warnings():
    graph = {
        "nodes": [
            {"id": "start", "type": "intake", "label": "Start", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "wait", "type": "wait", "label": "Wait", "position": {"x": 200, "y": 0}, "data": {}},
        ],
        "edges": [
            {"id": "start-wait", "source": "start", "target": "wait"},
            {"id": "wait-start", "source": "wait", "target": "start"},
        ],
    }

    result = FlowForgeService().validate_graph(graph=graph)

    assert result["valid"] is True
    assert result["errors"] == []
    assert any("loop" in warning.lower() for warning in result["warnings"])


def test_flowforge_service_creates_persisted_workflow_draft():
    repo = _WorkflowRepo()
    service = FlowForgeService(workflow_repository=repo, integration_repository=_IntegrationRepo())

    result = service.create_workflow_definition(
        workspace_id="ws-1",
        payload={
            "workflow_key": "new-routing",
            "name": "New Routing",
            "description": "A new workflow.",
            "graph": {
                "nodes": [
                    {"id": "intake", "type": "intake", "data": {"source": "intake-form", "event": "intake_submitted"}}
                ],
                "edges": [],
            },
        },
        actor_user_id="user-1",
    )

    assert result["id"] == "12"
    assert repo.created_definition["workflow_key"] == "new-routing"
    assert repo.granted_workflow_permission == {
        "workspace_id": "ws-1",
        "workflow_definition_id": 12,
        "principal_type": "user",
        "principal_id": "user-1",
        "permission": "owner",
        "granted_by": "user-1",
    }
    assert repo.created_version["validation_status"] == "valid"
    assert repo.current_draft["version_id"] == 45


def test_flowforge_service_filters_workflow_definitions_by_object_permission():
    repo = _WorkflowRepo()
    repo.definitions.append(
        {
            "id": 13,
            "workflow_key": "hidden-routing",
            "name": "Hidden Routing",
            "description": "Hidden workflow.",
            "owner_user_id": "other-user",
            "created_by": "other-user",
            "status": "draft",
            "graph_json": {"nodes": [{"id": "hidden"}], "edges": []},
        }
    )
    permission_service = _WorkflowPermissionService(viewable_ids={12})
    service = FlowForgeService(
        workflow_repository=repo,
        workflow_permission_service=permission_service,
    )

    workflows = service.list_definitions(
        workspace_id="ws-1",
        actor_user_id="user-1",
        effective_roles={"flowforge:viewer"},
    )

    assert [workflow["id"] for workflow in workflows] == ["12"]
    assert len(permission_service.view_calls) == 2


def test_flowforge_service_creates_incomplete_workflow_draft_with_invalid_validation():
    repo = _WorkflowRepo()
    service = FlowForgeService(workflow_repository=repo, integration_repository=_IntegrationRepo())

    result = service.create_workflow_definition(
        workspace_id="ws-1",
        payload={
            "workflow_key": "template-routing",
            "name": "Template Routing",
            "graph": {
                "nodes": [{"id": "intake", "type": "intake", "data": {"source": "", "event": ""}}],
                "edges": [],
            },
        },
        actor_user_id="user-1",
    )

    assert result["id"] == "12"
    assert repo.created_definition["workflow_key"] == "template-routing"
    assert repo.created_version["validation_status"] == "invalid"
    assert "requires a configured source integration" in repo.created_version["validation_result"]["errors"][0]
    assert repo.current_draft["version_id"] == 45


def test_flowforge_service_creates_new_workflow_draft_version():
    repo = _WorkflowRepo()
    service = FlowForgeService(workflow_repository=repo, integration_repository=_IntegrationRepo())

    result = service.create_workflow_version(
        workspace_id="ws-1",
        workflow_definition_id=12,
        payload={
            "graph": {
                "nodes": [
                    {"id": "intake", "type": "intake", "data": {"source": "intake-form", "event": "intake_submitted"}}
                ],
                "edges": [],
                "viewport": {"x": -220, "y": -110, "zoom": 0.62},
            }
        },
        actor_user_id="user-1",
    )

    assert result["id"] == 45
    assert result["version_number"] == 2
    assert result["graph"]["viewport"] == {"x": -220, "y": -110, "zoom": 0.62}
    assert repo.current_draft["version_id"] == 45


def test_flowforge_service_rejects_workflow_version_without_edit_permission():
    repo = _WorkflowRepo()
    service = FlowForgeService(
        workflow_repository=repo,
        integration_repository=_IntegrationRepo(),
        workflow_permission_service=_WorkflowPermissionService(denied_permissions={"edit"}),
    )

    with pytest.raises(ForgeError) as exc:
        service.create_workflow_version(
            workspace_id="ws-1",
            workflow_definition_id=12,
            payload={"graph": {"nodes": [], "edges": []}},
            actor_user_id="user-1",
            effective_roles={"flowforge:viewer"},
        )

    assert exc.value.status_code == 403
    assert repo.created_version is None


def test_flowforge_service_saves_invalid_workflow_draft_version():
    repo = _WorkflowRepo()
    service = FlowForgeService(workflow_repository=repo, integration_repository=_IntegrationRepo())

    result = service.create_workflow_version(
        workspace_id="ws-1",
        workflow_definition_id=12,
        payload={
            "graph": {
                "nodes": [{"id": "intake", "type": "intake", "data": {"source": "", "event": ""}}],
                "edges": [],
            }
        },
        actor_user_id="user-1",
    )

    assert result["id"] == 45
    assert result["validation_status"] == "invalid"
    assert repo.created_version["validation_status"] == "invalid"
    assert "requires a configured source integration" in result["validation_result"]["errors"][0]
    assert repo.current_draft["version_id"] == 45


def test_flowforge_service_creates_workflow_ai_draft_through_workspace_llm():
    llm_client = _WorkflowDraftLLMClient()
    service = FlowForgeService(
        integration_repository=_IntegrationRepo(),
        llm_runtime_builder=_workflow_draft_runtime_builder(llm_client),
    )

    result = service.create_workflow_ai_draft(
        workspace_id="ws-1",
        payload={
            "prompt": "Add an approval gate after intake.",
            "use_llm": True,
            "graph": {
                "nodes": [
                    {"id": "intake", "type": "intake", "data": {"source": "intake-form", "event": "intake_submitted"}}
                ],
                "edges": [],
                "viewport": {"x": -180, "y": -90, "zoom": 0.7},
            },
            "context": {
                "integrations": [
                    {
                        "integration_key": "intake-form",
                        "provider": "jotform",
                        "source_events": [{"event_key": "intake_submitted"}],
                    }
                ],
                "matching_policies": [{"id": 5, "display_name": "Therapist Routing"}],
            },
        },
        actor_user_id="user-1",
    )

    assert llm_client.calls
    assert "Governed designer context" in llm_client.calls[0]["user_prompt"]
    assert "intake-form" in llm_client.calls[0]["user_prompt"]
    assert "Therapist Routing" in llm_client.calls[0]["user_prompt"]
    assert result["draft_source"] == "llm"
    assert result["model_provider"] == "openai"
    assert result["model_name"] == "workflow-drafter"
    assert result["plain_language_summary"] == "Added an approval gate after intake."
    assert result["graph"]["nodes"][1]["type"] == "approval"
    assert result["graph"]["viewport"] == {"x": -180, "y": -90, "zoom": 0.7}
    assert result["validation_status"] == "invalid"
    assert "requires a configured source integration" in result["validation_result"]["errors"][0]


def test_flowforge_service_creates_workflow_ai_draft_with_heuristic_fallback():
    service = FlowForgeService(integration_repository=_IntegrationRepo())

    result = service.create_workflow_ai_draft(
        workspace_id="ws-1",
        payload={
            "prompt": "Schedule a daily export.",
            "graph": {
                "nodes": [
                    {"id": "intake", "type": "intake", "data": {"source": "intake-form", "event": "intake_submitted"}}
                ],
                "edges": [],
            },
        },
        actor_user_id="user-1",
    )

    assert result["draft_source"] == "heuristic"
    assert result["graph"]["nodes"][-1]["type"] == "schedule_trigger"
    assert result["graph"]["edges"][-1]["target"] == result["graph"]["nodes"][-1]["id"]


def test_flowforge_validation_rejects_unknown_edge_endpoint():
    result = FlowForgeService().validate_graph(
        graph={
            "nodes": [{"id": "a", "type": "intake", "label": "A", "position": {"x": 0, "y": 0}, "data": {}}],
            "edges": [{"id": "a-b", "source": "a", "target": "b"}],
        }
    )

    assert result["valid"] is False
    assert result["errors"] == ["Edge a-b has an unknown target."]


def test_flowforge_validation_accepts_manual_start_node():
    result = FlowForgeService().validate_graph(
        graph={
            "nodes": [
                {
                    "id": "start",
                    "type": "manual_start",
                    "label": "Manual Start",
                    "position": {"x": 0, "y": 0},
                    "data": {"mode": "manual"},
                },
                {"id": "end", "type": "end", "label": "End", "position": {"x": 200, "y": 0}, "data": {}},
            ],
            "edges": [{"id": "start-end", "source": "start", "target": "end"}],
        }
    )

    assert result["valid"] is True
    assert result["errors"] == []


def test_flowforge_validation_warns_for_unmapped_decision_outcomes_and_rejects_duplicates():
    result = FlowForgeService().validate_graph(
        graph={
            "nodes": [
                {
                    "id": "decision",
                    "type": "decision",
                    "label": "Accepted?",
                    "position": {"x": 0, "y": 0},
                    "data": {"outcomes": ["accepted", "declined", "timed_out"]},
                },
                {"id": "assign", "type": "end", "label": "Assign", "position": {"x": 200, "y": 0}, "data": {}},
                {"id": "decline", "type": "end", "label": "Decline", "position": {"x": 200, "y": 120}, "data": {}},
            ],
            "edges": [
                {"id": "accepted-1", "source": "decision", "target": "assign", "branch": "accepted"},
                {"id": "accepted-2", "source": "decision", "target": "decline", "branch": "accepted"},
            ],
        }
    )

    assert result["valid"] is False
    assert "duplicate branch 'accepted'" in result["errors"][0]
    assert "outcome 'declined' has no outgoing route" in " ".join(result["warnings"])
    assert "outcome 'timed_out' has no outgoing route" in " ".join(result["warnings"])


def test_flowforge_validation_accepts_multiple_decision_outcomes_on_one_edge():
    result = FlowForgeService().validate_graph(
        graph={
            "nodes": [
                {
                    "id": "decision",
                    "type": "decision",
                    "label": "Accepted?",
                    "position": {"x": 0, "y": 0},
                    "data": {"outcomes": ["accepted", "declined", "timed_out"]},
                },
                {"id": "assign", "type": "end", "label": "Assign", "position": {"x": 200, "y": 0}, "data": {}},
                {"id": "capture", "type": "event_capture", "label": "Capture", "position": {"x": 200, "y": 120}, "data": {}},
            ],
            "edges": [
                {"id": "accepted", "source": "decision", "target": "assign", "branch": "accepted"},
                {"id": "not-accepted", "source": "decision", "target": "capture", "branches": ["declined", "timed_out"]},
            ],
        }
    )

    assert result["valid"] is True
    assert result["errors"] == []
    assert not any("has no outgoing route" in warning for warning in result["warnings"])


def test_flowforge_validation_accepts_governed_data_movement_nodes():
    result = FlowForgeService().validate_graph(
        graph={
            "nodes": [
                {
                    "id": "schedule",
                    "type": "schedule_trigger",
                    "label": "Daily schedule",
                    "position": {"x": 0, "y": 0},
                    "data": {"rrule": "FREQ=DAILY;INTERVAL=1"},
                },
                {
                    "id": "extract",
                    "type": "query_extract",
                    "label": "Extract saved query",
                    "position": {"x": 220, "y": 0},
                    "data": {"saved_query_id": "saved-query-1", "preview_limit": 500},
                },
                {
                    "id": "transform",
                    "type": "map_transform",
                    "label": "Map fields",
                    "position": {"x": 440, "y": 0},
                    "data": {"field_mapping": {"email": "recipient_email"}},
                },
                {
                    "id": "approval",
                    "type": "approval",
                    "label": "Approve export",
                    "position": {"x": 660, "y": 0},
                    "data": {"approval_group": "ops"},
                },
                {
                    "id": "export",
                    "type": "export",
                    "label": "Export CSV",
                    "position": {"x": 880, "y": 0},
                    "data": {"destination_key": "ops-sftp", "format": "csv"},
                },
            ],
            "edges": [
                {"id": "e1", "source": "schedule", "target": "extract"},
                {"id": "e2", "source": "extract", "target": "transform"},
                {"id": "e3", "source": "transform", "target": "approval"},
                {"id": "e4", "source": "approval", "target": "export"},
            ],
        }
    )

    assert result["valid"] is True
    assert result["errors"] == []


def test_flowforge_validation_rejects_raw_sql_query_extract_and_unallowlisted_export():
    result = FlowForgeService().validate_graph(
        graph={
            "nodes": [
                {
                    "id": "schedule",
                    "type": "schedule_trigger",
                    "label": "Daily schedule",
                    "position": {"x": 0, "y": 0},
                    "data": {"rrule": "FREQ=DAILY;INTERVAL=1"},
                },
                {
                    "id": "extract",
                    "type": "query_extract",
                    "label": "Raw extract",
                    "position": {"x": 220, "y": 0},
                    "data": {"raw_sql": "SELECT * FROM patients"},
                },
                {
                    "id": "export",
                    "type": "export",
                    "label": "Export",
                    "position": {"x": 440, "y": 0},
                    "data": {"format": "csv"},
                },
            ],
            "edges": [
                {"id": "e1", "source": "schedule", "target": "extract"},
                {"id": "e2", "source": "extract", "target": "export"},
            ],
        }
    )

    assert result["valid"] is False
    assert "Query extract node 'extract' cannot define raw SQL fields: raw_sql." in result["errors"]
    assert "Query extract node 'extract' requires saved_query_id, semantic_plan_id, or query_builder_artifact_id." in result["errors"]
    assert "Export node 'export' requires an allowlisted destination_key or destination_id." in result["errors"]


def test_flowforge_validation_rejects_trigger_with_incoming_edge():
    result = FlowForgeService().validate_graph(
        graph={
            "nodes": [
                {"id": "start", "type": "intake", "label": "Start", "position": {"x": 0, "y": 0}, "data": {}},
                {
                    "id": "schedule",
                    "type": "schedule_trigger",
                    "label": "Schedule",
                    "position": {"x": 220, "y": 0},
                    "data": {"interval_minutes": 60},
                },
            ],
            "edges": [{"id": "e1", "source": "start", "target": "schedule"}],
        }
    )

    assert result["valid"] is False
    assert "Trigger node 'schedule' cannot have incoming edges." in result["errors"]


def test_flowforge_validation_rejects_unknown_intake_catalog_refs():
    service = FlowForgeService(integration_repository=_IntegrationRepo())

    result = service.validate_graph(
        workspace_id="ws-1",
        graph={
            "nodes": [
                {
                    "id": "intake",
                    "type": "intake",
                    "label": "Intake",
                    "position": {"x": 0, "y": 0},
                    "data": {"source": "intake-form", "event": "missing_event"},
                },
                {
                    "id": "normalize",
                    "type": "map_transform",
                    "label": "Normalize",
                    "position": {"x": 200, "y": 0},
                    "data": {
                        "mode": "run_context",
                        "field_mapping": [
                            {"target": "intake.requested_service", "source": "intake.fields.unknownField"}
                        ],
                    },
                },
            ],
            "edges": [{"id": "e1", "source": "intake", "target": "normalize"}],
        },
    )

    assert result["valid"] is False
    assert "Intake node 'intake' references unknown event 'missing_event' for integration 'intake-form'." in result["errors"]
    assert (
        "Map transform node 'normalize' references unknown intake source field "
        "'intake.fields.unknownField' for integration 'intake-form'."
    ) in result["errors"]


def test_flowforge_validation_accepts_known_intake_catalog_refs():
    service = FlowForgeService(integration_repository=_IntegrationRepo())

    result = service.validate_graph(
        workspace_id="ws-1",
        graph={
            "nodes": [
                {
                    "id": "intake",
                    "type": "intake",
                    "label": "Intake",
                    "position": {"x": 0, "y": 0},
                    "data": {"source": "intake-form", "event": "intake_submitted"},
                },
                {
                    "id": "normalize",
                    "type": "map_transform",
                    "label": "Normalize",
                    "position": {"x": 200, "y": 0},
                    "data": {
                        "mode": "run_context",
                        "field_mapping": [
                            {"target": "intake.requested_service", "source": "intake.fields.serviceRequested"}
                        ],
                    },
                },
            ],
            "edges": [{"id": "e1", "source": "intake", "target": "normalize"}],
        },
    )

    assert result["valid"] is True
    assert result["errors"] == []


def test_flowforge_service_lists_integrations_without_webhook_secret():
    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        integration_repository=_IntegrationRepo(),
    )

    result = service.list_integrations(workspace_id="ws-1")

    assert result[0]["integration_key"] == "intake-form"
    assert result[0]["webhook_path"] == "/api/v1/flowforge/webhooks/jotform/ffj_public"
    assert result[0]["source_events"] == [
        {"event_key": "intake_submitted", "display_name": "Intake Submitted", "description": None},
        {"event_key": "intake_updated", "display_name": "Intake Updated", "description": "Follow-up update."},
    ]
    assert result[0]["source_fields"] == [
        {
            "path": "serviceRequested",
            "label": "Requested Service",
            "type": "text",
            "required": True,
            "sensitive": False,
        },
        {
            "path": "summary",
            "label": "Clinical Summary",
            "type": "text",
            "required": False,
            "sensitive": True,
        },
    ]
    assert "webhook_secret" not in result[0]


def test_flowforge_service_creates_jotform_integration_with_one_time_secret():
    repo = _IntegrationRepo()
    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        integration_repository=repo,
    )

    result = service.create_jotform_integration(
        workspace_id="ws-1",
        payload={
            "integration_key": "intake-form",
            "display_name": "Intake Form",
            "external_form_id": "form-1",
            "mode": "test",
            "field_mapping": {"patient": "patientName"},
            "source_events": [
                {"event_key": "intake_submitted", "display_name": "Intake Submitted"},
                {"event_key": "intake_updated", "display_name": "Intake Updated", "description": "Follow-up update."},
            ],
            "source_fields": [
                {"path": "fields.name", "label": "Patient Name", "type": "text", "required": True},
                {"path": "fields.notes", "label": "Notes", "type": "long_text", "sensitive": True},
            ],
        },
        actor_user_id="user-1",
    )

    assert result["id"] == 11
    assert result["provider"] == "jotform"
    assert result["webhook_secret"].startswith("ffjot_")
    assert result["webhook_path"].startswith("/api/v1/flowforge/webhooks/jotform/ffj_")
    assert repo.created_config["created_by"] == "user-1"
    assert repo.created_config["secret_hash"] != result["webhook_secret"]
    assert len(repo.created_config["secret_hash"]) == 64
    assert result["source_events"] == [
        {"event_key": "intake_submitted", "display_name": "Intake Submitted", "description": None},
        {"event_key": "intake_updated", "display_name": "Intake Updated", "description": "Follow-up update."},
    ]
    assert result["source_fields"] == [
        {
            "path": "fields.name",
            "label": "Patient Name",
            "type": "text",
            "required": True,
            "sensitive": False,
        },
        {
            "path": "fields.notes",
            "label": "Notes",
            "type": "unknown",
            "required": False,
            "sensitive": True,
        },
    ]


def test_flowforge_service_creates_webhook_integration_with_one_time_secret():
    repo = _IntegrationRepo()
    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        integration_repository=repo,
    )

    result = service.create_webhook_integration(
        workspace_id="ws-1",
        payload={
            "integration_key": "webhook-intake",
            "display_name": "Webhook Intake",
            "mode": "test",
            "source_events": [{"event_key": "webhook_received", "display_name": "Webhook Received"}],
            "source_fields": [{"path": "fields.summary", "label": "Summary", "type": "text"}],
        },
        actor_user_id="user-1",
    )

    assert result["id"] == 11
    assert result["provider"] == "webhook"
    assert result["webhook_secret"].startswith("ffweb_")
    assert result["webhook_path"].startswith("/api/v1/flowforge/webhooks/generic/ffw_")
    assert repo.created_config["provider"] == "webhook"
    assert repo.created_config["created_by"] == "user-1"
    assert repo.created_config["secret_hash"] != result["webhook_secret"]
    assert len(repo.created_config["secret_hash"]) == 64


def test_flowforge_service_creates_file_watch_integration_without_webhook_endpoint():
    repo = _IntegrationRepo()
    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        integration_repository=repo,
    )

    result = service.create_file_watch_integration(
        workspace_id="ws-1",
        payload={
            "integration_key": "sftp-dropbox",
            "display_name": "SFTP Dropbox",
            "mode": "test",
            "source_events": [
                {"event_key": "file_created", "display_name": "File Created"},
                {"event_key": "file_updated", "display_name": "File Updated"},
            ],
            "source_fields": [
                {"path": "file.name", "label": "File Name", "type": "text", "required": True},
                {"path": "file.size_bytes", "label": "Size", "type": "number"},
            ],
        },
        actor_user_id="user-1",
    )

    assert result["id"] == 11
    assert result["provider"] == "file_watch"
    assert result["webhook_path"] is None
    assert result["webhook_url"] is None
    assert result["webhook_secret"] is None
    assert repo.created_config["provider"] == "file_watch"
    assert repo.created_config["webhook_public_id"].startswith("fffile_")
    assert repo.created_config["created_by"] == "user-1"
    assert result["source_events"] == [
        {"event_key": "file_created", "display_name": "File Created", "description": None},
        {"event_key": "file_updated", "display_name": "File Updated", "description": None},
    ]


def test_flowforge_service_rejects_jotform_integration_without_key():
    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        integration_repository=_IntegrationRepo(),
    )

    with pytest.raises(ForgeError) as exc:
        service.create_jotform_integration(
            workspace_id="ws-1",
            payload={"display_name": "Intake Form"},
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400
    assert "integration_key" in str(exc.value)


def test_flowforge_service_lists_integration_triggers():
    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        integration_repository=_IntegrationRepo(),
    )

    result = service.list_integration_triggers(workspace_id="ws-1", integration_config_id=10)

    assert result[0]["trigger_key"] == "intake-routing"
    assert result[0]["workflow_definition_id"] == 12
    assert result[0]["workflow_version_id"] == 13
    assert result[0]["field_mapping"] == {"patient_name": "fields.name"}


def test_flowforge_service_creates_pinned_integration_trigger():
    repo = _IntegrationRepo()
    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        integration_repository=repo,
    )

    result = service.create_integration_trigger(
        workspace_id="ws-1",
        integration_config_id=10,
        payload={
            "trigger_key": "intake-routing",
            "display_name": "Intake Routing",
            "priority": 50,
            "trigger_mode": "always",
            "trigger_policy": "all_matching",
            "version_strategy": "pinned",
            "workflow_definition_id": 12,
            "workflow_version_id": 13,
            "field_mapping": {"patient_name": "fields.name"},
            "no_match_config": {"notify": ["ops@example.com"]},
        },
        actor_user_id="user-1",
    )

    assert result["id"] == 67
    assert result["trigger_key"] == "intake-routing"
    assert repo.created_trigger["created_by"] == "user-1"
    assert repo.created_trigger["workflow_version_id"] == 13
    assert repo.created_trigger["condition"] == {}


def test_flowforge_service_rejects_pinned_integration_trigger_without_version():
    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        integration_repository=_IntegrationRepo(),
    )

    with pytest.raises(ForgeError) as exc:
        service.create_integration_trigger(
            workspace_id="ws-1",
            integration_config_id=10,
            payload={
                "trigger_key": "intake-routing",
                "display_name": "Intake Routing",
                "workflow_definition_id": 12,
                "version_strategy": "pinned",
            },
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400
    assert "workflow_version_id" in str(exc.value)


def test_flowforge_service_rejects_conditional_trigger_without_condition():
    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        integration_repository=_IntegrationRepo(),
    )

    with pytest.raises(ForgeError) as exc:
        service.create_integration_trigger(
            workspace_id="ws-1",
            integration_config_id=10,
            payload={
                "trigger_key": "conditional-routing",
                "display_name": "Conditional Routing",
                "workflow_definition_id": 12,
                "workflow_version_id": 13,
                "trigger_mode": "conditional",
                "condition": [],
            },
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400
    assert "condition" in str(exc.value)


def test_flowforge_service_persists_public_jotform_webhook_intake(monkeypatch):
    integration_repo = _IntegrationRepo()
    runtime_repo = _RuntimeRepo()
    queued_dispatches = []
    monkeypatch.setattr(
        "app.tasks.flowforge_tasks.enqueue_flowforge_run_dispatch",
        lambda workspace_id, run_id: queued_dispatches.append((workspace_id, run_id)),
    )
    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        integration_repository=integration_repo,
        settings_repository=_SettingsRepo(),
        runtime_repository=runtime_repo,
        workflow_repository=_WorkflowRepo(),
    )

    result = service.accept_jotform_integration_webhook(
        webhook_public_id="ffj_public",
        token="ffjot_secret",
        source_ip="203.0.113.7",
        headers={"User-Agent": "Jotform"},
        payload={
            "rawRequest": (
                '{"submissionID":"sub-123","formID":"form-456","ip":"203.0.113.5",'
                '"created_at":"2026-05-04 08:15:00","patientType":"new","name":"Jane Patient"}'
            )
        },
    )

    assert result["accepted"] is True
    assert result["duplicate"] is False
    assert result["intake_event_id"] == 501
    assert result["integration_id"] == 10
    assert integration_repo.created_intake_event["workspace_id"] == "ws-1"
    assert integration_repo.created_intake_event["idempotency_key"] == "jotform:ffj_public:submission:sub-123"
    assert integration_repo.created_intake_event["mode"] == "test"
    assert integration_repo.created_intake_event["normalized_payload"]["submission_id"] == "sub-123"
    assert integration_repo.created_intake_event["source_ip"] == "203.0.113.7"
    assert integration_repo.created_intake_event["raw_payload_expires_at"] is not None
    assert integration_repo.created_intake_event["trigger_evaluation"]["matched_trigger_count"] == 1
    assert integration_repo.created_intake_event["trigger_evaluation"]["selected_trigger_count"] == 1
    assert result["trigger_evaluation"]["selected_triggers"][0]["trigger_key"] == "intake-routing"
    assert result["trigger_evaluation"]["workflow_run_creation"] == "created"
    assert result["workflow_runs"][0]["run_id"] == 901
    assert runtime_repo.created_runs[0]["workflow_definition_id"] == 12
    assert runtime_repo.created_runs[0]["workflow_version_id"] == 13
    assert runtime_repo.created_runs[0]["intake_event_id"] == 501
    assert runtime_repo.created_runs[0]["run_as_principal_type"] == "user"
    assert runtime_repo.created_runs[0]["run_as_principal_id"] == "user-1"
    assert runtime_repo.created_events[0]["event_type"] == "workflow.run.created"
    assert runtime_repo.created_events[0]["event_payload"]["run_as_principal_type"] == "user"
    assert runtime_repo.created_events[0]["event_payload"]["run_as_principal_id"] == "user-1"
    assert integration_repo.updated_trigger_evaluation["trigger_evaluation"]["created_run_count"] == 1
    assert queued_dispatches == [("ws-1", 901)]


def test_flowforge_service_returns_duplicate_for_existing_public_jotform_webhook_intake():
    integration_repo = _IntegrationRepo()
    integration_repo.existing_intake_event = {
        "id": 500,
        "normalized_payload_json": {"submission_id": "sub-123", "received_at": "2026-05-04T00:00:00Z"},
        "trigger_evaluation_json": {"matched_trigger_count": 1, "selected_triggers": [{"id": 66}]},
    }
    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        integration_repository=integration_repo,
        settings_repository=_SettingsRepo(),
        runtime_repository=_RuntimeRepo(),
    )

    result = service.accept_jotform_integration_webhook(
        webhook_public_id="ffj_public",
        token="ffjot_secret",
        payload={"submissionID": "sub-123"},
    )

    assert result["accepted"] is True
    assert result["duplicate"] is True
    assert result["intake_event_id"] == 500
    assert result["trigger_evaluation"]["matched_trigger_count"] == 1
    assert integration_repo.created_intake_event is None


def test_flowforge_service_persists_public_generic_webhook_intake(monkeypatch):
    integration_repo = _IntegrationRepo()
    integration_repo.secret_hash = FlowForgeService()._hash_webhook_secret("ffweb_secret")
    runtime_repo = _RuntimeRepo()
    queued_dispatches = []
    monkeypatch.setattr(
        "app.tasks.flowforge_tasks.enqueue_flowforge_run_dispatch",
        lambda workspace_id, run_id: queued_dispatches.append((workspace_id, run_id)),
    )
    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        integration_repository=integration_repo,
        settings_repository=_SettingsRepo(),
        runtime_repository=runtime_repo,
        workflow_repository=_WorkflowRepo(),
    )

    result = service.accept_generic_integration_webhook(
        webhook_public_id="ffw_public",
        token="ffweb_secret",
        source_ip="203.0.113.7",
        headers={"User-Agent": "Example"},
        payload={
            "event_key": "webhook_received",
            "event_id": "evt-123",
            "fields": {"patientType": "new", "summary": "Ready", "serviceRequested": "Therapy"},
        },
    )

    assert result["accepted"] is True
    assert result["duplicate"] is False
    assert result["source"] == "webhook"
    assert result["event"]["event_type"] == "flowforge.integration.webhook.received"
    assert integration_repo.created_intake_event["workspace_id"] == "ws-1"
    assert integration_repo.created_intake_event["provider"] == "webhook"
    assert integration_repo.created_intake_event["idempotency_key"] == "webhook:ffw_public:event:evt-123"
    assert integration_repo.created_intake_event["external_submission_id"] == "evt-123"
    assert integration_repo.created_intake_event["normalized_payload"]["event_key"] == "webhook_received"
    assert integration_repo.created_intake_event["normalized_payload"]["fields"]["summary"] == "Ready"
    assert result["trigger_evaluation"]["workflow_run_creation"] == "created"
    assert result["workflow_runs"][0]["run_id"] == 901
    assert queued_dispatches == [("ws-1", 901)]


def test_flowforge_service_rejects_public_jotform_webhook_with_bad_secret():
    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        integration_repository=_IntegrationRepo(),
        settings_repository=_SettingsRepo(),
    )

    with pytest.raises(ForgeError) as exc:
        service.accept_jotform_integration_webhook(
            webhook_public_id="ffj_public",
            token="wrong",
            payload={"submissionID": "sub-123"},
        )

    assert exc.value.status_code == 401


def test_flowforge_service_lists_persisted_runs_and_events():
    service = FlowForgeService(runtime_repository=_RuntimeRepo())

    runs = service.list_runs(workspace_id="ws-1", status="waiting", mode="test", limit=5000, offset=-1)
    detail = service.get_run(workspace_id="ws-1", run_id=90)
    events = service.list_run_events(workspace_id="ws-1", run_id=90, limit=5000)

    assert runs["limit"] == 500
    assert runs["offset"] == 0
    assert runs["runs"][0]["id"] == 90
    assert runs["runs"][0]["run_context"] == {"trigger_key": "intake-routing"}
    assert runs["runs"][0]["run_as_principal_type"] == "user"
    assert runs["runs"][0]["run_as_principal_id"] == "operator-1"
    assert runs["runs"][0]["run_as_principal_display_name"] == "Olivia Operator"
    assert runs["runs"][0]["triggered_by_user_id"] == "operator-1"
    assert runs["runs"][0]["triggered_by_display_name"] == "Olivia Operator"
    assert runs["runs"][0]["started_at"] == "2026-05-11T21:06:00"
    assert runs["runs"][0]["created_at"] == "2026-05-11T21:06:00"
    assert runs["runs"][0]["updated_at"] == "2026-05-11T21:06:01"
    assert detail["id"] == 90
    assert events["events"][0]["event_type"] == "workflow.run.created"
    assert events["events"][0]["created_at"] == "2026-05-11T21:06:00"


def test_flowforge_service_updates_workspace_settings():
    settings_repo = _SettingsRepo()
    service = FlowForgeService(settings_repository=settings_repo)

    result = service.update_workspace_settings(
        workspace_id="ws-1",
        payload={
            "enabled": True,
            "raw_payload_retention_days": 45,
            "default_offer_timeout_minutes": 120,
            "default_no_match_recipients": ["ops@example.com"],
            "default_test_recipients": ["test@example.com"],
        },
        actor_user_id="user-1",
    )

    assert result["enabled"] is True
    assert result["raw_payload_retention_days"] == 45
    assert result["default_no_match_recipients"] == ["ops@example.com"]
    assert settings_repo.updated_payload["payload"]["updated_by"] == "user-1"


def test_flowforge_service_updates_sensitive_reporting_mcp_block_flag():
    settings_repo = _SettingsRepo()
    service = FlowForgeService(settings_repository=settings_repo)

    result = service.update_workspace_settings(
        workspace_id="ws-1",
        payload={"block_sensitive_reporting_mcp": True},
        actor_user_id="user-1",
    )

    assert result["block_sensitive_reporting_mcp"] is True
    assert settings_repo.updated_payload["payload"]["settings"]["block_sensitive_reporting_mcp"] is True


def test_flowforge_service_updates_production_run_as_settings():
    settings_repo = _SettingsRepo()
    service = FlowForgeService(settings_repository=settings_repo)

    result = service.update_workspace_settings(
        workspace_id="ws-1",
        payload={
            "allow_user_run_as_for_production": True,
            "require_service_principal_for_automated_triggers": False,
        },
        actor_user_id="user-1",
    )

    assert result["allow_user_run_as_for_production"] is True
    assert result["require_service_principal_for_automated_triggers"] is False
    assert settings_repo.updated_payload["payload"]["settings"]["allow_user_run_as_for_production"] is True
    assert settings_repo.updated_payload["payload"]["settings"]["require_service_principal_for_automated_triggers"] is False


def test_flowforge_service_rejects_settings_retention_above_max():
    service = FlowForgeService(settings_repository=_SettingsRepo())

    with pytest.raises(ForgeError) as exc:
        service.update_workspace_settings(
            workspace_id="ws-1",
            payload={"raw_payload_retention_days": 120},
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400


def test_flowforge_service_returns_none_for_missing_run():
    service = FlowForgeService(runtime_repository=_RuntimeRepo())

    assert service.get_run(workspace_id="ws-1", run_id=999) is None


def test_flowforge_service_adds_operator_note_to_run_timeline():
    repo = _RuntimeRepo()
    service = FlowForgeService(runtime_repository=repo)

    result = service.add_run_note(
        workspace_id="ws-1",
        run_id=90,
        payload={"note": "Called intake coordinator; waiting on updated availability.", "idempotency_key": "note-1"},
        actor_user_id="user-1",
    )

    assert result["id"] == 801
    assert result["event_type"] == "workflow.operator.note"
    assert result["message"] == "Operator note added."
    assert result["event_payload"]["note"] == "Called intake coordinator; waiting on updated availability."
    assert result["actor_type"] == "user"
    assert result["actor_id"] == "user-1"
    assert repo.created_events[0]["idempotency_key"] == "note-1"


def test_flowforge_service_rejects_operator_note_for_missing_run():
    service = FlowForgeService(runtime_repository=_RuntimeRepo())

    with pytest.raises(ForgeError) as exc:
        service.add_run_note(
            workspace_id="ws-1",
            run_id=999,
            payload={"note": "Missing run."},
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 404


def test_flowforge_service_rejects_blank_operator_note():
    service = FlowForgeService(runtime_repository=_RuntimeRepo())

    with pytest.raises(ForgeError) as exc:
        service.add_run_note(
            workspace_id="ws-1",
            run_id=90,
            payload={"note": "   "},
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400


def test_flowforge_service_lists_run_human_tasks():
    service = FlowForgeService(runtime_repository=_RuntimeRepo())

    result = service.list_run_human_tasks(workspace_id="ws-1", run_id=90, limit=5000)

    assert result["workspace_id"] == "ws-1"
    assert result["run_id"] == 90
    assert result["limit"] == 500
    assert result["tasks"][0]["id"] == 301
    assert result["tasks"][0]["task_type"] == "offer"
    assert result["tasks"][0]["response"] == {"allowed_actions": ["accept", "decline"]}
    assert result["tasks"][0]["due_at"] == "2026-05-05T12:00:00"
    assert result["tasks"][0]["created_at"] == "2026-05-05T10:00:00"
    assert result["tasks"][0]["updated_at"] == "2026-05-05T10:00:01"


def test_flowforge_service_lists_operator_approval_tasks():
    service = FlowForgeService(runtime_repository=_RuntimeRepo())

    result = service.list_human_tasks(
        workspace_id="ws-1",
        task_type="approval",
        status="pending,waiting",
        limit=5000,
        offset=-1,
    )

    assert result["workspace_id"] == "ws-1"
    assert result["task_type"] == "approval"
    assert result["status"] == "pending,waiting"
    assert result["limit"] == 500
    assert result["offset"] == 0
    assert result["tasks"][0]["id"] == 302
    assert result["tasks"][0]["response"]["approval"]["destination_key"] == "ops-export"


def test_flowforge_service_rejects_human_task_list_for_missing_run():
    service = FlowForgeService(runtime_repository=_RuntimeRepo())

    with pytest.raises(ForgeError) as exc:
        service.list_run_human_tasks(workspace_id="ws-1", run_id=999, limit=25)

    assert exc.value.status_code == 404


def test_flowforge_service_creates_signed_action_token_for_human_task(monkeypatch):
    repo = _RuntimeRepo()
    service = FlowForgeService(runtime_repository=repo)
    monkeypatch.setattr(service, "_generate_signed_action_token", lambda: "plain-token")
    monkeypatch.setattr(service, "_hash_signed_action_token", lambda token: "token-hash")

    result = service.create_signed_action_token(
        workspace_id="ws-1",
        human_task_id=301,
        payload={"allowed_actions": ["accept", "decline"], "expires_at": "2099-01-01 00:00:00"},
        actor_user_id="user-1",
    )

    assert result["token"] == "plain-token"
    assert result["allowed_actions"] == ["accept", "decline"]
    assert repo.created_tokens[0]["token_hash"] == "token-hash"
    assert repo.created_events[0]["event_type"] == "workflow.signed_action.created"


def test_flowforge_service_gets_public_signed_action_details(monkeypatch):
    service = FlowForgeService(runtime_repository=_RuntimeRepo())
    monkeypatch.setattr(service, "_hash_signed_action_token", lambda token: "token-hash")

    result = service.get_signed_action_details(token="plain-token")

    assert result["valid"] is True
    assert result["task"]["task_type"] == "offer"
    assert result["allowed_actions"] == ["accept", "decline"]
    assert "workspace_id" not in result


def test_flowforge_service_accepts_public_signed_action(monkeypatch):
    repo = _RuntimeRepo()
    advanced = []

    class _HumanResponseRuntime:
        def __init__(self, **kwargs):
            advanced.append({"init": kwargs})

        def advance_after_human_action(self, **payload):
            advanced.append(payload)
            return {"status": "advanced", "run_id": payload["run_id"], "to_node_id": "assign"}

    service = FlowForgeService(runtime_repository=repo)
    monkeypatch.setattr(service, "_hash_signed_action_token", lambda token: "token-hash")
    monkeypatch.setattr("app.features.flowforge.runtime.human_responses.FlowForgeHumanResponseRuntime", _HumanResponseRuntime)

    result = service.complete_signed_action(
        token="plain-token",
        action="accept",
        payload={"response_note": "I can take this referral."},
        source_ip="203.0.113.9",
    )

    assert result["accepted"] is True
    assert result["action"] == "accept"
    assert repo.used_token["used_action"] == "accept"
    assert repo.updated_task["status"] == "accepted"
    assert repo.created_events[0]["event_type"] == "workflow.human_task.accepted"
    assert result["runtime"] == {"status": "advanced", "run_id": 90, "to_node_id": "assign"}
    assert advanced[1]["workspace_id"] == "ws-1"
    assert advanced[1]["run_id"] == 90
    assert advanced[1]["action"] == "accept"
    assert advanced[1]["human_task_id"] == 301


def test_flowforge_service_rejects_unsupported_public_signed_action(monkeypatch):
    service = FlowForgeService(runtime_repository=_RuntimeRepo())
    monkeypatch.setattr(service, "_hash_signed_action_token", lambda token: "token-hash")

    with pytest.raises(ForgeError) as exc:
        service.complete_signed_action(token="plain-token", action="cancel", payload={}, source_ip=None)

    assert exc.value.status_code == 400


def test_flowforge_service_lists_run_notifications():
    service = FlowForgeService(runtime_repository=_RuntimeRepo())

    result = service.list_run_notifications(workspace_id="ws-1", run_id=90, limit=5000)

    assert result["limit"] == 500
    assert result["notifications"][0]["template_key"] == "flowforge.no_match"
    assert result["notifications"][0]["payload_summary"] == {"reason": "No eligible resources."}
    assert result["notifications"][0]["created_at"] == "2026-05-12T10:11:28"
    assert result["notifications"][0]["failed_at"] == "2026-05-12T10:11:52"
    json.dumps(result)


def test_flowforge_service_creates_no_match_escalation_notifications():
    repo = _RuntimeRepo()
    service = FlowForgeService(runtime_repository=repo, settings_repository=_SettingsRepo())

    result = service.create_no_match_escalation(
        workspace_id="ws-1",
        run_id=90,
        payload={"reason": "No eligible resources.", "recipients": ["ops@example.com"]},
        actor_user_id="user-1",
    )

    assert result["status"] == "needs_attention"
    assert result["notification_count"] == 1
    assert repo.updated_run_status["status"] == "needs_attention"
    assert repo.created_notifications[0]["recipient"] == "ops@example.com"
    assert repo.created_notifications[0]["payload_summary"]["reason"] == "No eligible resources."
    assert repo.created_events[0]["event_type"] == "workflow.no_match.escalated"


def test_flowforge_service_uses_default_no_match_recipients():
    repo = _RuntimeRepo()
    service = FlowForgeService(runtime_repository=repo, settings_repository=_SettingsRepo())

    result = service.create_no_match_escalation(
        workspace_id="ws-1",
        run_id=90,
        payload={"reason": "No eligible resources."},
        actor_user_id="user-1",
    )

    assert result["recipients"] == ["ops-default@example.com"]
    assert repo.created_notifications[0]["recipient"] == "ops-default@example.com"


def test_flowforge_service_returns_reporting_domains_and_summary(monkeypatch):
    monkeypatch.setattr(
        FlowForgeSemanticSyncService,
        "domain_status_index",
        lambda self, *, workspace_id: {
            "flowforge_workflow_runs": {
                "registration_status": "registered",
                "registration_issues": [],
                "queryforge_launch": {"source": "flowforge"},
            }
        },
    )
    service = FlowForgeService(runtime_repository=_RuntimeRepo())

    domains = service.list_reporting_domains(workspace_id="ws-1")
    summary = service.get_report_summary(workspace_id="ws-1", mode=None)

    assert domains[0]["domain_key"] == "flowforge_workflow_runs"
    assert domains[0]["semantic_registered"] is True
    assert domains[0]["read_model"] == "v_flowforge_report_workflow_runs"
    assert domains[0]["default_filters"] == [{"field": "mode", "operator": "equals", "value": "production"}]
    assert any(metric["key"] == "run_count" for metric in domains[0]["metrics"])
    sensitive_fields = {field for domain in domains for field in domain["sensitive_excluded_fields"]}
    assert "raw_payload_json" in sensitive_fields
    assert "recipient" in sensitive_fields
    assert "sensitive_profile_json" in sensitive_fields
    assert "request_json" in sensitive_fields
    assert "storage_ref_json" in sensitive_fields
    assert summary["mode"] == "production"
    assert summary["default_filters"] == [{"field": "mode", "operator": "equals", "value": "production"}]
    assert summary["metrics"]["run_count"] == 10
    assert summary["metrics"]["needs_attention_count"] == 2


def test_flowforge_service_returns_reporting_dashboard_metrics():
    service = FlowForgeService(runtime_repository=_RuntimeRepo())

    dashboard = service.get_report_dashboard(workspace_id="ws-1", mode=None)

    assert dashboard["mode"] == "production"
    assert dashboard["metrics"]["intake_event_count"] == 9
    assert dashboard["metrics"]["offer_count"] == 6
    assert dashboard["metrics"]["assignment_count"] == 4
    assert dashboard["metrics"]["dataset_artifact_count"] == 11
    assert dashboard["metrics"]["failed_export_count"] == 2
    assert {domain["domain_key"] for domain in dashboard["domains"]} >= {
        "flowforge_intake_events",
        "flowforge_matching_evaluations",
        "flowforge_resource_snapshots",
        "flowforge_offers_responses",
        "flowforge_assignments",
        "flowforge_notifications",
        "flowforge_dataset_artifacts",
        "flowforge_data_movement_audit",
    }


def test_flowforge_service_returns_intake_review_timeline_and_raw_form():
    service = FlowForgeService(runtime_repository=_RuntimeRepo())

    timeline = service.get_intake_review_timeline(workspace_id="ws-1", mode=None, days=7)
    raw_form = service.get_intake_raw_form(workspace_id="ws-1", intake_event_id=502)
    today_bucket = next(bucket for bucket in timeline["buckets"] if bucket["date"] == date.today().isoformat())

    assert timeline["mode"] == "production"
    assert today_bucket["intake_count"] == 2
    assert today_bucket["accepted_count"] == 1
    assert today_bucket["not_accepted_count"] == 1
    assert today_bucket["events"][0]["accepted_by"] == "Dr. Lane"
    assert today_bucket["events"][1]["outcome"] == "not_accepted"
    assert raw_form["raw_payload"]["patient"]["first_name"] == "Jane"
    assert raw_form["normalized_payload"]["requested_service"] == "therapy"


def test_flowforge_service_lists_and_publishes_workflow_versions():
    repo = _WorkflowRepo()
    service = FlowForgeService(workflow_repository=repo, runtime_repository=_RuntimeRepo(), settings_repository=_SettingsRepo())

    versions = service.list_workflow_versions(workspace_id="ws-1", workflow_definition_id=12)
    published = service.publish_workflow_version(
        workspace_id="ws-1",
        workflow_definition_id=12,
        version_id=44,
        actor_user_id="user-1",
    )

    assert versions[0]["id"] == 44
    assert versions[0]["graph"] == {"nodes": [{"id": "intake"}], "edges": []}
    assert versions[0]["created_at"] == "2026-05-07T20:27:25"
    assert published["version_status"] == "published"
    assert repo.published["published_by"] == "user-1"


def test_flowforge_service_rejects_production_publish_without_service_run_as():
    repo = _WorkflowRepo()
    repo.definitions[0]["lifecycle"] = "production"
    repo.definitions[0]["run_as_principal_type"] = "user"
    repo.definitions[0]["run_as_principal_id"] = "user-1"
    service = FlowForgeService(workflow_repository=repo, runtime_repository=_RuntimeRepo(), settings_repository=_SettingsRepo())

    with pytest.raises(ForgeError) as exc:
        service.publish_workflow_version(
            workspace_id="ws-1",
            workflow_definition_id=12,
            version_id=44,
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400
    assert exc.value.details["reason"] == "production_run_as_required"
    assert repo.published is None


def test_flowforge_service_readiness_reports_publish_and_runtime_blockers():
    repo = _WorkflowRepo()
    repo.definitions[0]["lifecycle"] = "production"
    repo.definitions[0]["run_as_principal_type"] = "user"
    repo.definitions[0]["run_as_principal_id"] = "user-1"
    repo.versions[0]["graph_json"] = {
        "nodes": [
            {"id": "start", "type": "intake", "data": {"source": "intake-form", "event": "intake_submitted"}},
            {"id": "match", "type": "matching", "data": {}},
        ],
        "edges": [{"id": "start-match", "source": "start", "target": "match"}],
    }
    service = FlowForgeService(workflow_repository=repo, runtime_repository=_RuntimeRepo(), settings_repository=_SettingsRepo())

    readiness = service.get_workflow_readiness(
        workspace_id="ws-1",
        workflow_definition_id=12,
        actor_user_id="user-1",
        effective_roles={"flowforge:admin"},
    )

    blocker_codes = {item["code"] for item in readiness["blockers"]}
    warning_codes = {item["code"] for item in readiness["warnings"]}
    assert readiness["status"] == "blocked"
    assert readiness["can_publish"] is False
    assert readiness["can_run"] is False
    assert "production_run_as_required" in blocker_codes
    assert "matching_policy_required" in blocker_codes
    assert "resource_set_required" in blocker_codes
    assert "published_version_required" in warning_codes
    assert readiness["steps"][0]["id"] == "draft_saved"


def test_flowforge_service_readiness_allows_published_runnable_workflow():
    repo = _WorkflowRepo()
    runtime_repo = _RuntimeRepo()
    repo.definitions[0]["latest_published_version_id"] = 44
    repo.definitions[0]["graph_json"] = {"nodes": [{"id": "end", "type": "end", "data": {}}], "edges": []}
    repo.versions[0]["version_status"] = "published"
    repo.versions[0]["graph_json"] = {"nodes": [{"id": "end", "type": "end", "data": {}}], "edges": []}
    service = FlowForgeService(workflow_repository=repo, runtime_repository=runtime_repo, settings_repository=_SettingsRepo())

    readiness = service.get_workflow_readiness(
        workspace_id="ws-1",
        workflow_definition_id=12,
        actor_user_id="user-1",
        effective_roles={"flowforge:admin"},
    )

    assert readiness["status"] == "ready"
    assert readiness["can_run"] is True
    assert readiness["latest_published_version_id"] == 44
    assert readiness["latest_run_id"] == 90
    assert readiness["latest_run_status"] == "waiting"
    assert readiness["latest_run_mode"] == "test"
    assert readiness["steps"][2]["state"] == "complete"
    assert readiness["steps"][4]["state"] == "current"


def test_flowforge_service_allows_production_publish_with_service_run_as():
    repo = _WorkflowRepo()
    repo.definitions[0]["lifecycle"] = "production"
    repo.definitions[0]["run_as_principal_type"] = "service_principal"
    repo.definitions[0]["run_as_principal_id"] = "workflow-runner"
    service = FlowForgeService(workflow_repository=repo, settings_repository=_SettingsRepo())

    published = service.publish_workflow_version(
        workspace_id="ws-1",
        workflow_definition_id=12,
        version_id=44,
        actor_user_id="user-1",
    )

    assert published["version_status"] == "published"
    assert repo.published["published_by"] == "user-1"


def test_flowforge_service_allows_user_run_as_when_workspace_override_enabled_for_manual_production():
    repo = _WorkflowRepo()
    repo.definitions[0]["lifecycle"] = "production"
    repo.definitions[0]["run_as_principal_type"] = "user"
    repo.definitions[0]["run_as_principal_id"] = "user-1"
    settings_repo = _SettingsRepo()
    settings_repo.current["allow_user_run_as_for_production"] = True
    settings_repo.current["settings"] = {"allow_user_run_as_for_production": True}
    service = FlowForgeService(workflow_repository=repo, settings_repository=settings_repo)

    published = service.publish_workflow_version(
        workspace_id="ws-1",
        workflow_definition_id=12,
        version_id=44,
        actor_user_id="user-1",
    )

    assert published["version_status"] == "published"
    assert repo.published["published_by"] == "user-1"


def test_flowforge_service_rejects_user_run_as_for_production_trigger_even_with_user_override():
    repo = _WorkflowRepo()
    repo.definitions[0]["lifecycle"] = "production"
    repo.definitions[0]["run_as_principal_type"] = "user"
    repo.definitions[0]["run_as_principal_id"] = "user-1"
    repo.versions[0]["graph_json"] = {
        "nodes": [{"id": "schedule", "type": "schedule_trigger"}],
        "edges": [],
    }
    settings_repo = _SettingsRepo()
    settings_repo.current["allow_user_run_as_for_production"] = True
    settings_repo.current["require_service_principal_for_automated_triggers"] = True
    settings_repo.current["settings"] = {
        "allow_user_run_as_for_production": True,
        "require_service_principal_for_automated_triggers": True,
    }
    service = FlowForgeService(workflow_repository=repo, settings_repository=settings_repo)

    with pytest.raises(ForgeError) as exc:
        service.publish_workflow_version(
            workspace_id="ws-1",
            workflow_definition_id=12,
            version_id=44,
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400
    assert exc.value.details["allow_user_run_as_for_production"] is True
    assert exc.value.details["require_service_principal_for_automated_triggers"] is True
    assert repo.published is None


def test_flowforge_service_returns_workflow_governance_metadata():
    service = FlowForgeService(workflow_repository=_WorkflowRepo())

    result = service.get_definition(
        workspace_id="ws-1",
        workflow_id="12",
        actor_user_id="user-1",
        effective_roles={"flowforge:designer"},
    )

    assert result["owner_user_id"] == "user-1"
    assert result["owner_display_name"] == "Taylor Jordan"
    assert result["run_as_principal"] == {
        "principal_type": "user",
        "principal_id": "user-1",
        "display_name": "Taylor Jordan",
    }
    assert result["lifecycle"] == "development"
    assert result["effective_permissions"]["permission"] == "owner"
    assert result["effective_permissions"]["can_manage"] is True


def test_flowforge_service_updates_workflow_permissions():
    repo = _WorkflowRepo()
    service = FlowForgeService(workflow_repository=repo)

    result = service.update_workflow_permissions(
        workspace_id="ws-1",
        workflow_definition_id=12,
        payload={
            "grants": [{"principal_type": "workspace_role", "principal_id": "flowforge:operator", "permission": "run"}],
            "revocations": [{"principal_type": "user", "principal_id": "user-2"}],
        },
        actor_user_id="user-1",
        effective_roles={"flowforge:admin"},
    )

    assert result["workflow_definition_id"] == 12
    assert repo.grants[-1]["principal_id"] == "flowforge:operator"
    assert repo.revocations[-1]["principal_id"] == "user-2"


def test_flowforge_service_updates_metadata_owner_and_run_as():
    repo = _WorkflowRepo()
    service = FlowForgeService(workflow_repository=repo)

    metadata = service.update_workflow_metadata(
        workspace_id="ws-1",
        workflow_definition_id=12,
        payload={"name": "Renamed Workflow", "description": "Updated description."},
        actor_user_id="user-1",
        effective_roles={"flowforge:admin"},
    )
    owner = service.update_workflow_owner(
        workspace_id="ws-1",
        workflow_definition_id=12,
        payload={"owner_user_id": "user-2"},
        actor_user_id="user-1",
        effective_roles={"flowforge:admin"},
    )
    run_as = service.update_workflow_run_as(
        workspace_id="ws-1",
        workflow_definition_id=12,
        payload={"principal_type": "workspace_principal", "principal_id": "ws-1"},
        actor_user_id="user-1",
        effective_roles={"flowforge:admin"},
    )

    assert metadata["name"] == "Renamed Workflow"
    assert repo.metadata_update["description"] == "Updated description."
    assert owner["owner_user_id"] == "user-2"
    assert repo.grants[-1]["permission"] == "owner"
    assert run_as["run_as_principal"] == {
        "principal_type": "workspace_principal",
        "principal_id": "ws-1",
        "display_name": "Workspace principal",
    }


def test_flowforge_service_starts_manual_run_from_latest_published_version(monkeypatch):
    repo = _WorkflowRepo()
    repo.definitions[0]["latest_published_version_id"] = 44
    repo.versions[0]["version_status"] = "published"
    repo.versions[0]["graph_json"] = {
        "nodes": [
            {"id": "start", "type": "manual_start", "label": "Manual Start", "data": {"mode": "manual"}},
            {"id": "end", "type": "end", "label": "End", "data": {}},
        ],
        "edges": [{"id": "start-end", "source": "start", "target": "end"}],
    }
    runtime_repo = _RuntimeRepo()
    queued_dispatches = []
    monkeypatch.setattr(
        "app.tasks.flowforge_tasks.enqueue_flowforge_run_dispatch",
        lambda *, workspace_id, run_id: queued_dispatches.append((workspace_id, run_id)),
    )
    service = FlowForgeService(workflow_repository=repo, runtime_repository=runtime_repo)

    result = service.start_workflow_run(
        workspace_id="ws-1",
        workflow_definition_id=12,
        payload={"mode": "test", "idempotency_key": "manual-1", "input": {"reason": "smoke-test"}},
        actor_user_id="user-1",
        effective_roles={"flowforge:admin"},
    )

    assert result["run_id"] == 901
    assert result["workflow_version_id"] == 44
    assert runtime_repo.created_runs[0]["triggered_by_user_id"] == "user-1"
    assert runtime_repo.created_runs[0]["run_context"]["input"] == {"reason": "smoke-test"}
    assert runtime_repo.created_events[0]["event_type"] == "workflow.run.created"
    assert queued_dispatches == [("ws-1", 901)]


def test_flowforge_service_rejects_manual_run_for_invalid_published_graph(monkeypatch):
    repo = _WorkflowRepo()
    repo.definitions[0]["latest_published_version_id"] = 44
    repo.versions[0]["version_status"] = "published"
    repo.versions[0]["graph_json"] = {
        "nodes": [{"id": "match", "type": "matching", "data": {}}],
        "edges": [],
    }
    runtime_repo = _RuntimeRepo()
    monkeypatch.setattr(
        "app.tasks.flowforge_tasks.enqueue_flowforge_run_dispatch",
        lambda *, workspace_id, run_id: None,
    )
    service = FlowForgeService(workflow_repository=repo, runtime_repository=runtime_repo)

    with pytest.raises(ForgeError) as exc:
        service.start_workflow_run(
            workspace_id="ws-1",
            workflow_definition_id=12,
            payload={"mode": "test", "idempotency_key": "manual-1"},
            actor_user_id="user-1",
            effective_roles={"flowforge:admin"},
        )

    assert exc.value.status_code == 400
    assert exc.value.message == "Published workflow version is not runnable."
    blocker_codes = {item["code"] for item in exc.value.details["blockers"]}
    assert "matching_policy_required" in blocker_codes
    assert runtime_repo.created_runs == []


def test_flowforge_service_archives_persisted_workflow_definition():
    repo = _WorkflowRepo()
    service = FlowForgeService(workflow_repository=repo)

    result = service.delete_workflow_definition(
        workspace_id="ws-1",
        workflow_definition_id=12,
        actor_user_id="user-1",
    )

    assert result == {"deleted": True, "workflow_definition_id": 12}
    assert repo.archived_definition == {
        "workspace_id": "ws-1",
        "workflow_definition_id": 12,
        "archived_by": "user-1",
    }


def test_flowforge_service_delete_rejects_unknown_workflow_definition():
    repo = _WorkflowRepo()
    service = FlowForgeService(workflow_repository=repo)

    with pytest.raises(ForgeError) as exc:
        service.delete_workflow_definition(
            workspace_id="ws-1",
            workflow_definition_id=999,
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 404


def test_flowforge_service_lists_resource_sets_from_repository():
    service = FlowForgeService(resource_repository=_ResourceRepo())

    result = service.list_resource_sets(workspace_id="ws-1")

    assert result[0]["resource_set_key"] == "therapist-pool"
    assert result[0]["display_name"] == "Therapist Pool"


def test_flowforge_service_creates_resource_set_with_defaults():
    repo = _ResourceRepo()
    service = FlowForgeService(resource_repository=repo)

    result = service.create_resource_set(
        workspace_id="ws-1",
        payload={
            "resource_set_key": "resource-pool",
            "display_name": "Resource Pool",
            "settings": {"refresh": "manual"},
        },
        actor_user_id="user-1",
    )

    assert result["id"] == 21
    assert repo.created_payload == {
        "workspace_id": "ws-1",
        "resource_set_key": "resource-pool",
        "display_name": "Resource Pool",
        "description": None,
        "source_type": "manual_csv",
        "settings": {"refresh": "manual"},
        "created_by": "user-1",
    }


def test_flowforge_service_rejects_resource_set_without_key():
    service = FlowForgeService(resource_repository=_ResourceRepo())

    with pytest.raises(ForgeError) as exc:
        service.create_resource_set(
            workspace_id="ws-1",
            payload={"display_name": "Resource Pool"},
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400
    assert "resource_set_key" in str(exc.value)


def test_flowforge_service_updates_resource_set_enabled_state():
    repo = _ResourceRepo()
    service = FlowForgeService(resource_repository=repo)

    result = service.update_resource_set(
        workspace_id="ws-1",
        resource_set_id=20,
        payload={"enabled": False},
        actor_user_id="user-1",
    )

    assert result["enabled"] is False
    assert repo.updated_enabled == {
        "workspace_id": "ws-1",
        "resource_set_id": 20,
        "enabled": False,
        "updated_by": "user-1",
    }


def test_flowforge_service_deletes_resource_set():
    repo = _ResourceRepo()
    service = FlowForgeService(resource_repository=repo)

    result = service.delete_resource_set(workspace_id="ws-1", resource_set_id=20, actor_user_id="user-1")

    assert result == {"deleted": True, "resource_set_id": 20}
    assert repo.archived_resource_set == {
        "workspace_id": "ws-1",
        "resource_set_id": 20,
        "updated_by": "user-1",
    }


def test_flowforge_service_lists_resource_records_with_caps():
    service = FlowForgeService(resource_repository=_ResourceRepo())

    result = service.list_resource_records(
        workspace_id="ws-1",
        resource_set_id=20,
        limit=5000,
        offset=-10,
    )

    assert result["limit"] == 500
    assert result["offset"] == 0
    assert result["records"][0]["source_record_key"] == "resource-1"
    assert result["records"][0]["capacity_total"] == 5
    assert result["records"][0]["capacity_used"] == 2.5
    assert result["records"][0]["capacity_available"] == 2.5
    assert result["records"][0]["current_load"] == 2.5


def test_flowforge_service_updates_resource_record_values():
    repo = _ResourceRepo()
    service = FlowForgeService(resource_repository=repo)

    result = service.update_resource_record(
        workspace_id="ws-1",
        resource_set_id=20,
        record_id=300,
        payload={
            "display_name": "Jane Updated",
            "capacity_used": 4,
            "capacity_available": 1,
            "normalized_profile": {"insurance_carriers": "Aetna, Cigna"},
        },
        actor_user_id="user-1",
    )

    assert result["id"] == 300
    assert repo.updated_record["display_name"] == "Jane Updated"
    assert repo.updated_record["capacity_used"] == 4
    assert repo.updated_record["capacity_available"] == 1
    assert repo.updated_record["normalized_profile"]["insurance_carriers"] == "Aetna, Cigna"


def test_flowforge_service_deletes_resource_record():
    repo = _ResourceRepo()
    service = FlowForgeService(resource_repository=repo)

    result = service.delete_resource_record(workspace_id="ws-1", resource_set_id=20, record_id=300, actor_user_id="user-1")

    assert result == {"deleted": True, "resource_set_id": 20, "resource_record_id": 300}
    assert repo.deleted_record == {"workspace_id": "ws-1", "resource_set_id": 20, "record_id": 300}


def test_flowforge_service_lists_resource_snapshot_batches():
    service = FlowForgeService(resource_repository=_ResourceRepo())

    result = service.list_resource_snapshot_batches(workspace_id="ws-1", resource_set_id=20, limit=50)

    assert result[0]["batch_key"] == "manual-20260504"
    assert result[0]["summary"] == {"message": "ok"}


def test_flowforge_service_creates_manual_resource_snapshot():
    repo = _ResourceRepo(active_snapshot_batch_id=None)
    service = FlowForgeService(resource_repository=repo)

    result = service.create_manual_resource_snapshot(
        workspace_id="ws-1",
        resource_set_id=20,
        payload={
            "mode": "test",
            "batch_key": "manual-20260504",
            "activate": True,
            "records": [
                {
                    "source_record_key": "resource-1",
                    "display_name": "Jane Resource",
                    "primary_email": "jane@example.com",
                    "effective_status": "active",
                    "availability_status": "available",
                    "capacity_total": 5,
                    "capacity_used": 3,
                    "tags": ["telehealth"],
                    "attributes": {"languages": ["Spanish"]},
                }
            ],
        },
        actor_user_id="user-1",
    )

    assert result == {
        "resource_set_id": 20,
        "snapshot_batch_id": 31,
        "status": "completed",
        "record_count": 1,
        "valid_count": 1,
        "invalid_count": 0,
        "activated": True,
    }
    assert repo.created_batch["record_count"] == 1
    assert repo.upserted_records[0]["source_record_key"] == "resource-1"
    assert repo.upserted_records[0]["capacity_available"] == 2
    assert repo.upserted_records[0]["normalized_profile"]["display_name"] == "Jane Resource"


def test_flowforge_service_upserts_manual_records_into_active_snapshot():
    repo = _ResourceRepo(active_snapshot_batch_id=30)
    service = FlowForgeService(resource_repository=repo)

    result = service.create_manual_resource_snapshot(
        workspace_id="ws-1",
        resource_set_id=20,
        payload={
            "mode": "test",
            "activate": True,
            "records": [
                {"source_record_key": "resource-1", "display_name": "Jane Updated", "capacity_total": 5, "capacity_used": 4}
            ],
        },
        actor_user_id="user-1",
    )

    assert result["snapshot_batch_id"] == 30
    assert result["activated"] is True
    assert repo.created_batch is None
    assert repo.upserted_records[0]["snapshot_batch_id"] == 30
    assert repo.upserted_records[0]["source_record_key"] == "resource-1"
    assert repo.upserted_records[0]["display_name"] == "Jane Updated"
    assert repo.upserted_records[0]["capacity_available"] == 1


def test_flowforge_service_rejects_manual_snapshot_without_records():
    service = FlowForgeService(resource_repository=_ResourceRepo())

    with pytest.raises(ForgeError) as exc:
        service.create_manual_resource_snapshot(
            workspace_id="ws-1",
            resource_set_id=20,
            payload={"records": []},
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400
    assert "records" in str(exc.value)


def test_flowforge_service_validates_matching_policy():
    service = FlowForgeService(resource_repository=_ResourceRepo())

    result = service.validate_matching_policy(
        workspace_id="ws-1",
        payload={
            "policy": {
                "version": 1,
                "eligibility": [{"field": "effective_status", "operator": "equals", "value": "active"}],
            }
        },
    )

    assert result["valid"] is True


def test_flowforge_service_simulates_matching_policy_with_inline_resources():
    service = FlowForgeService(resource_repository=_ResourceRepo())

    result = service.simulate_matching_policy(
        workspace_id="ws-1",
        payload={
            "policy": {
                "version": 1,
                "eligibility": [{"field": "effective_status", "operator": "equals", "value": "active"}],
                "scoring": [{"field": "capacity_available", "operator": "gt", "value": 0, "weight": 5}],
            },
            "context": {},
            "resources": [
                {"source_record_key": "resource-1", "effective_status": "active", "capacity_available": 2},
                {"source_record_key": "resource-2", "effective_status": "on_hold", "capacity_available": 5},
            ],
        },
    )

    assert result["valid"] is True
    assert result["selected_candidate"]["source_record_key"] == "resource-1"
    assert result["ranked_candidates"][0]["score"] == 5


def test_flowforge_service_lists_matching_policies():
    service = FlowForgeService(resource_repository=_ResourceRepo(), matching_repository=_MatchingRepo())

    result = service.list_matching_policies(workspace_id="ws-1")

    assert result[0]["policy_key"] == "routing-policy"
    assert result[0]["current_draft_version_id"] == 77


def test_flowforge_service_creates_matching_policy_with_initial_valid_version():
    repo = _MatchingRepo()
    service = FlowForgeService(resource_repository=_ResourceRepo(), matching_repository=repo)

    result = service.create_matching_policy(
        workspace_id="ws-1",
        payload={
            "policy_key": "routing-policy",
            "display_name": "Routing Policy",
            "description": "Default routing rules.",
            "resource_set_id": 20,
            "policy": {
                "version": 1,
                "eligibility": [{"field": "effective_status", "operator": "equals", "value": "active"}],
            },
        },
        actor_user_id="user-1",
    )

    assert result["id"] == 5
    assert result["current_draft_version_id"] == 78
    assert repo.created_policy["policy_key"] == "routing-policy"
    assert repo.created_version["version_number"] == 2
    assert repo.created_version["validation_status"] == "valid"
    assert repo.current_draft["matching_policy_version_id"] == 78


def test_flowforge_service_deletes_matching_policy_without_published_versions():
    repo = _MatchingRepo()
    service = FlowForgeService(resource_repository=_ResourceRepo(), matching_repository=repo)

    result = service.delete_matching_policy(
        workspace_id="ws-1",
        matching_policy_id=5,
        actor_user_id="user-1",
    )

    assert result == {"deleted": True, "matching_policy_id": 5, "deleted_versions": 1}
    assert repo.deleted_policy == {"workspace_id": "ws-1", "matching_policy_id": 5, "updated_by": "user-1"}
    assert repo.deleted_policy_versions == {"workspace_id": "ws-1", "matching_policy_id": 5, "updated_by": "user-1"}


def test_flowforge_service_rejects_matching_policy_delete_with_published_versions():
    repo = _MatchingRepo()
    repo.versions[0]["version_status"] = "published"
    service = FlowForgeService(resource_repository=_ResourceRepo(), matching_repository=repo)

    with pytest.raises(ForgeError) as exc:
        service.delete_matching_policy(
            workspace_id="ws-1",
            matching_policy_id=5,
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400
    assert "published versions cannot be deleted" in exc.value.message
    assert repo.deleted_policy is None


def test_flowforge_service_rejects_invalid_matching_policy_version():
    service = FlowForgeService(resource_repository=_ResourceRepo(), matching_repository=_MatchingRepo())

    with pytest.raises(ForgeError) as exc:
        service.create_matching_policy_version(
            workspace_id="ws-1",
            matching_policy_id=5,
            payload={"policy": {"version": 2, "eligibility": []}},
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400
    assert exc.value.details["errors"] == ["policy.version must be 1."]


def test_flowforge_service_lists_matching_policy_versions():
    service = FlowForgeService(resource_repository=_ResourceRepo(), matching_repository=_MatchingRepo())

    result = service.list_matching_policy_versions(workspace_id="ws-1", matching_policy_id=5)

    assert result[0]["id"] == 77
    assert result[0]["policy"] == {"version": 1, "eligibility": []}
    assert result[0]["validation_result"] == {"errors": [], "warnings": []}


def test_flowforge_service_deletes_non_published_matching_policy_version():
    repo = _MatchingRepo()
    service = FlowForgeService(resource_repository=_ResourceRepo(), matching_repository=repo)

    result = service.delete_matching_policy_version(
        workspace_id="ws-1",
        matching_policy_id=5,
        matching_policy_version_id=77,
        actor_user_id="user-1",
    )

    assert result == {"deleted": True, "matching_policy_id": 5, "matching_policy_version_id": 77}
    assert repo.deleted_version == {
        "workspace_id": "ws-1",
        "matching_policy_id": 5,
        "matching_policy_version_id": 77,
        "updated_by": "user-1",
    }
    assert repo.cleared_current_draft == {
        "workspace_id": "ws-1",
        "matching_policy_id": 5,
        "matching_policy_version_id": 77,
        "updated_by": "user-1",
    }


def test_flowforge_service_rejects_published_matching_policy_version_delete():
    repo = _MatchingRepo()
    repo.versions[0]["version_status"] = "published"
    service = FlowForgeService(resource_repository=_ResourceRepo(), matching_repository=repo)

    with pytest.raises(ForgeError) as exc:
        service.delete_matching_policy_version(
            workspace_id="ws-1",
            matching_policy_id=5,
            matching_policy_version_id=77,
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400
    assert "Published matching policy versions cannot be deleted" in exc.value.message


def test_flowforge_service_creates_matching_policy_llm_draft_with_validation_metadata():
    repo = _MatchingRepo()
    llm_calls = []

    def _runtime_builder(**payload):
        llm_calls.append(payload)
        return SimpleNamespace(
            client=_FakeFlowForgeRuleDraftingLLM(),
            provider="openai",
            model="gpt-flowforge",
        )

    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=repo,
        llm_runtime_builder=_runtime_builder,
    )

    result = service.create_matching_policy_llm_draft(
        workspace_id="ws-1",
        matching_policy_id=5,
        payload={"prompt": "Prefer active and available resources.", "use_llm": True},
        actor_user_id="user-1",
    )

    assert result["id"] == 92
    assert result["validation_status"] == "valid"
    assert result["draft_source"] == "llm"
    assert repo.created_llm_draft["generated_policy"]["eligibility"][0]["operator"] == "equals"
    assert repo.created_llm_draft["generated_policy"]["eligibility"][1]["operator"] == "contains_context"
    assert repo.created_llm_draft["generated_policy"]["eligibility"][1]["context_field"] == "preferred_languages"
    assert repo.created_llm_draft["generated_policy"]["scoring"][0]["weight"] == 5
    assert repo.created_llm_draft["created_by"] == "user-1"
    assert repo.created_llm_draft["model_provider"] == "openai"
    assert repo.created_llm_draft["model_name"] == "gpt-flowforge"
    assert llm_calls == [{"workspace_id": "ws-1", "role": "flowforge_rule_drafting"}]


def test_flowforge_service_requires_workspace_llm_config_for_llm_drafting():
    def _runtime_builder(**payload):
        raise ForgeError("No LLM configuration found for role", status_code=404, details=payload)

    service = FlowForgeService(
        resource_repository=_ResourceRepo(),
        matching_repository=_MatchingRepo(),
        llm_runtime_builder=_runtime_builder,
    )

    with pytest.raises(ForgeError) as exc:
        service.create_matching_policy_llm_draft(
            workspace_id="ws-1",
            matching_policy_id=5,
            payload={"prompt": "Prefer active resources.", "use_llm": True},
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 404
    assert exc.value.details == {"workspace_id": "ws-1", "role": "flowforge_rule_drafting"}


def test_flowforge_service_accepts_matching_policy_llm_draft_as_version():
    repo = _MatchingRepo()
    service = FlowForgeService(resource_repository=_ResourceRepo(), matching_repository=repo)

    result = service.accept_matching_policy_llm_draft(
        workspace_id="ws-1",
        matching_policy_id=5,
        draft_id=91,
        actor_user_id="user-1",
    )

    assert result["draft"]["status"] == "accepted"
    assert result["version"]["id"] == 78
    assert repo.created_version["policy"] == {"version": 1, "eligibility": []}
    assert repo.reviewed_draft["status"] == "accepted"


def test_flowforge_service_rejects_invalid_matching_policy_llm_draft_acceptance():
    repo = _MatchingRepo()
    repo.llm_drafts[0]["generated_policy_json"] = {"version": 2, "eligibility": []}
    service = FlowForgeService(resource_repository=_ResourceRepo(), matching_repository=repo)

    with pytest.raises(ForgeError) as exc:
        service.accept_matching_policy_llm_draft(
            workspace_id="ws-1",
            matching_policy_id=5,
            draft_id=91,
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400
    assert exc.value.details["errors"] == ["policy.version must be 1."]


def test_flowforge_service_creates_and_reads_dataset_artifact_metadata():
    repo = _DataMovementRepo()
    service = FlowForgeService(data_movement_repository=repo)

    created = service.create_dataset_artifact(
        workspace_id="ws-1",
        payload={
            "run_id": 90,
            "node_id": "extract-1",
            "artifact_key": "run-90-extract-2",
            "artifact_type": "query_extract",
            "storage_ref": {"query_id": "saved-1"},
            "schema": {"columns": ["id"]},
            "row_count": 12,
            "byte_count": 512,
        },
        actor_user_id="user-1",
    )
    listed = service.list_dataset_artifacts(workspace_id="ws-1", run_id=90)
    fetched = service.get_dataset_artifact(workspace_id="ws-1", artifact_id=10)

    assert created["artifact_key"] == "run-90-extract-2"
    assert created["storage_ref"] == {"query_id": "saved-1"}
    assert repo.created_artifact["created_by"] == "user-1"
    assert listed["artifacts"][0]["artifact_key"] == "run-90-extract"
    assert fetched["schema"] == {"columns": ["id"]}


def test_flowforge_service_records_data_movement_audit_without_side_effects():
    repo = _DataMovementRepo()
    service = FlowForgeService(data_movement_repository=repo)

    audit = service.record_data_movement_audit(
        workspace_id="ws-1",
        payload={
            "run_id": 90,
            "node_id": "export-1",
            "action_type": "export",
            "status": "completed",
            "destination_key": "ops-email",
            "dataset_artifact_id": 10,
            "request": {"format": "csv"},
            "result": {"row_count": 12},
            "idempotency_key": "audit:90:export",
        },
        actor_user_id="user-1",
    )

    assert audit["action_type"] == "export"
    assert audit["status"] == "completed"
    assert audit["request"] == {"format": "csv"}
    assert repo.created_audit["actor_type"] == "user"
    assert repo.created_audit["actor_id"] == "user-1"


def test_flowforge_service_upserts_and_redacts_data_source_and_destination_allowlists():
    repo = _DataMovementRepo()
    service = FlowForgeService(data_movement_repository=repo)

    source = service.upsert_data_source(
        workspace_id="ws-1",
        payload={
            "source_key": "jotform-intake",
            "display_name": "Jotform Intake",
            "source_type": "jotform",
            "mode": "test",
            "config": {"api_key": "secret", "form_id": "abc"},
        },
        actor_user_id="user-1",
    )
    destination = service.upsert_data_destination(
        workspace_id="ws-1",
        payload={
            "destination_key": "ops-email",
            "display_name": "Ops Email",
            "destination_type": "email",
            "mode": "test",
            "config": {"token": "secret", "to": ["ops@example.com"]},
        },
        actor_user_id="user-1",
    )
    disabled_source = service.set_data_source_enabled(
        workspace_id="ws-1",
        source_key="jotform-intake",
        enabled=False,
        actor_user_id="user-1",
    )

    assert source["config"] == {"api_key": "********", "form_id": "abc"}
    assert destination["config"] == {"token": "********", "to": ["ops@example.com"]}
    assert repo.upserted_source["config"]["api_key"] == "secret"
    assert repo.upserted_destination["config"]["token"] == "secret"
    assert disabled_source["enabled"] is False
    assert repo.updated_source_enabled["updated_by"] == "user-1"


def test_flowforge_service_validates_data_movement_contracts():
    service = FlowForgeService(data_movement_repository=_DataMovementRepo())

    with pytest.raises(ForgeError) as exc:
        service.upsert_data_source(
            workspace_id="ws-1",
            payload={"source_key": "bad", "display_name": "Bad", "source_type": "unknown"},
            actor_user_id="user-1",
        )

    assert exc.value.status_code == 400
    assert "source_type must be one of" in exc.value.message

    with pytest.raises(ForgeError) as key_exc:
        service.upsert_data_destination(
            workspace_id="ws-1",
            payload={"destination_key": "../bad", "display_name": "Bad", "destination_type": "email"},
            actor_user_id="user-1",
        )

    assert key_exc.value.status_code == 400
    assert "destination_key must start with a letter or number" in key_exc.value.message
