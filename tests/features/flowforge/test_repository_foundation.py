from __future__ import annotations

import json
from datetime import datetime, timezone

from app.adapters.query_port import QueryExecResult
from app.features.flowforge.repositories import (
    FlowForgeCommunicationTemplateRepository,
    FlowForgeDataMovementRepository,
    FlowForgeIntegrationRepository,
    FlowForgeMatchingRepository,
    FlowForgeResourceRepository,
    FlowForgeRuntimeRepository,
    FlowForgeSettingsRepository,
    FlowForgeWorkflowRepository,
)


class _SQL:
    def __init__(self, *, rows=None, lastrowid=101, write_count=1) -> None:
        self.rows = list(rows or [])
        self.lastrowid = lastrowid
        self.write_count = write_count
        self.inserts = []
        self.queries = []
        self.writes = []

    def execute_insert(self, query, params=None):
        self.inserts.append((query, dict(params or {})))
        return QueryExecResult(rowcount=1, lastrowid=self.lastrowid)

    def execute_query_mappings(self, query, params=None):
        self.queries.append((query, dict(params or {})))
        return list(self.rows)

    def execute_write(self, query, params=None):
        self.writes.append((query, dict(params or {})))
        return self.write_count


def test_flowforge_settings_repository_returns_defaults_when_missing():
    repo = FlowForgeSettingsRepository(sql=_SQL(rows=[]))

    settings = repo.get_settings(workspace_id="ws-1")

    assert settings == {
        "workspace_id": "ws-1",
        "enabled": False,
        "allow_designer_publish": False,
        "block_sensitive_reporting_mcp": False,
        "raw_payload_retention_days": 30,
        "raw_payload_retention_max_days": 90,
        "default_offer_timeout_minutes": 1440,
        "default_no_match_recipients": [],
        "default_test_recipients": [],
        "settings": {},
    }


def test_flowforge_settings_repository_upserts_workspace_settings():
    sql = _SQL(
        rows=[
            {
                "workspace_id": "ws-1",
                "enabled": 1,
                "allow_designer_publish": 0,
                "raw_payload_retention_days": 45,
                "raw_payload_retention_max_days": 90,
                "default_offer_timeout_minutes": 120,
                "default_no_match_recipients_json": '["ops@example.com"]',
                "default_test_recipients_json": '["test@example.com"]',
                "settings_json": '{"notify_on_timeout":true}',
            }
        ]
    )
    repo = FlowForgeSettingsRepository(sql=sql)

    settings = repo.upsert_settings(
        workspace_id="ws-1",
        payload={
            "enabled": True,
            "allow_designer_publish": False,
            "raw_payload_retention_days": 45,
            "raw_payload_retention_max_days": 90,
            "default_offer_timeout_minutes": 120,
            "default_no_match_recipients": ["ops@example.com"],
            "default_test_recipients": ["test@example.com"],
            "settings": {"notify_on_timeout": True},
        },
    )

    query, params = sql.writes[0]
    assert "INSERT INTO flowforge_workspace_settings" in query
    assert "ON DUPLICATE KEY UPDATE" in query
    assert params["default_no_match_recipients_json"] == '["ops@example.com"]'
    assert settings["default_test_recipients"] == ["test@example.com"]


def test_flowforge_integration_repository_purges_expired_raw_payloads():
    sql = _SQL(write_count=3)
    repo = FlowForgeIntegrationRepository(sql=sql)

    purged = repo.purge_expired_raw_payloads(limit=250)

    query, params = sql.writes[0]
    assert purged == 3
    assert "raw_payload_json = NULL" in query
    assert "sensitive_fields_json = NULL" in query
    assert "raw_payload_expires_at <= CURRENT_TIMESTAMP" in query
    assert params == {"limit": 250}


def test_flowforge_data_movement_repository_expires_dataset_artifacts():
    sql = _SQL(write_count=4)
    repo = FlowForgeDataMovementRepository(sql=sql)

    expired = repo.expire_dataset_artifacts(limit=250)

    query, params = sql.writes[0]
    assert expired == 4
    assert "UPDATE flowforge_dataset_artifacts" in query
    assert "SET status = 'expired'" in query
    assert "expires_at <= CURRENT_TIMESTAMP" in query
    assert "status NOT IN ('expired', 'deleted')" in query
    assert params == {"limit": 250}


def test_flowforge_communication_template_repository_creates_and_lists_templates():
    sql = _SQL(
        rows=[
            {
                "id": 501,
                "workspace_id": "ws-1",
                "template_key": "therapist-task",
                "display_name": "Therapist Task",
                "description": None,
                "channel": "email",
                "purpose": "human_task",
                "resource_set_id": 30,
                "subject": "New task",
                "body_blocks_json": '[{"type":"text","content":"Hello"}]',
                "status": "draft",
                "validation_status": "valid",
                "validation_result_json": '{"valid":true,"errors":[],"warnings":[]}',
                "metadata_json": "{}",
            }
        ],
        lastrowid=501,
    )
    repo = FlowForgeCommunicationTemplateRepository(sql=sql)

    created = repo.create_template(
        workspace_id="ws-1",
        template_key="therapist-task",
        display_name="Therapist Task",
        description=None,
        channel="email",
        purpose="human_task",
        resource_set_id=30,
        subject="New task",
        body_blocks=[{"type": "text", "content": "Hello"}],
        status="draft",
        validation_status="valid",
        validation_result={"valid": True, "errors": [], "warnings": []},
        metadata={},
        created_by="user-1",
    )
    rows = repo.list_templates(workspace_id="ws-1", status="draft", purpose="human_task", channel="email", resource_set_id=30)

    insert_query, params = sql.inserts[0]
    assert created["id"] == 501
    assert "INSERT INTO flowforge_communication_templates" in insert_query
    assert json.loads(params["body_blocks_json"]) == [{"type": "text", "content": "Hello"}]
    assert rows[0]["body_blocks_json"] == [{"type": "text", "content": "Hello"}]
    assert rows[0]["validation_result_json"]["valid"] is True


def test_flowforge_communication_template_repository_gets_active_template_by_key():
    sql = _SQL(
        rows=[
            {
                "id": 501,
                "workspace_id": "ws-1",
                "template_key": "therapist-task",
                "display_name": "Therapist Task",
                "description": None,
                "channel": "email",
                "purpose": "human_task",
                "resource_set_id": 30,
                "subject": "New task",
                "body_blocks_json": '[{"type":"text","content":"Hello"}]',
                "status": "active",
                "validation_status": "valid",
                "validation_result_json": '{"valid":true,"errors":[],"warnings":[]}',
                "metadata_json": "{}",
            }
        ],
    )
    repo = FlowForgeCommunicationTemplateRepository(sql=sql)

    row = repo.get_active_template_by_key(workspace_id="ws-1", template_key="therapist-task", channel="email")

    query, params = sql.queries[0]
    assert row is not None
    assert row["template_key"] == "therapist-task"
    assert "status = 'active'" in query
    assert "validation_status = 'valid'" in query
    assert params == {"workspace_id": "ws-1", "template_key": "therapist-task", "channel": "email"}


def test_flowforge_communication_template_repository_creates_ai_draft():
    sql = _SQL(lastrowid=601)
    repo = FlowForgeCommunicationTemplateRepository(sql=sql)

    created = repo.create_ai_draft(
        workspace_id="ws-1",
        purpose="human_task",
        channel="email",
        resource_set_id=30,
        prompt="Write a task email.",
        tone="concise",
        required_actions=["accept", "decline"],
        generated_subject="Action requested",
        generated_body_blocks=[{"type": "action_buttons", "actions": ["accept", "decline"]}],
        plain_language_summary="Generated a task email.",
        validation_status="valid",
        validation_result={"valid": True, "errors": [], "warnings": []},
        model_provider="heuristic",
        model_name="flowforge-local-communication-template-draft-generator",
        status="drafted",
        created_by="user-1",
    )

    query, params = sql.inserts[0]
    assert created["id"] == 601
    assert "INSERT INTO flowforge_communication_template_ai_drafts" in query
    assert json.loads(params["required_actions_json"]) == ["accept", "decline"]
    assert json.loads(params["generated_body_blocks_json"])[0]["type"] == "action_buttons"


