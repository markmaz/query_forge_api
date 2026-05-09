from __future__ import annotations

from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


def _migration_text(name: str) -> str:
    return (MIGRATIONS_DIR / name).read_text(encoding="utf-8")


def test_flowforge_workspace_workflow_migration_defines_publish_and_version_tables():
    sql = _migration_text("20260504_flowforge_workspace_workflows.sql")

    assert "CREATE TABLE IF NOT EXISTS flowforge_workspace_settings" in sql
    assert "allow_designer_publish TINYINT(1) NOT NULL DEFAULT 0" in sql
    assert "raw_payload_retention_days SMALLINT UNSIGNED NOT NULL DEFAULT 30" in sql
    assert "raw_payload_retention_max_days SMALLINT UNSIGNED NOT NULL DEFAULT 90" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_workflow_definitions" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_workflow_versions" in sql
    assert "UNIQUE KEY uidx_ff_workflow_key" in sql


def test_flowforge_integrations_migration_defines_idempotent_intake_and_trigger_tables():
    sql = _migration_text("20260504_flowforge_integrations_intake.sql")

    assert "CREATE TABLE IF NOT EXISTS flowforge_integration_configs" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_integration_triggers" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_intake_events" in sql
    assert "UNIQUE KEY uidx_ff_webhook_public_id" in sql
    assert "UNIQUE KEY uidx_ff_intake_idempotency" in sql
    assert "raw_payload_expires_at DATETIME NULL" in sql
    assert "mode VARCHAR(16) NOT NULL DEFAULT 'production'" in sql


def test_flowforge_resource_migration_defines_vertical_neutral_snapshot_columns():
    sql = _migration_text("20260504_flowforge_resource_sets.sql")

    assert "CREATE TABLE IF NOT EXISTS flowforge_resource_sets" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_resource_snapshot_records" in sql
    assert "display_name VARCHAR(255) NULL" in sql
    assert "primary_email VARCHAR(255) NULL" in sql
    assert "capacity_available DECIMAL(12,2) NULL" in sql
    assert "normalized_profile_json JSON NOT NULL" in sql
    assert "sensitive_profile_json JSON NULL" in sql
    assert "source_missing TINYINT(1) NOT NULL DEFAULT 0" in sql
    assert "therapist" not in sql.lower()


def test_flowforge_matching_migration_defines_policy_and_evaluation_tables():
    sql = _migration_text("20260504_flowforge_matching.sql")

    assert "CREATE TABLE IF NOT EXISTS flowforge_matching_policies" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_matching_policy_versions" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_matching_policy_llm_drafts" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_matching_evaluations" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_matching_evaluation_candidates" in sql
    assert "policy_json JSON NOT NULL" in sql
    assert "score DECIMAL(12,4) NULL" in sql


def test_flowforge_runtime_migration_defines_idempotent_events_and_signed_tokens():
    sql = _migration_text("20260504_flowforge_runtime.sql")

    assert "CREATE TABLE IF NOT EXISTS flowforge_runs" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_run_events" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_human_tasks" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_signed_action_tokens" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_notifications" in sql
    assert "UNIQUE KEY uidx_ff_run_idempotency" in sql
    assert "UNIQUE KEY uidx_ff_signed_token_hash" in sql
    assert "UNIQUE KEY uidx_ff_notification_idempotency" in sql


def test_flowforge_runtime_hardening_migration_adds_task_idempotency_and_assignments():
    sql = _migration_text("20260505_flowforge_runtime_hardening.sql")

    assert "ALTER TABLE flowforge_human_tasks" in sql
    assert "ADD COLUMN idempotency_key VARCHAR(255) NULL" in sql
    assert "UNIQUE KEY uidx_ff_human_task_idempotency" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_assignments" in sql
    assert "UNIQUE KEY uidx_ff_assignment_idempotency" in sql


def test_flowforge_data_movement_migration_defines_phase_one_contract_tables():
    sql = _migration_text("20260506_flowforge_data_movement.sql")

    assert "CREATE TABLE IF NOT EXISTS flowforge_dataset_artifacts" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_data_movement_audit" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_data_sources" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_data_destinations" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_schedule_runs" in sql
    assert "UNIQUE KEY uidx_ff_dataset_artifact_key" in sql
    assert "UNIQUE KEY uidx_ff_data_source_key" in sql
    assert "UNIQUE KEY uidx_ff_data_destination_key" in sql
    assert "UNIQUE KEY uidx_ff_schedule_run_idempotency" in sql
    assert "trigger_node_id VARCHAR(128) NOT NULL" in sql
    assert "window_start DATETIME NOT NULL" in sql
    assert "window_end DATETIME NULL" in sql
    assert "config_json JSON NULL" in sql
    assert "trigger_payload_json JSON NULL" in sql


def test_flowforge_communication_template_migration_defines_template_contract():
    sql = _migration_text("20260506_flowforge_communication_templates.sql")

    assert "CREATE TABLE IF NOT EXISTS flowforge_communication_templates" in sql
    assert "template_key VARCHAR(128) NOT NULL" in sql
    assert "communication" not in sql.split("CREATE TABLE IF NOT EXISTS flowforge_communication_templates", 1)[0]
    assert "body_blocks_json JSON NOT NULL" in sql
    assert "validation_result_json JSON NOT NULL" in sql
    assert "UNIQUE KEY uidx_ff_comm_template_key" in sql
    assert "KEY idx_ff_comm_template_workspace_purpose" in sql


def test_flowforge_communication_template_ai_draft_migration_defines_audit_contract():
    sql = _migration_text("20260506_flowforge_communication_template_ai_drafts.sql")

    assert "CREATE TABLE IF NOT EXISTS flowforge_communication_template_ai_drafts" in sql
    assert "prompt TEXT NOT NULL" in sql
    assert "required_actions_json JSON NOT NULL" in sql
    assert "generated_body_blocks_json JSON NOT NULL" in sql
    assert "model_provider VARCHAR(64) NULL" in sql
    assert "KEY idx_ff_comm_template_ai_draft_purpose" in sql


def test_flowforge_workflow_jobs_governance_migration_defines_owner_run_as_and_acl_contract():
    sql = _migration_text("20260509_flowforge_workflow_jobs_governance.sql")

    assert "ALTER TABLE flowforge_workflow_definitions" in sql
    assert "ADD COLUMN owner_user_id VARCHAR(255) NULL" in sql
    assert "ADD COLUMN run_as_principal_type VARCHAR(32) NULL" in sql
    assert "ADD COLUMN run_as_principal_id VARCHAR(255) NULL" in sql
    assert "ADD COLUMN lifecycle VARCHAR(32) NOT NULL DEFAULT 'development'" in sql
    assert "CREATE TABLE IF NOT EXISTS flowforge_workflow_acl" in sql
    assert "UNIQUE KEY uidx_ff_workflow_acl_principal" in sql
    assert "permission VARCHAR(32) NOT NULL" in sql
    assert "INSERT INTO flowforge_workflow_acl" in sql
    assert "ALTER TABLE flowforge_runs" in sql
    assert "ADD COLUMN triggered_by_user_id VARCHAR(255) NULL" in sql
