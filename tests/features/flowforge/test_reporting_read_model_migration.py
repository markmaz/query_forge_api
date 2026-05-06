from __future__ import annotations

from pathlib import Path


MIGRATION_PATH = Path("migrations/20260505_flowforge_reporting_read_models.sql")
DATA_MOVEMENT_MIGRATION_PATH = Path("migrations/20260506_flowforge_data_movement_reporting_read_models.sql")


def test_flowforge_reporting_read_model_views_exclude_sensitive_fields():
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    for view_name in [
        "v_flowforge_report_workflow_runs",
        "v_flowforge_report_intake_events",
        "v_flowforge_report_matching_evaluations",
        "v_flowforge_report_resource_snapshots",
        "v_flowforge_report_offers_responses",
        "v_flowforge_report_assignments",
        "v_flowforge_report_notifications",
    ]:
        assert f"CREATE OR REPLACE VIEW {view_name}" in sql

    assert "raw_payload_json" not in sql
    assert "normalized_payload_json" not in sql
    assert "sensitive_fields_json" not in sql
    assert "sensitive_profile_json" not in sql
    assert "recipient" not in sql
    assert "payload_summary_json" not in sql
    assert "token_hash" not in sql


def test_flowforge_data_movement_reporting_read_model_views_exclude_payload_fields():
    sql = DATA_MOVEMENT_MIGRATION_PATH.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE VIEW v_flowforge_report_dataset_artifacts" in sql
    assert "CREATE OR REPLACE VIEW v_flowforge_report_data_movement_audit" in sql
    assert "flowforge_dataset_artifacts" in sql
    assert "flowforge_data_movement_audit" in sql
    assert "storage_ref_json" not in sql
    assert "schema_json" not in sql
    assert "checksum" not in sql
    assert "request_json" not in sql
    assert "result_json" not in sql
    assert "idempotency_key" not in sql