def test_flowforge_workflow_repository_creates_definition_with_owner_and_run_as_defaults():
    sql = _SQL(lastrowid=12)
    repo = FlowForgeWorkflowRepository(sql=sql)

    created_id = repo.create_workflow_definition(
        workspace_id="ws-1",
        workflow_key="intake-routing",
        name="Intake Routing",
        description="Routes intake submissions.",
        created_by="user-1",
    )

    query, params = sql.inserts[0]
    assert created_id == 12
    assert "INSERT INTO flowforge_workflow_definitions" in query
    assert "owner_user_id" in query
    assert "run_as_principal_type" in query
    assert "run_as_principal_id" in query
    assert "lifecycle" in query
    assert params["owner_user_id"] == "user-1"
    assert params["run_as_principal_type"] == "user"
    assert params["run_as_principal_id"] == "user-1"
    assert params["lifecycle"] == "development"


def test_flowforge_workflow_repository_serializes_graph_when_creating_version():
    sql = _SQL(lastrowid=44)
    repo = FlowForgeWorkflowRepository(sql=sql)

    created_id = repo.create_workflow_version(
        workspace_id="ws-1",
        workflow_definition_id=12,
        version_number=1,
        graph={"nodes": [{"id": "intake"}], "edges": []},
        created_by="user-1",
        version_status="draft",
        validation_status="pending",
    )

    query, params = sql.inserts[0]
    assert created_id == 44
    assert "INSERT INTO flowforge_workflow_versions" in query
    assert params["workspace_id"] == "ws-1"
    assert json.loads(params["graph_json"]) == {"nodes": [{"id": "intake"}], "edges": []}


def test_flowforge_workflow_repository_lists_and_gets_definitions_with_current_graph():
    sql = _SQL(
        rows=[
            {
                "id": 12,
                "workspace_id": "ws-1",
                "workflow_key": "intake-routing",
                "name": "Intake Routing",
                "description": "Routes intake submissions.",
                "status": "draft",
                "graph_json": '{"nodes":[{"id":"intake"}],"edges":[]}',
                "validation_status": "valid",
                "validation_result_json": '{"errors":[],"warnings":[]}',
            }
        ]
    )
    repo = FlowForgeWorkflowRepository(sql=sql)

    definitions = repo.list_workflow_definitions(workspace_id="ws-1")
    definition = repo.get_workflow_definition(workspace_id="ws-1", workflow_definition_id=12)

    assert "FROM flowforge_workflow_definitions" in sql.queries[0][0]
    assert definitions[0]["graph_json"] == {"nodes": [{"id": "intake"}], "edges": []}
    assert definition["name"] == "Intake Routing"


def test_flowforge_workflow_repository_lists_and_publishes_versions():
    sql = _SQL(
        rows=[
            {
                "id": 44,
                "workspace_id": "ws-1",
                "workflow_definition_id": 12,
                "version_number": 1,
                "version_status": "draft",
                "graph_json": '{"nodes":[{"id":"intake"}],"edges":[]}',
                "validation_status": "valid",
                "validation_result_json": '{"errors":[],"warnings":[]}',
                "matching_policy_refs_json": "[]",
                "settings_json": "{}",
            }
        ]
    )
    repo = FlowForgeWorkflowRepository(sql=sql)

    versions = repo.list_workflow_versions(workspace_id="ws-1", workflow_definition_id=12)
    version = repo.get_workflow_version(workspace_id="ws-1", workflow_definition_id=12, version_id=44)
    published = repo.publish_workflow_version(
        workspace_id="ws-1",
        workflow_definition_id=12,
        version_id=44,
        published_by="user-1",
    )

    assert versions[0]["graph_json"] == {"nodes": [{"id": "intake"}], "edges": []}
    assert version["id"] == 44
    assert published is True
    assert "UPDATE flowforge_workflow_versions" in sql.writes[0][0]
    assert "UPDATE flowforge_workflow_definitions" in sql.writes[1][0]


def test_flowforge_workflow_repository_sets_current_draft_version():
    sql = _SQL()
    repo = FlowForgeWorkflowRepository(sql=sql)

    updated = repo.set_current_draft_version(
        workspace_id="ws-1",
        workflow_definition_id=12,
        version_id=45,
        updated_by="user-1",
    )

    assert updated is True
    assert "current_draft_version_id" in sql.writes[0][0]
    assert sql.writes[0][1]["version_id"] == 45


def test_flowforge_workflow_repository_archives_workflow_definition():
    sql = _SQL()
    repo = FlowForgeWorkflowRepository(sql=sql)

    archived = repo.archive_workflow_definition(
        workspace_id="ws-1",
        workflow_definition_id=12,
        archived_by="user-1",
    )

    query, params = sql.writes[0]
    assert archived is True
    assert "archived_at = CURRENT_TIMESTAMP" in query
    assert "archived_by = :archived_by" in query
    assert "archived_at IS NULL" in query
    assert params == {
        "workspace_id": "ws-1",
        "workflow_definition_id": 12,
        "archived_by": "user-1",
    }


def test_flowforge_workflow_repository_updates_owner_run_as_and_acl():
    sql = _SQL(
        rows=[
            {
                "id": 71,
                "workspace_id": "ws-1",
                "workflow_definition_id": 12,
                "principal_type": "user",
                "principal_id": "designer-1",
                "permission": "edit",
            }
        ],
        lastrowid=71,
    )
    repo = FlowForgeWorkflowRepository(sql=sql)

    owner_updated = repo.update_workflow_owner(
        workspace_id="ws-1",
        workflow_definition_id=12,
        owner_user_id="owner-2",
        updated_by="admin-1",
    )
    run_as_updated = repo.update_workflow_run_as(
        workspace_id="ws-1",
        workflow_definition_id=12,
        principal_type="service_principal",
        principal_id="workflow-runner",
        updated_by="admin-1",
    )
    grant_id = repo.grant_workflow_permission(
        workspace_id="ws-1",
        workflow_definition_id=12,
        principal_type="user",
        principal_id="designer-1",
        permission="edit",
        granted_by="admin-1",
    )
    acl = repo.list_workflow_acl(workspace_id="ws-1", workflow_definition_id=12)
    revoked = repo.revoke_workflow_permission(
        workspace_id="ws-1",
        workflow_definition_id=12,
        principal_type="user",
        principal_id="designer-1",
        revoked_by="admin-1",
    )

    assert owner_updated is True
    assert run_as_updated is True
    assert grant_id == 71
    assert revoked is True
    assert "owner_user_id = :owner_user_id" in sql.writes[0][0]
    assert "run_as_principal_type = :principal_type" in sql.writes[1][0]
    assert "INSERT INTO flowforge_workflow_acl" in sql.inserts[0][0]
    assert "ON DUPLICATE KEY UPDATE" in sql.inserts[0][0]
    assert "FROM flowforge_workflow_acl" in sql.queries[0][0]
    assert "revoked_at IS NULL" in sql.queries[0][0]
    assert acl[0]["permission"] == "edit"
    assert "UPDATE flowforge_workflow_acl" in sql.writes[2][0]
    assert sql.writes[2][1]["revoked_by"] == "admin-1"


