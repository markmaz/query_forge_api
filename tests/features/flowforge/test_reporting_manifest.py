from __future__ import annotations

from pathlib import Path

from app.features.flowforge.reporting import REPORTING_DOMAINS, expected_read_models, validate_reporting_manifest
from app.features.flowforge.reporting.read_model_audit import audit_reporting_read_model_sql


REPORTING_MIGRATION_SQL = "\n".join(
    [
        Path("migrations/20260505_flowforge_reporting_read_models.sql").read_text(encoding="utf-8"),
        Path("migrations/20260506_flowforge_data_movement_reporting_read_models.sql").read_text(encoding="utf-8"),
        Path("migrations/20260510_flowforge_workflow_intelligence_read_models.sql").read_text(encoding="utf-8"),
    ]
)


def test_flowforge_reporting_manifest_is_valid():
    assert validate_reporting_manifest() == []


def test_flowforge_reporting_manifest_domains_have_required_contract_fields():
    assert REPORTING_DOMAINS

    for domain in REPORTING_DOMAINS:
        assert domain["domain_key"].startswith("flowforge_")
        assert domain["read_model"].startswith("v_flowforge_report_")
        assert domain["domain_source"] == "flowforge_system"
        assert domain["domain_group"] == "workflow_intelligence"
        assert domain["queryforge_visibility"] == "enabled"
        assert domain["workspace_scope_field"] == "workspace_id"
        assert domain["metrics"]
        assert domain["dimensions"]
        assert domain["sensitive_excluded_fields"]
        assert domain["query_studio_prompts"]
        assert domain["default_filters"]
        assert domain["time_fields"]
        assert domain["identifiers"]


def test_flowforge_reporting_manifest_carries_subject_language_as_semantic_synonyms():
    intake = next(domain for domain in REPORTING_DOMAINS if domain["domain_key"] == "flowforge_intake_events")
    funnel = next(domain for domain in REPORTING_DOMAINS if domain["domain_key"] == "flowforge_assignment_funnel")

    intake_terms = {
        str(value)
        for synonym in intake["synonyms"]
        for value in [synonym["term"], *synonym["means"]]
    }
    funnel_terms = {
        str(value)
        for synonym in funnel["synonyms"]
        for value in [synonym["term"], *synonym["means"]]
    }

    assert {"patient", "client", "referral", "applicant"}.issubset(intake_terms)
    assert {"not accepted", "accepted patient", "accepted client"}.issubset(funnel_terms)


def test_flowforge_reporting_manifest_validation_rejects_missing_metric_dimension_fields():
    invalid_domain = {
        **REPORTING_DOMAINS[0],
        "metrics": [{"key": "run_count"}],
        "dimensions": [{"label": "Status"}],
    }

    errors = validate_reporting_manifest([invalid_domain])

    assert errors == [
        "flowforge_workflow_runs: metric/dimension entries require key and label",
        "flowforge_workflow_runs: metric/dimension entries require key and label",
    ]


def test_flowforge_reporting_manifest_read_models_match_migrations():
    assert expected_read_models() == {
        "v_flowforge_report_workflow_runs",
        "v_flowforge_report_workflow_checkpoints",
        "v_flowforge_report_intake_events",
        "v_flowforge_report_matching_evaluations",
        "v_flowforge_report_matching_candidates",
        "v_flowforge_report_resource_snapshots",
        "v_flowforge_report_offer_outcomes",
        "v_flowforge_report_offers_responses",
        "v_flowforge_report_assignments",
        "v_flowforge_report_assignment_funnel",
        "v_flowforge_report_notifications",
        "v_flowforge_report_dataset_artifacts",
        "v_flowforge_report_data_movement_audit",
    }
    assert audit_reporting_read_model_sql(REPORTING_MIGRATION_SQL) == []


def test_flowforge_reporting_read_model_audit_rejects_missing_views_and_sensitive_columns():
    sql = """
    CREATE OR REPLACE VIEW v_flowforge_report_workflow_runs AS
    SELECT
      id,
      workspace_id,
      workflow_definition_id,
      workflow_version_id,
      intake_event_id,
      mode,
      status,
      started_at,
      completed_at,
      failed_at,
      created_at,
      updated_at,
      run_context_json
    FROM flowforge_runs;
    """

    intake_domain = next(domain for domain in REPORTING_DOMAINS if domain["domain_key"] == "flowforge_intake_events")
    errors = audit_reporting_read_model_sql(sql, domains=[REPORTING_DOMAINS[0], intake_domain])

    assert "flowforge_workflow_runs: sensitive field run_context_json is exposed by v_flowforge_report_workflow_runs" in errors
    assert (
        "flowforge_intake_events: read model v_flowforge_report_intake_events is missing from migration SQL"
        in errors
    )