def test_flowforge_runtime_repository_dashboard_metrics_are_production_scoped_and_redacted():
    sql = _SQL(
        rows=[
            {
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
        ]
    )
    repo = FlowForgeRuntimeRepository(sql=sql)

    metrics = repo.get_reporting_dashboard_metrics(workspace_id="ws-1", mode="production")

    query, params = sql.queries[0]
    assert metrics["run_count"] == 8
    assert params == {"workspace_id": "ws-1", "mode": "production"}
    assert "flowforge_intake_events" in query
    assert "flowforge_assignments" in query
    assert "flowforge_dataset_artifacts" in query
    assert "flowforge_data_movement_audit" in query
    assert "raw_payload_json" not in query
    assert "recipient" not in query
    assert "sensitive_profile_json" not in query


def test_flowforge_data_movement_repository_creates_and_lists_dataset_artifacts():
    sql = _SQL(
        rows=[
            {
                "id": 10,
                "workspace_id": "ws-1",
                "run_id": 90,
                "node_id": "extract-1",
                "artifact_key": "run-90-extract",
                "artifact_type": "query_extract",
                "storage_kind": "metadata_only",
                "storage_ref_json": '{"query_id":"saved-1"}',
                "schema_json": '{"columns":["id"]}',
                "row_count": 12,
                "byte_count": 512,
                "checksum": "sha256:abc",
                "status": "ready",
            }
        ],
        lastrowid=10,
    )
    repo = FlowForgeDataMovementRepository(sql=sql)

    created = repo.create_dataset_artifact(
        workspace_id="ws-1",
        run_id=90,
        node_id="extract-1",
        artifact_key="run-90-extract",
        artifact_type="query_extract",
        storage_kind="metadata_only",
        storage_ref={"query_id": "saved-1"},
        schema={"columns": ["id"]},
        row_count=12,
        byte_count=512,
        checksum="sha256:abc",
        status="ready",
        expires_at=None,
        created_by="user-1",
    )
    listed = repo.list_dataset_artifacts(workspace_id="ws-1", run_id=90, limit=50, offset=0)

    assert created["id"] == 10
    assert "INSERT INTO flowforge_dataset_artifacts" in sql.inserts[0][0]
    assert json.loads(sql.inserts[0][1]["storage_ref_json"]) == {"query_id": "saved-1"}
    assert listed[0]["storage_ref_json"] == {"query_id": "saved-1"}
    assert listed[0]["schema_json"] == {"columns": ["id"]}


def test_flowforge_data_movement_repository_records_audit_and_upserts_allowlists():
    sql = _SQL(lastrowid=30)
    repo = FlowForgeDataMovementRepository(sql=sql)

    audit = repo.create_data_movement_audit(
        workspace_id="ws-1",
        run_id=90,
        node_id="export-1",
        action_type="export",
        status="completed",
        source_key=None,
        destination_key="ops-email",
        dataset_artifact_id=10,
        resource_set_id=None,
        actor_type="system",
        actor_id="flowforge",
        request={"format": "csv"},
        result={"row_count": 12},
        error_message=None,
        idempotency_key="audit:90:export",
        completed_at=None,
    )
    sql.rows = [
        {
            "id": 20,
            "workspace_id": "ws-1",
            "source_key": "jotform-intake",
            "display_name": "Jotform Intake",
            "source_type": "jotform",
            "enabled": 1,
            "mode": "test",
            "config_json": '{"api_key":"secret","form_id":"abc"}',
        }
    ]
    source = repo.upsert_data_source(
        workspace_id="ws-1",
        source_key="jotform-intake",
        display_name="Jotform Intake",
        source_type="jotform",
        enabled=True,
        mode="test",
        config={"api_key": "secret", "form_id": "abc"},
        actor_user_id="user-1",
    )

    assert audit["id"] == 30
    assert "INSERT INTO flowforge_data_movement_audit" in sql.inserts[0][0]
    assert json.loads(sql.inserts[0][1]["request_json"]) == {"format": "csv"}
    assert "INSERT INTO flowforge_data_sources" in sql.writes[0][0]
    assert "ON DUPLICATE KEY UPDATE" in sql.writes[0][0]
    assert source["enabled"] is True
    assert source["config_json"] == {"api_key": "secret", "form_id": "abc"}


def test_flowforge_data_movement_repository_creates_schedule_run_ledger():
    sql = _SQL(lastrowid=77)
    repo = FlowForgeDataMovementRepository(sql=sql)

    created_id = repo.create_schedule_run(
        workspace_id="ws-1",
        workflow_definition_id=12,
        workflow_version_id=44,
        trigger_node_id="schedule",
        schedule_key="daily-provider-refresh",
        scheduled_for="2026-05-06 08:00:00",
        window_start="2026-05-06 08:00:00",
        window_end="2026-05-07 08:00:00",
        status="pending",
        run_id=None,
        idempotency_key="schedule:daily-provider-refresh:202605060800",
        trigger_payload={"timezone": "America/Chicago"},
    )

    query, params = sql.inserts[0]
    assert created_id == 77
    assert "INSERT INTO flowforge_schedule_runs" in query
    assert params["trigger_node_id"] == "schedule"
    assert params["idempotency_key"] == "schedule:daily-provider-refresh:202605060800"
    assert json.loads(params["trigger_payload_json"]) == {"timezone": "America/Chicago"}


def test_flowforge_workflow_repository_lists_published_schedule_workflow_versions():
    sql = _SQL(
        rows=[
            {
                "workspace_id": "ws-1",
                "workflow_definition_id": 12,
                "workflow_key": "daily-provider-refresh",
                "name": "Daily Provider Refresh",
                "workflow_version_id": 44,
                "version_number": 3,
                "graph_json": '{"nodes":[{"id":"schedule","type":"schedule_trigger"}],"edges":[]}',
                "settings_json": "{}",
                "published_at": "2026-05-06 08:00:00",
            }
        ]
    )
    repo = FlowForgeWorkflowRepository(sql=sql)

    rows = repo.list_published_schedule_workflow_versions(limit=25)

    query, params = sql.queries[0]
    assert "d.status = 'published'" in query
    assert "v.version_status = 'published'" in query
    assert "v.graph_json LIKE '%schedule_trigger%'" in query
    assert params == {"limit": 25}
    assert rows[0]["graph_json"]["nodes"][0]["id"] == "schedule"


def test_flowforge_integration_repository_creates_intake_event_with_retention_and_idempotency():
    received_at = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    expires_at = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    sql = _SQL(lastrowid=55)
    repo = FlowForgeIntegrationRepository(sql=sql)

    intake_id = repo.create_intake_event(
        workspace_id="ws-1",
        integration_config_id=10,
        provider="jotform",
        external_form_id="form-1",
        external_submission_id="sub-1",
        mode="test",
        idempotency_key="jotform:form-1:sub-1",
        normalized_payload={"patient_type": "new"},
        raw_payload={"rawRequest": "{}"},
        trigger_evaluation={"matched_trigger_count": 1},
        received_at=received_at,
        raw_payload_expires_at=expires_at,
    )

    query, params = sql.inserts[0]
    assert intake_id == 55
    assert "INSERT INTO flowforge_intake_events" in query
    assert params["mode"] == "test"
    assert params["idempotency_key"] == "jotform:form-1:sub-1"
    assert json.loads(params["normalized_payload_json"]) == {"patient_type": "new"}
    assert json.loads(params["raw_payload_json"]) == {"rawRequest": "{}"}
    assert json.loads(params["trigger_evaluation_json"]) == {"matched_trigger_count": 1}
    assert params["raw_payload_expires_at"] == expires_at


def test_flowforge_integration_repository_lists_and_creates_configs_without_secret_leakage():
    sql = _SQL(
        rows=[
            {
                "id": 10,
                "workspace_id": "ws-1",
                "provider": "jotform",
                "integration_key": "intake-form",
                "display_name": "Intake Form",
                "external_form_id": "form-1",
                "enabled": 1,
                "mode": "test",
                "webhook_public_id": "ffj_public",
                "secret_hash": "hash-not-returned-by-service",
                "field_mapping_json": '{"patient":"patientName"}',
                "test_recipient_overrides_json": '["ops@example.com"]',
                "settings_json": '{"trigger_policy":"all_matching"}',
            }
        ],
        lastrowid=10,
    )
    repo = FlowForgeIntegrationRepository(sql=sql)

    created = repo.create_integration_config(
        workspace_id="ws-1",
        provider="jotform",
        integration_key="intake-form",
        display_name="Intake Form",
        webhook_public_id="ffj_public",
        secret_hash="secret-hash",
        external_form_id="form-1",
        mode="test",
        field_mapping={"patient": "patientName"},
        test_recipient_overrides=["ops@example.com"],
        settings={"trigger_policy": "all_matching"},
        created_by="user-1",
    )
    listed = repo.list_integration_configs(workspace_id="ws-1", provider="jotform")

    assert created["id"] == 10
    assert "INSERT INTO flowforge_integration_configs" in sql.inserts[0][0]
    assert sql.inserts[0][1]["secret_hash"] == "secret-hash"
    assert json.loads(sql.inserts[0][1]["field_mapping_json"]) == {"patient": "patientName"}
    assert listed[0]["enabled"] is True
    assert listed[0]["field_mapping_json"] == {"patient": "patientName"}
    assert listed[0]["test_recipient_overrides_json"] == ["ops@example.com"]


def test_flowforge_integration_repository_updates_integration_settings():
    sql = _SQL(
        rows=[
            {
                "id": 10,
                "workspace_id": "ws-1",
                "provider": "jotform",
                "integration_key": "intake-form",
                "display_name": "Intake Form",
                "enabled": 1,
                "mode": "test",
                "webhook_public_id": "ffj_public",
                "field_mapping_json": "{}",
                "test_recipient_overrides_json": "[]",
                "settings_json": '{"workflow_value_schema":{"fields":[]}}',
            }
        ]
    )
    repo = FlowForgeIntegrationRepository(sql=sql)

    updated = repo.update_integration_settings(
        workspace_id="ws-1",
        integration_config_id=10,
        settings={"workflow_value_schema": {"fields": [{"key": "values.patient.email"}]}},
    )

    query, params = sql.writes[0]
    assert updated is not None
    assert "UPDATE flowforge_integration_configs" in query
    assert params["integration_config_id"] == 10
    assert json.loads(params["settings_json"]) == {
        "workflow_value_schema": {"fields": [{"key": "values.patient.email"}]}
    }


def test_flowforge_integration_repository_gets_public_config_and_idempotent_event():
    sql = _SQL(
        rows=[
            {
                "id": 10,
                "workspace_id": "ws-1",
                "provider": "jotform",
                "webhook_public_id": "ffj_public",
                "enabled": 1,
                "field_mapping_json": "{}",
                "test_recipient_overrides_json": "[]",
                "settings_json": "{}",
                "idempotency_key": "jotform:ffj_public:submission:sub-1",
                "headers_json": '{"User-Agent":"Jotform"}',
                "raw_payload_json": '{"submissionID":"sub-1"}',
                "normalized_payload_json": '{"submission_id":"sub-1"}',
                "sensitive_fields_json": "{}",
                "trigger_evaluation_json": '{"matched_trigger_count":1}',
            }
        ]
    )
    repo = FlowForgeIntegrationRepository(sql=sql)

    config = repo.get_integration_config_by_public_id(webhook_public_id="ffj_public")
    event = repo.get_intake_event_by_idempotency(
        workspace_id="ws-1",
        idempotency_key="jotform:ffj_public:submission:sub-1",
    )

    assert config is not None
    assert config["enabled"] is True
    assert event is not None
    assert event["headers_json"] == {"User-Agent": "Jotform"}
    assert event["normalized_payload_json"] == {"submission_id": "sub-1"}
    assert event["trigger_evaluation_json"] == {"matched_trigger_count": 1}


def test_flowforge_integration_repository_creates_and_lists_triggers():
    sql = _SQL(
        rows=[
            {
                "id": 66,
                "workspace_id": "ws-1",
                "integration_config_id": 10,
                "trigger_key": "intake-routing",
                "display_name": "Intake Routing",
                "enabled": 1,
                "priority": 25,
                "trigger_mode": "conditional",
                "trigger_policy": "first_matching",
                "version_strategy": "pinned",
                "workflow_definition_id": 12,
                "workflow_version_id": 13,
                "condition_json": '{"fields.caseType":"new"}',
                "field_mapping_json": '{"patient_name":"fields.name"}',
                "no_match_config_json": '{"notify":["ops@example.com"]}',
            }
        ],
        lastrowid=66,
    )
    repo = FlowForgeIntegrationRepository(sql=sql)

    created = repo.create_integration_trigger(
        workspace_id="ws-1",
        integration_config_id=10,
        trigger_key="intake-routing",
        display_name="Intake Routing",
        priority=25,
        trigger_mode="conditional",
        trigger_policy="first_matching",
        version_strategy="pinned",
        workflow_definition_id=12,
        workflow_version_id=13,
        condition={"fields.caseType": "new"},
        field_mapping={"patient_name": "fields.name"},
        no_match_config={"notify": ["ops@example.com"]},
        created_by="user-1",
    )
    listed = repo.list_integration_triggers(workspace_id="ws-1", integration_config_id=10)

    assert created["id"] == 66
    assert "INSERT INTO flowforge_integration_triggers" in sql.inserts[0][0]
    assert json.loads(sql.inserts[0][1]["condition_json"]) == {"fields.caseType": "new"}
    assert listed[0]["enabled"] is True
    assert listed[0]["condition_json"] == {"fields.caseType": "new"}
    assert listed[0]["field_mapping_json"] == {"patient_name": "fields.name"}
    assert listed[0]["no_match_config_json"] == {"notify": ["ops@example.com"]}


def test_flowforge_resource_repository_decodes_snapshot_record_json_and_booleans():
    sql = _SQL(
        rows=[
            {
                "source_record_key": "resource-1",
                "display_name": "Jane Resource",
                "source_missing": 0,
                "tags_json": '["spanish","telehealth"]',
                "attributes_json": '{"languages":["Spanish"]}',
                "normalized_profile_json": '{"display_name":"Jane Resource"}',
                "sensitive_profile_json": '{"dob":"redacted"}',
                "validation_errors_json": "[]",
            }
        ]
    )
    repo = FlowForgeResourceRepository(sql=sql)

    record = repo.get_snapshot_record(
        workspace_id="ws-1",
        resource_set_id=20,
        snapshot_batch_id=30,
        source_record_key="resource-1",
    )

    assert record is not None
    assert record["source_missing"] is False
    assert record["tags_json"] == ["spanish", "telehealth"]
    assert record["attributes_json"] == {"languages": ["Spanish"]}
    assert record["normalized_profile_json"] == {"display_name": "Jane Resource"}
    assert record["sensitive_profile_json"] == {"dob": "redacted"}
    assert record["validation_errors_json"] == []


def test_flowforge_resource_repository_gets_resource_set_and_batch_records():
    sql = _SQL(
        rows=[
            {
                "id": 20,
                "workspace_id": "ws-1",
                "resource_set_key": "resources",
                "display_name": "Resources",
                "enabled": 1,
                "active_snapshot_batch_id": 30,
                "settings_json": "{}",
                "source_record_key": "resource-1",
                "source_missing": 0,
                "tags_json": "[]",
                "attributes_json": '{"languages":["Spanish"]}',
                "normalized_profile_json": "{}",
                "sensitive_profile_json": "{}",
                "validation_errors_json": "[]",
            }
        ]
    )
    repo = FlowForgeResourceRepository(sql=sql)

    resource_set = repo.get_resource_set(workspace_id="ws-1", resource_set_id=20)
    records = repo.list_snapshot_records_for_batch(
        workspace_id="ws-1",
        resource_set_id=20,
        snapshot_batch_id=30,
        limit=5000,
    )
    active_records = repo.list_snapshot_records(workspace_id="ws-1", resource_set_id=20, limit=100, offset=0)

    assert resource_set is not None
    assert resource_set["active_snapshot_batch_id"] == 30
    assert "snapshot_batch_id = :snapshot_batch_id" in sql.queries[1][0]
    assert records[0]["attributes_json"] == {"languages": ["Spanish"]}
    assert "active_snapshot_batch_id = records.snapshot_batch_id" in sql.queries[2][0]
    assert active_records[0]["source_record_key"] == "resource-1"


def test_flowforge_resource_repository_creates_snapshot_batch_and_record():
    sql = _SQL(lastrowid=31)
    repo = FlowForgeResourceRepository(sql=sql)

    batch_id = repo.create_snapshot_batch(
        workspace_id="ws-1",
        resource_set_id=20,
        batch_key="manual-20260504",
        source_type="manual_csv",
        mode="test",
        record_count=1,
        source_ref={"filename": "resources.csv"},
        created_by="user-1",
    )
    record_id = repo.create_snapshot_record(
        workspace_id="ws-1",
        resource_set_id=20,
        snapshot_batch_id=batch_id,
        source_record_key="resource-1",
        display_name="Jane Resource",
        primary_email="jane@example.com",
        primary_phone=None,
        status="active",
        effective_status="active",
        availability_status="available",
        capacity_total=5,
        capacity_used=3,
        capacity_available=2,
        current_load=3,
        service_area="Austin",
        timezone="America/Chicago",
        tags=["telehealth"],
        attributes={"languages": ["Spanish"]},
        normalized_profile={"display_name": "Jane Resource"},
        sensitive_profile=None,
        validation_status="valid",
        validation_errors=[],
        source_missing=False,
        source_updated_at=None,
    )

    assert batch_id == 31
    assert record_id == 31
    assert "INSERT INTO flowforge_resource_snapshot_batches" in sql.inserts[0][0]
    assert "INSERT INTO flowforge_resource_snapshot_records" in sql.inserts[1][0]
    assert json.loads(sql.inserts[1][1]["tags_json"]) == ["telehealth"]
    assert json.loads(sql.inserts[1][1]["normalized_profile_json"]) == {"display_name": "Jane Resource"}


def test_flowforge_resource_repository_upserts_snapshot_record_by_source_key():
    sql = _SQL(
        rows=[
            {
                "id": 300,
                "source_record_key": "resource-1",
                "source_missing": 0,
                "tags_json": "[]",
                "attributes_json": "{}",
                "normalized_profile_json": "{}",
                "sensitive_profile_json": "{}",
                "validation_errors_json": "[]",
            }
        ],
        write_count=1,
    )
    repo = FlowForgeResourceRepository(sql=sql)

    record_id = repo.upsert_snapshot_record(
        workspace_id="ws-1",
        resource_set_id=20,
        snapshot_batch_id=30,
        source_record_key="resource-1",
        display_name="Jane Updated",
        primary_email="jane@example.com",
        primary_phone=None,
        status="active",
        effective_status="active",
        availability_status="available",
        capacity_total=5,
        capacity_used=4,
        capacity_available=1,
        current_load=4,
        service_area="Austin",
        timezone="America/Chicago",
        tags=["telehealth"],
        attributes={"languages": ["Spanish"]},
        normalized_profile={"display_name": "Jane Updated"},
        sensitive_profile=None,
        validation_status="valid",
        validation_errors=[],
        source_missing=False,
        source_updated_at=None,
    )

    assert record_id == 300
    assert "source_record_key = :source_record_key" in sql.queries[0][0]
    assert "UPDATE flowforge_resource_snapshot_records" in sql.writes[0][0]
    assert not sql.inserts


def test_flowforge_resource_repository_updates_and_deletes_snapshot_record():
    sql = _SQL(write_count=1)
    repo = FlowForgeResourceRepository(sql=sql)

    updated = repo.update_snapshot_record(
        workspace_id="ws-1",
        resource_set_id=20,
        record_id=300,
        source_record_key="resource-1",
        display_name="Jane Updated",
        primary_email="jane@example.com",
        primary_phone=None,
        status="active",
        effective_status="active",
        availability_status="available",
        capacity_total=5,
        capacity_used=4,
        capacity_available=1,
        current_load=4,
        service_area="Austin",
        timezone="America/Chicago",
        tags=["telehealth"],
        attributes={"languages": ["Spanish"]},
        normalized_profile={"display_name": "Jane Updated"},
        validation_status="valid",
        validation_errors=[],
        source_missing=False,
        source_updated_at=None,
    )
    deleted = repo.delete_snapshot_record(workspace_id="ws-1", resource_set_id=20, record_id=300)

    assert updated is True
    assert deleted is True
    assert "UPDATE flowforge_resource_snapshot_records" in sql.writes[0][0]
    assert json.loads(sql.writes[0][1]["normalized_profile_json"]) == {"display_name": "Jane Updated"}
    assert "DELETE FROM flowforge_resource_snapshot_records" in sql.writes[1][0]


def test_flowforge_resource_repository_completes_batch_and_activates_resource_set():
    sql = _SQL(write_count=1)
    repo = FlowForgeResourceRepository(sql=sql)

    completed = repo.complete_snapshot_batch(
        workspace_id="ws-1",
        snapshot_batch_id=31,
        valid_count=1,
        invalid_count=0,
        summary={"message": "ok"},
    )
    activated = repo.activate_snapshot_batch(
        workspace_id="ws-1",
        resource_set_id=20,
        snapshot_batch_id=31,
    )

    assert completed is True
    assert activated is True
    assert "UPDATE flowforge_resource_snapshot_batches" in sql.writes[0][0]
    assert "UPDATE flowforge_resource_sets" in sql.writes[1][0]
    assert json.loads(sql.writes[0][1]["summary_json"]) == {"message": "ok"}


def test_flowforge_resource_repository_updates_and_archives_resource_set():
    sql = _SQL(write_count=1)
    repo = FlowForgeResourceRepository(sql=sql)

    updated = repo.update_resource_set_enabled(workspace_id="ws-1", resource_set_id=20, enabled=False, updated_by="user-1")
    archived = repo.archive_resource_set(workspace_id="ws-1", resource_set_id=20, updated_by="user-1")

    assert updated is True
    assert archived is True
    assert "SET enabled = :enabled" in sql.writes[0][0]
    assert sql.writes[0][1]["enabled"] == 0
    assert "SET enabled = 0" in sql.writes[1][0]
    assert "archived_at = CURRENT_TIMESTAMP" in sql.writes[1][0]


def test_flowforge_resource_repository_updates_runtime_state_counts():
    sql = _SQL(write_count=1)
    repo = FlowForgeResourceRepository(sql=sql)

    offered = repo.mark_resource_offered(workspace_id="ws-1", resource_set_id=20, source_record_key="resource-1")
    assigned = repo.mark_resource_assigned(workspace_id="ws-1", resource_set_id=20, source_record_key="resource-1")
    declined = repo.mark_resource_declined(workspace_id="ws-1", resource_set_id=20, source_record_key="resource-1")

    assert offered is True
    assert assigned is True
    assert declined is True
    assert "flowforge_resource_runtime_state" in sql.writes[0][0]
    assert "last_offered_at" in sql.writes[0][0]
    assert "last_accepted_at" in sql.writes[1][0]
    assert "last_declined_at" in sql.writes[2][0]


def test_flowforge_matching_repository_serializes_policy_version_and_context():
    sql = _SQL(lastrowid=77)
    repo = FlowForgeMatchingRepository(sql=sql)

    version_id = repo.create_policy_version(
        workspace_id="ws-1",
        matching_policy_id=5,
        resource_set_id=20,
        version_number=1,
        policy={
            "version": 1,
            "resource_set_id": "resources",
            "eligibility": [{"field": "status", "operator": "equals", "value": "active"}],
        },
        created_by="user-1",
    )

    query, params = sql.inserts[0]
    assert version_id == 77
    assert "INSERT INTO flowforge_matching_policy_versions" in query
    assert json.loads(params["policy_json"])["eligibility"][0]["operator"] == "equals"


def test_flowforge_matching_repository_creates_and_lists_policies():
    rows = [
        {
            "id": 5,
            "workspace_id": "ws-1",
            "policy_key": "routing-policy",
            "display_name": "Routing Policy",
            "resource_set_id": 20,
            "status": "draft",
            "current_draft_version_id": 77,
        }
    ]
    sql = _SQL(rows=rows, lastrowid=5)
    repo = FlowForgeMatchingRepository(sql=sql)

    created = repo.create_policy(
        workspace_id="ws-1",
        policy_key="routing-policy",
        display_name="Routing Policy",
        description=None,
        resource_set_id=20,
        created_by="user-1",
    )
    listed = repo.list_policies(workspace_id="ws-1")

    assert created["id"] == 5
    assert created["policy_key"] == "routing-policy"
    assert "INSERT INTO flowforge_matching_policies" in sql.inserts[0][0]
    assert listed[0]["current_draft_version_id"] == 77


def test_flowforge_matching_repository_archives_policy_and_deletes_non_published_versions():
    sql = _SQL(write_count=2)
    repo = FlowForgeMatchingRepository(sql=sql)

    archived = repo.archive_policy(workspace_id="ws-1", matching_policy_id=5, updated_by="user-1")
    deleted_versions = repo.delete_non_published_policy_versions(workspace_id="ws-1", matching_policy_id=5, updated_by="user-1")

    assert archived is True
    assert deleted_versions == 2
    assert "SET archived_at = CURRENT_TIMESTAMP" in sql.writes[0][0]
    assert "SET version_status = 'deleted'" in sql.writes[1][0]
    assert "version_status <> 'published'" in sql.writes[1][0]


def test_flowforge_matching_repository_decodes_policy_versions_and_sets_current_draft():
    sql = _SQL(
        rows=[
            {
                "id": 77,
                "workspace_id": "ws-1",
                "matching_policy_id": 5,
                "resource_set_id": 20,
                "version_number": 1,
                "version_status": "draft",
                "policy_json": '{"version":1,"eligibility":[]}',
                "validation_status": "valid",
                "validation_result_json": '{"errors":[],"warnings":[]}',
                "explanation_template_json": None,
            }
        ],
        write_count=1,
    )
    repo = FlowForgeMatchingRepository(sql=sql)

    versions = repo.list_policy_versions(workspace_id="ws-1", matching_policy_id=5)
    updated = repo.set_current_draft_version(
        workspace_id="ws-1",
        matching_policy_id=5,
        matching_policy_version_id=77,
        updated_by="user-1",
    )

    assert versions[0]["policy_json"] == {"version": 1, "eligibility": []}
    assert versions[0]["validation_result_json"] == {"errors": [], "warnings": []}
    assert updated is True
    assert "UPDATE flowforge_matching_policies" in sql.writes[0][0]


def test_flowforge_matching_repository_soft_deletes_policy_version_and_filters_lists():
    sql = _SQL(
        rows=[
            {
                "id": 77,
                "workspace_id": "ws-1",
                "matching_policy_id": 5,
                "resource_set_id": 20,
                "version_number": 1,
                "version_status": "draft",
                "policy_json": '{"version":1,"eligibility":[]}',
                "validation_status": "valid",
                "validation_result_json": '{"errors":[],"warnings":[]}',
                "explanation_template_json": None,
            }
        ],
        write_count=1,
    )
    repo = FlowForgeMatchingRepository(sql=sql)

    versions = repo.list_policy_versions(workspace_id="ws-1", matching_policy_id=5)
    deleted = repo.delete_policy_version(
        workspace_id="ws-1",
        matching_policy_id=5,
        matching_policy_version_id=77,
        updated_by="user-1",
    )
    cleared = repo.clear_current_draft_version(
        workspace_id="ws-1",
        matching_policy_id=5,
        matching_policy_version_id=77,
        updated_by="user-1",
    )

    assert versions[0]["id"] == 77
    assert "version_status <> 'deleted'" in sql.queries[0][0]
    assert deleted is True
    assert cleared is True
    assert "SET version_status = 'deleted'" in sql.writes[0][0]
    assert "current_draft_version_id = NULL" in sql.writes[1][0]


def test_flowforge_matching_repository_creates_and_lists_llm_drafts():
    sql = _SQL(
        rows=[
            {
                "id": 91,
                "workspace_id": "ws-1",
                "matching_policy_id": 5,
                "resource_set_id": 20,
                "prompt": "Prefer available resources.",
                "generated_policy_json": '{"version":1,"eligibility":[]}',
                "plain_language_summary": "A simple draft.",
                "validation_status": "valid",
                "validation_result_json": '{"errors":[],"warnings":[]}',
                "model_provider": "heuristic",
                "model_name": "flowforge-local-draft-generator",
                "status": "drafted",
            }
        ],
        lastrowid=91,
        write_count=1,
    )
    repo = FlowForgeMatchingRepository(sql=sql)

    created = repo.create_llm_draft(
        workspace_id="ws-1",
        matching_policy_id=5,
        resource_set_id=20,
        prompt="Prefer available resources.",
        generated_policy={"version": 1, "eligibility": []},
        plain_language_summary="A simple draft.",
        validation_status="valid",
        validation_result={"errors": [], "warnings": []},
        model_provider="heuristic",
        model_name="flowforge-local-draft-generator",
        status="drafted",
        created_by="user-1",
    )
    listed = repo.list_llm_drafts(workspace_id="ws-1", matching_policy_id=5)
    reviewed = repo.mark_llm_draft_reviewed(
        workspace_id="ws-1",
        matching_policy_id=5,
        draft_id=91,
        status="accepted",
        reviewed_by="user-1",
    )

    assert created["id"] == 91
    assert "INSERT INTO flowforge_matching_policy_llm_drafts" in sql.inserts[0][0]
    assert listed[0]["generated_policy_json"] == {"version": 1, "eligibility": []}
    assert listed[0]["validation_result_json"] == {"errors": [], "warnings": []}
    assert reviewed is True
    assert "UPDATE flowforge_matching_policy_llm_drafts" in sql.writes[0][0]


def test_flowforge_matching_repository_gets_policy_version_by_id():
    sql = _SQL(
        rows=[
            {
                "id": 77,
                "workspace_id": "ws-1",
                "matching_policy_id": 5,
                "resource_set_id": 20,
                "version_number": 2,
                "version_status": "published",
                "policy_json": '{"version":1,"eligibility":[]}',
                "validation_status": "valid",
                "validation_result_json": '{"errors":[],"warnings":[]}',
                "explanation_template_json": "{}",
            }
        ]
    )
    repo = FlowForgeMatchingRepository(sql=sql)

    version = repo.get_policy_version(workspace_id="ws-1", version_id=77)

    query, params = sql.queries[0]
    assert "FROM flowforge_matching_policy_versions" in query
    assert params["version_id"] == 77
    assert version is not None
    assert version["policy_json"] == {"version": 1, "eligibility": []}


def test_flowforge_runtime_repository_appends_idempotent_run_event():
    sql = _SQL(lastrowid=88)
    repo = FlowForgeRuntimeRepository(sql=sql)

    event_id = repo.append_run_event(
        workspace_id="ws-1",
        run_id=9,
        event_type="workflow.run.started",
        node_id="intake",
        message="Run started.",
        event_payload={"mode": "test"},
        actor_type="system",
        actor_id="flowforge",
        idempotency_key="run-9:started",
    )

    query, params = sql.inserts[0]
    assert event_id == 88
    assert "INSERT INTO flowforge_run_events" in query
    assert params["idempotency_key"] == "run-9:started"
    assert json.loads(params["event_payload_json"]) == {"mode": "test"}


def test_flowforge_runtime_repository_gets_run_event_by_idempotency():
    sql = _SQL(
        rows=[
            {
                "id": 88,
                "workspace_id": "ws-1",
                "run_id": 9,
                "event_type": "workflow.dispatch.started",
                "node_id": None,
                "message": "Workflow dispatch started.",
                "event_payload_json": '{"run_id":9}',
                "sensitive_payload_json": "{}",
                "actor_type": "system",
                "actor_id": "flowforge",
                "idempotency_key": "run-9:dispatch:started",
            }
        ]
    )
    repo = FlowForgeRuntimeRepository(sql=sql)

    event = repo.get_run_event_by_idempotency(workspace_id="ws-1", idempotency_key="run-9:dispatch:started")

    query, params = sql.queries[0]
    assert "FROM flowforge_run_events" in query
    assert params["idempotency_key"] == "run-9:dispatch:started"
    assert event is not None
    assert event["event_payload_json"] == {"run_id": 9}


def test_flowforge_runtime_repository_creates_and_reads_run_by_idempotency():
    sql = _SQL(
        rows=[
            {
                "id": 90,
                "workspace_id": "ws-1",
                "workflow_definition_id": 12,
                "workflow_version_id": 13,
                "intake_event_id": 501,
                "mode": "test",
                "status": "waiting",
                "current_node_id": "intake",
                "idempotency_key": "intake:501:trigger:66",
                "run_context_json": '{"trigger_key":"intake-routing"}',
            }
        ],
        lastrowid=90,
    )
    repo = FlowForgeRuntimeRepository(sql=sql)

    run_id = repo.create_run(
        workspace_id="ws-1",
        workflow_definition_id=12,
        workflow_version_id=13,
        intake_event_id=501,
        mode="test",
        run_as_principal_type="service_principal",
        run_as_principal_id="workflow-runner",
        triggered_by_user_id="operator-1",
        status="waiting",
        current_node_id="intake",
        idempotency_key="intake:501:trigger:66",
        run_context={"trigger_key": "intake-routing"},
    )
    existing = repo.get_run_by_idempotency(
        workspace_id="ws-1",
        idempotency_key="intake:501:trigger:66",
    )

    assert run_id == 90
    assert "INSERT INTO flowforge_runs" in sql.inserts[0][0]
    assert sql.inserts[0][1]["run_as_principal_type"] == "service_principal"
    assert sql.inserts[0][1]["run_as_principal_id"] == "workflow-runner"
    assert sql.inserts[0][1]["triggered_by_user_id"] == "operator-1"
    assert json.loads(sql.inserts[0][1]["run_context_json"]) == {"trigger_key": "intake-routing"}
    assert existing is not None
    assert existing["run_context_json"] == {"trigger_key": "intake-routing"}


def test_flowforge_runtime_repository_completes_and_fails_runs():
    sql = _SQL(write_count=1)
    repo = FlowForgeRuntimeRepository(sql=sql)

    completed = repo.complete_run(workspace_id="ws-1", run_id=90, current_node_id="end")
    failed = repo.fail_run(
        workspace_id="ws-1",
        run_id=91,
        current_node_id="match",
        error_code="unsupported_node",
        error_message="Unsupported FlowForge node type.",
    )

    complete_query, complete_params = sql.writes[0]
    fail_query, fail_params = sql.writes[1]
    assert completed is True
    assert failed is True
    assert "completed_at = CURRENT_TIMESTAMP" in complete_query
    assert complete_params["current_node_id"] == "end"
    assert "failed_at = CURRENT_TIMESTAMP" in fail_query
    assert fail_params["run_id"] == 91


def test_flowforge_runtime_repository_updates_run_context():
    sql = _SQL(write_count=1)
    repo = FlowForgeRuntimeRepository(sql=sql)

    updated = repo.update_run_context(
        workspace_id="ws-1",
        run_id=90,
        run_context={"flowforge_matching": {"candidate_keys": ["resource-1"]}},
    )

    query, params = sql.writes[0]
    assert updated is True
    assert "SET run_context_json = :run_context_json" in query
    assert json.loads(params["run_context_json"]) == {"flowforge_matching": {"candidate_keys": ["resource-1"]}}


def test_flowforge_runtime_repository_persists_matching_evaluations_and_candidates():
    sql = _SQL(lastrowid=77)
    repo = FlowForgeRuntimeRepository(sql=sql)

    evaluation_id = repo.create_matching_evaluation(
        workspace_id="ws-1",
        run_id=90,
        matching_policy_version_id=44,
        resource_set_id=20,
        snapshot_batch_id=30,
        input_context={"intake": {"caseType": "new"}},
        summary={"eligible_count": 1},
        selected_source_record_key="resource-1",
        no_match_reason=None,
        status="completed",
    )
    candidate_id = repo.create_matching_evaluation_candidate(
        workspace_id="ws-1",
        matching_evaluation_id=evaluation_id,
        resource_set_id=20,
        candidate={
            "source_record_key": "resource-1",
            "included": True,
            "excluded": False,
            "rank_position": 1,
            "score": 5,
            "eligibility_result": [{"passed": True}],
            "score_breakdown": [{"weight": 5}],
            "explanation": "Included with score 5.",
            "exclusion_reasons": [],
        },
        selected=True,
    )

    assert evaluation_id == 77
    assert candidate_id == 77
    assert "INSERT INTO flowforge_matching_evaluations" in sql.inserts[0][0]
    assert json.loads(sql.inserts[0][1]["summary_json"]) == {"eligible_count": 1}
    assert "INSERT INTO flowforge_matching_evaluation_candidates" in sql.inserts[1][0]
    assert sql.inserts[1][1]["selected"] == 1
    assert json.loads(sql.inserts[1][1]["explanation_json"]) == {
        "explanation": "Included with score 5.",
        "exclusion_reasons": [],
    }


def test_flowforge_runtime_repository_lists_runs_and_events():
    sql = _SQL(
        rows=[
            {
                "id": 90,
                "workspace_id": "ws-1",
                "workflow_definition_id": 12,
                "workflow_version_id": 13,
                "intake_event_id": 501,
                "mode": "test",
                "status": "waiting",
                "current_node_id": "intake",
                "idempotency_key": "intake:501:trigger:66",
                "run_context_json": '{"trigger_key":"intake-routing"}',
                "event_payload_json": '{"trigger_key":"intake-routing"}',
                "sensitive_payload_json": "{}",
            }
        ]
    )
    repo = FlowForgeRuntimeRepository(sql=sql)

    runs = repo.list_runs(workspace_id="ws-1", status="waiting", mode="test", limit=25, offset=5)
    run = repo.get_run(workspace_id="ws-1", run_id=90)
    events = repo.list_run_events(workspace_id="ws-1", run_id=90, limit=50)

    assert "FROM flowforge_runs" in sql.queries[0][0]
    assert sql.queries[0][1]["status"] == "waiting"
    assert sql.queries[0][1]["mode"] == "test"
    assert runs[0]["run_context_json"] == {"trigger_key": "intake-routing"}
    assert run is not None
    assert run["id"] == 90
    assert events[0]["event_payload_json"] == {"trigger_key": "intake-routing"}


def test_flowforge_runtime_repository_creates_and_lists_human_tasks():
    sql = _SQL(
        rows=[
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
                "due_at": "2026-05-05 12:00:00",
                "completed_at": None,
                "response_json": '{"allowed_actions":["accept","decline"]}',
            }
        ],
        lastrowid=301,
    )
    repo = FlowForgeRuntimeRepository(sql=sql)

    created_id = repo.create_human_task(
        workspace_id="ws-1",
        run_id=90,
        task_type="offer",
        resource_set_id=20,
        source_record_key="resource-1",
        status="pending",
        assigned_to_principal_type="resource",
        assigned_to_principal_id="resource-1",
        due_at="2026-05-05 12:00:00",
        response={"allowed_actions": ["accept", "decline"]},
    )
    tasks = repo.list_run_human_tasks(workspace_id="ws-1", run_id=90, limit=25)

    query, params = sql.inserts[0]
    assert created_id == 301
    assert "INSERT INTO flowforge_human_tasks" in query
    assert params["task_type"] == "offer"
    assert json.loads(params["response_json"]) == {"allowed_actions": ["accept", "decline"]}
    assert tasks[0]["id"] == 301
    assert tasks[0]["response_json"] == {"allowed_actions": ["accept", "decline"]}


def test_flowforge_runtime_repository_creates_human_task_with_idempotency_key():
    sql = _SQL(rows=[], lastrowid=301)
    repo = FlowForgeRuntimeRepository(sql=sql)

    created_id = repo.create_human_task(
        workspace_id="ws-1",
        run_id=90,
        task_type="offer",
        resource_set_id=20,
        source_record_key="resource-1",
        status="pending",
        assigned_to_principal_type="resource",
        assigned_to_principal_id="resource-1",
        due_at="2026-05-05 12:00:00",
        response={},
        idempotency_key="run:90:offer:resource-1:task",
    )

    assert created_id == 301
    assert sql.inserts[0][1]["idempotency_key"] == "run:90:offer:resource-1:task"


def test_flowforge_runtime_repository_reuses_idempotent_human_task():
    sql = _SQL(rows=[{"id": 301, "response_json": "{}"}], lastrowid=999)
    repo = FlowForgeRuntimeRepository(sql=sql)

    created_id = repo.create_human_task(
        workspace_id="ws-1",
        run_id=90,
        task_type="offer",
        resource_set_id=20,
        source_record_key="resource-1",
        status="pending",
        assigned_to_principal_type="resource",
        assigned_to_principal_id="resource-1",
        due_at="2026-05-05 12:00:00",
        response={},
        idempotency_key="run:90:offer:resource-1:task",
    )

    assert created_id == 301
    assert sql.inserts == []
    assert "FROM flowforge_human_tasks" in sql.queries[0][0]


def test_flowforge_runtime_repository_creates_assignment_idempotently():
    sql = _SQL(rows=[], lastrowid=501)
    repo = FlowForgeRuntimeRepository(sql=sql)

    assignment_id = repo.create_assignment(
        workspace_id="ws-1",
        run_id=90,
        human_task_id=301,
        resource_set_id=20,
        source_record_key="resource-1",
        status="assigned",
        assignment={"source": "signed_action"},
        idempotency_key="run:90:assignment:resource-1",
    )

    query, params = sql.inserts[0]
    assert assignment_id == 501
    assert "INSERT INTO flowforge_assignments" in query
    assert params["idempotency_key"] == "run:90:assignment:resource-1"
    assert json.loads(params["assignment_json"]) == {"source": "signed_action"}


def test_flowforge_runtime_repository_lists_due_human_tasks():
    sql = _SQL(
        rows=[
            {
                "id": 301,
                "workspace_id": "ws-1",
                "run_id": 90,
                "task_type": "offer",
                "resource_set_id": 20,
                "source_record_key": "resource-1",
                "status": "pending",
                "due_at": "2026-05-05 12:00:00",
                "response_json": "{}",
            }
        ]
    )
    repo = FlowForgeRuntimeRepository(sql=sql)

    tasks = repo.list_due_human_tasks(limit=25)

    query, params = sql.queries[0]
    assert "due_at <= CURRENT_TIMESTAMP" in query
    assert params["limit"] == 25
    assert tasks[0]["id"] == 301
    assert tasks[0]["response_json"] == {}


def test_flowforge_runtime_repository_manages_signed_action_tokens_and_task_response():
    sql = _SQL(
        rows=[
            {
                "id": 401,
                "workspace_id": "ws-1",
                "human_task_id": 301,
                "token_hash": "hash-1",
                "allowed_actions_json": '["accept","decline"]',
                "expires_at": "2099-01-01 00:00:00",
                "used_at": None,
                "used_action": None,
                "used_ip": None,
                "revoked_at": None,
                "task_type": "offer",
                "run_id": 90,
                "task_status": "pending",
                "resource_set_id": 20,
                "source_record_key": "resource-1",
                "response_json": "{}",
            }
        ],
        lastrowid=401,
    )
    repo = FlowForgeRuntimeRepository(sql=sql)

    created_id = repo.create_signed_action_token(
        workspace_id="ws-1",
        human_task_id=301,
        token_hash="hash-1",
        allowed_actions=["accept", "decline"],
        expires_at="2099-01-01 00:00:00",
    )
    token = repo.get_signed_action_token(token_hash="hash-1")
    marked = repo.mark_signed_action_token_used(token_hash="hash-1", used_action="accept", used_ip="203.0.113.9")
    updated = repo.update_human_task_response(
        workspace_id="ws-1",
        human_task_id=301,
        status="accepted",
        response={"action": "accept"},
    )

    assert created_id == 401
    assert "INSERT INTO flowforge_signed_action_tokens" in sql.inserts[0][0]
    assert json.loads(sql.inserts[0][1]["allowed_actions_json"]) == ["accept", "decline"]
    assert token["allowed_actions_json"] == ["accept", "decline"]
    assert token["response_json"] == {}
    assert marked is True
    assert updated is True


def test_flowforge_runtime_repository_manages_run_notifications_and_status():
    sql = _SQL(
        rows=[
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
                "payload_summary_json": '{"reason":"No eligible resources."}',
                "provider_message_id": None,
                "error_message": None,
                "created_at": "2026-05-05 12:00:00",
                "sent_at": None,
                "failed_at": None,
            }
        ],
        lastrowid=701,
    )
    repo = FlowForgeRuntimeRepository(sql=sql)

    created_id = repo.create_notification(
        workspace_id="ws-1",
        run_id=90,
        human_task_id=None,
        channel="email",
        recipient="ops@example.com",
        template_key="flowforge.no_match",
        status="pending",
        idempotency_key="no-match:90:ops@example.com",
        payload_summary={"reason": "No eligible resources."},
    )
    notifications = repo.list_run_notifications(workspace_id="ws-1", run_id=90, limit=25)
    updated = repo.update_run_status(workspace_id="ws-1", run_id=90, status="needs_attention", current_node_id="no_match")

    assert created_id == 701
    assert "INSERT INTO flowforge_notifications" in sql.inserts[0][0]
    assert json.loads(sql.inserts[0][1]["payload_summary_json"]) == {"reason": "No eligible resources."}
    assert notifications[0]["payload_summary_json"] == {"reason": "No eligible resources."}
    assert updated is True


def test_flowforge_runtime_repository_lists_and_marks_pending_notifications():
    sql = _SQL(
        rows=[
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
                "payload_summary_json": '{"reason":"No eligible resources."}',
            }
        ],
        write_count=1,
    )
    repo = FlowForgeRuntimeRepository(sql=sql)

    pending = repo.list_pending_notifications(limit=25)
    sent = repo.mark_notification_sent(workspace_id="ws-1", notification_id=701, provider_message_id="local-email")
    failed = repo.mark_notification_failed(workspace_id="ws-1", notification_id=702, error_message="smtp unavailable")

    assert pending[0]["payload_summary_json"] == {"reason": "No eligible resources."}
    assert sent is True
    assert failed is True
    assert "status = 'sent'" in sql.writes[0][0]
    assert "status = 'failed'" in sql.writes[1][0]


def test_flowforge_runtime_repository_returns_report_summary():
    sql = _SQL(
        rows=[
            {
                "run_count": 10,
                "active_run_count": 3,
                "completed_run_count": 4,
                "failed_run_count": 1,
                "needs_attention_count": 2,
                "test_run_count": 2,
                "production_run_count": 8,
            }
        ]
    )
    repo = FlowForgeRuntimeRepository(sql=sql)

    summary = repo.get_report_summary(workspace_id="ws-1", mode="production")

    query, params = sql.queries[0]
    assert "FROM flowforge_runs" in query
    assert params["workspace_id"] == "ws-1"
    assert params["mode"] == "production"
    assert summary["run_count"] == 10
    assert summary["needs_attention_count"] == 2
