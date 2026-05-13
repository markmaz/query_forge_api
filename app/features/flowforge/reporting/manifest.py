from __future__ import annotations

from typing import Any

DEFAULT_DOMAIN_GROUP = "workflow_intelligence"
DEFAULT_DOMAIN_SOURCE = "flowforge_system"
DEFAULT_QUERYFORGE_VISIBILITY = "enabled"


def _field(key: str, label: str) -> dict[str, str]:
    return {"key": key, "label": label}


def _production_filter(field: str = "run_mode") -> list[dict[str, Any]]:
    return [{"field": field, "operator": "equals", "value": "production"}]


def _domain(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain_group": DEFAULT_DOMAIN_GROUP,
        "domain_source": DEFAULT_DOMAIN_SOURCE,
        "queryforge_visibility": DEFAULT_QUERYFORGE_VISIBILITY,
        "workspace_scope_field": "workspace_id",
        **payload,
    }


REPORTING_DOMAINS: list[dict[str, Any]] = [
    _domain({
        "domain_key": "flowforge_workflow_runs",
        "display_name": "FlowForge Workflow Runs",
        "description": "Workspace-scoped workflow run status, mode, timing, ownership, run identity, and operational outcomes.",
        "read_model": "v_flowforge_report_workflow_runs",
        "mode_field": "mode",
        "time_fields": ["started_at", "completed_at", "failed_at", "created_at", "updated_at"],
        "identifiers": ["run_id", "workflow_definition_id", "workflow_version_id", "workflow_key", "intake_event_id"],
        "default_filters": _production_filter("mode"),
        "sensitive_excluded_fields": ["run_context_json", "idempotency_key"],
        "query_studio_prompts": [
            "How many times did Workflow Studio run today?",
            "How many Workflow Studio runs completed this week?",
            "Which production workflows need attention?",
            "Show average run duration by workflow.",
        ],
        "synonyms": [
            {
                "term": "workflow studio run",
                "means": [
                    "workflow run",
                    "workflow studio runs",
                    "flowforge run",
                    "automation run",
                    "ran today",
                ],
            },
            {"term": "run count", "means": ["how many times", "number of runs", "times workflow studio ran"]},
        ],
        "metrics": [
            _field("run_count", "Run Count"),
            _field("active_run_count", "Active Runs"),
            _field("completed_run_count", "Completed Runs"),
            _field("failed_run_count", "Failed Runs"),
            _field("needs_attention_count", "Needs Attention Runs"),
        ],
        "dimensions": [
            _field("mode", "Mode"),
            _field("status", "Run Status"),
            _field("workflow_definition_id", "Workflow Definition"),
            _field("workflow_key", "Workflow"),
            _field("workflow_lifecycle", "Workflow Lifecycle"),
            _field("run_as_principal_type", "Run-As Principal Type"),
            _field("workflow_version_id", "Workflow Version"),
        ],
    }),
    _domain({
        "domain_key": "flowforge_workflow_checkpoints",
        "display_name": "FlowForge Workflow Checkpoints",
        "description": "Structured workflow run checkpoints from the runtime event timeline without raw event payloads.",
        "read_model": "v_flowforge_report_workflow_checkpoints",
        "mode_field": "run_mode",
        "time_fields": ["created_at"],
        "identifiers": ["event_id", "run_id", "workflow_definition_id", "workflow_version_id", "node_id"],
        "default_filters": _production_filter(),
        "sensitive_excluded_fields": ["event_payload_json", "sensitive_payload_json", "run_context_json", "signed_action_tokens"],
        "query_studio_prompts": [
            "Which Workflow Studio checkpoints are slowest?",
            "Which workflow nodes fail most often?",
            "Where do production runs stop before assignment?",
        ],
        "metrics": [_field("checkpoint_count", "Checkpoint Count")],
        "dimensions": [
            _field("event_type", "Event Type"),
            _field("checkpoint_key", "Checkpoint"),
            _field("checkpoint_status", "Checkpoint Status"),
            _field("node_id", "Node"),
            _field("workflow_key", "Workflow"),
        ],
    }),
    _domain({
        "domain_key": "flowforge_intake_events",
        "display_name": "FlowForge Intake Events",
        "description": "Safe intake event metadata without raw payloads, normalized payloads, headers, or sensitive fields.",
        "read_model": "v_flowforge_report_intake_events",
        "mode_field": "mode",
        "time_fields": ["received_at", "created_at", "updated_at"],
        "identifiers": ["id", "integration_config_id", "external_form_id", "external_submission_id"],
        "default_filters": _production_filter("mode"),
        "sensitive_excluded_fields": [
            "headers_json",
            "raw_payload_json",
            "normalized_payload_json",
            "sensitive_fields_json",
            "source_ip",
        ],
        "query_studio_prompts": [
            "How many intakes were received by provider?",
            "Show intake events that produced no workflow run.",
        ],
        "synonyms": [
            {"term": "intake subject", "means": ["patient", "client", "referral", "applicant"]},
            {"term": "intake form", "means": ["patient intake", "client intake", "referral form", "submission"]},
        ],
        "metrics": [_field("intake_event_count", "Intake Event Count")],
        "dimensions": [_field("provider", "Provider"), _field("mode", "Mode"), _field("status", "Status")],
    }),
    _domain({
        "domain_key": "flowforge_matching_evaluations",
        "display_name": "FlowForge Matching Evaluations",
        "description": "Matching outcomes, selected resource keys, and no-match reasons without input context payloads.",
        "read_model": "v_flowforge_report_matching_evaluations",
        "mode_field": "run_mode",
        "time_fields": ["evaluated_at"],
        "identifiers": ["matching_evaluation_id", "run_id", "matching_policy_version_id", "resource_set_id"],
        "default_filters": _production_filter(),
        "sensitive_excluded_fields": ["input_context_json", "summary_json"],
        "query_studio_prompts": [
            "What are the top no-match reasons?",
            "How many matching evaluations selected a resource?",
        ],
        "synonyms": [
            {"term": "not accepted", "means": ["no match", "not matched", "unassigned", "declined"]},
            {"term": "intake subject", "means": ["patient", "client", "referral", "applicant"]},
        ],
        "metrics": [
            _field("matching_evaluation_count", "Matching Evaluation Count"),
            _field("no_match_outcome_count", "No-Match Outcomes"),
        ],
        "dimensions": [
            _field("status", "Evaluation Status"),
            _field("no_match_reason", "No-Match Reason"),
            _field("resource_set_id", "Resource Set"),
            _field("workflow_key", "Workflow"),
        ],
    }),
    _domain({
        "domain_key": "flowforge_matching_candidates",
        "display_name": "FlowForge Matching Candidates",
        "description": "Candidate-level matching outcomes, ranks, scores, and selected resource display names.",
        "read_model": "v_flowforge_report_matching_candidates",
        "mode_field": "run_mode",
        "time_fields": ["evaluated_at", "created_at"],
        "identifiers": ["candidate_id", "matching_evaluation_id", "run_id", "source_record_key"],
        "default_filters": _production_filter(),
        "sensitive_excluded_fields": ["eligibility_result_json", "score_breakdown_json", "explanation_json", "normalized_profile_json"],
        "query_studio_prompts": [
            "Which resources are most often selected by matching?",
            "Which matching candidates are frequently excluded?",
            "What are average matching scores by resource pool?",
        ],
        "metrics": [
            _field("matching_candidate_count", "Matching Candidate Count"),
            _field("selected_candidate_count", "Selected Candidates"),
        ],
        "dimensions": [
            _field("selected", "Selected"),
            _field("included", "Included"),
            _field("excluded", "Excluded"),
            _field("resource_set_id", "Resource Set"),
            _field("resource_display_name", "Resource"),
            _field("workflow_key", "Workflow"),
        ],
    }),
    _domain({
        "domain_key": "flowforge_resource_snapshots",
        "display_name": "FlowForge Resource Snapshots",
        "description": "Compiled resource snapshot availability, capacity, and status fields with contact/sensitive profiles excluded.",
        "read_model": "v_flowforge_report_resource_snapshots",
        "mode_field": "snapshot_mode",
        "time_fields": ["compiled_at", "source_updated_at"],
        "identifiers": ["resource_set_id", "snapshot_batch_id", "source_record_key"],
        "default_filters": [{"field": "snapshot_mode", "operator": "equals", "value": "production"}],
        "sensitive_excluded_fields": [
            "primary_email",
            "primary_phone",
            "normalized_profile_json",
            "sensitive_profile_json",
            "validation_errors_json",
        ],
        "query_studio_prompts": [
            "How many active resources are available?",
            "Show resource capacity by service area.",
        ],
        "metrics": [
            _field("resource_snapshot_record_count", "Resource Snapshot Records"),
            _field("available_resource_count", "Available Resources"),
        ],
        "dimensions": [
            _field("effective_status", "Effective Status"),
            _field("availability_status", "Availability Status"),
            _field("resource_set_id", "Resource Set"),
            _field("service_area", "Service Area"),
        ],
    }),
    _domain({
        "domain_key": "flowforge_offers_responses",
        "display_name": "FlowForge Offers and Responses",
        "description": "Human offer task status, due/completion timing, and resource references without signed-token data.",
        "read_model": "v_flowforge_report_offers_responses",
        "mode_field": "run_mode",
        "time_fields": ["due_at", "completed_at", "created_at", "updated_at"],
        "identifiers": ["id", "run_id", "resource_set_id", "source_record_key"],
        "default_filters": _production_filter(),
        "sensitive_excluded_fields": ["response_json", "idempotency_key", "signed_action_tokens"],
        "query_studio_prompts": [
            "What is the offer acceptance rate?",
            "Which offers are still pending?",
        ],
        "synonyms": [
            {"term": "accepted", "means": ["accepted the patient", "accepted the client", "approved offer"]},
            {"term": "not accepted", "means": ["declined", "timed out", "not accepted the patient", "not accepted the client"]},
        ],
        "metrics": [
            _field("offer_count", "Offer Count"),
            _field("pending_offer_count", "Pending Offers"),
            _field("completed_offer_count", "Completed Offers"),
        ],
        "dimensions": [_field("status", "Offer Status"), _field("resource_set_id", "Resource Set")],
    }),
    _domain({
        "domain_key": "flowforge_offer_outcomes",
        "display_name": "FlowForge Offer Outcomes",
        "description": "Therapist/resource offer response outcomes, response timing, and assignment linkage without contact details.",
        "read_model": "v_flowforge_report_offer_outcomes",
        "mode_field": "run_mode",
        "time_fields": ["offered_at", "due_at", "completed_at", "assigned_at"],
        "identifiers": ["human_task_id", "run_id", "resource_set_id", "source_record_key", "assignment_id"],
        "default_filters": _production_filter(),
        "sensitive_excluded_fields": ["response_json", "idempotency_key", "signed_action_tokens", "primary_email", "primary_phone"],
        "query_studio_prompts": [
            "Which therapists decline most often?",
            "What is the offer acceptance rate by resource pool?",
            "How long do therapists take to respond?",
        ],
        "synonyms": [
            {"term": "accepted", "means": ["accepted the patient", "accepted the client", "approved offer"]},
            {"term": "not accepted", "means": ["declined", "rejected", "timed out", "not accepted the patient", "not accepted the client"]},
        ],
        "metrics": [
            _field("offer_count", "Offer Count"),
            _field("accepted_offer_count", "Accepted Offers"),
            _field("declined_offer_count", "Declined Offers"),
            _field("timed_out_offer_count", "Timed-Out Offers"),
        ],
        "dimensions": [
            _field("outcome", "Outcome"),
            _field("offer_status", "Offer Status"),
            _field("resource_display_name", "Resource"),
            _field("resource_set_id", "Resource Set"),
            _field("workflow_key", "Workflow"),
        ],
    }),
    _domain({
        "domain_key": "flowforge_assignments",
        "display_name": "FlowForge Assignments",
        "description": "Assignment outcomes and resource references created by Workflow Studio.",
        "read_model": "v_flowforge_report_assignments",
        "mode_field": "run_mode",
        "time_fields": ["assigned_at", "released_at"],
        "identifiers": ["id", "run_id", "human_task_id", "resource_set_id", "source_record_key"],
        "default_filters": _production_filter(),
        "sensitive_excluded_fields": ["assignment_json", "idempotency_key"],
        "query_studio_prompts": [
            "How many assignments were created this month?",
            "Show assignments by resource set and status.",
        ],
        "synonyms": [
            {"term": "assigned subject", "means": ["accepted patient", "accepted client", "assigned patient", "assigned client"]},
        ],
        "metrics": [_field("assignment_count", "Assignment Count")],
        "dimensions": [_field("status", "Assignment Status"), _field("resource_set_id", "Resource Set")],
    }),
    _domain({
        "domain_key": "flowforge_assignment_funnel",
        "display_name": "FlowForge Assignment Funnel",
        "description": "Run-level funnel timing from intake through matching, first offer, response, and assignment.",
        "read_model": "v_flowforge_report_assignment_funnel",
        "mode_field": "run_mode",
        "time_fields": ["intake_received_at", "matching_evaluated_at", "first_offer_created_at", "first_response_at", "assigned_at"],
        "identifiers": ["run_id", "workflow_definition_id", "workflow_version_id"],
        "default_filters": _production_filter(),
        "sensitive_excluded_fields": ["run_context_json", "input_context_json", "response_json"],
        "query_studio_prompts": [
            "What percentage of intakes become assignments?",
            "How long does assignment take by workflow?",
            "How many offers are needed before assignment?",
        ],
        "synonyms": [
            {"term": "intake subject", "means": ["patient", "client", "referral", "applicant"]},
            {"term": "not accepted", "means": ["no match", "not matched", "not assigned", "not accepted"]},
            {"term": "accepted", "means": ["assigned", "accepted patient", "accepted client"]},
        ],
        "metrics": [
            _field("assignment_funnel_count", "Assignment Funnel Runs"),
            _field("assigned_run_count", "Assigned Runs"),
            _field("no_match_run_count", "No-Match Runs"),
        ],
        "dimensions": [
            _field("funnel_status", "Funnel Status"),
            _field("workflow_key", "Workflow"),
            _field("no_match_reason", "No-Match Reason"),
        ],
    }),
    _domain({
        "domain_key": "flowforge_notifications",
        "display_name": "FlowForge Notifications",
        "description": "Notification delivery status and template usage with recipient addresses and payload details excluded.",
        "read_model": "v_flowforge_report_notifications",
        "mode_field": "run_mode",
        "time_fields": ["created_at", "sent_at", "failed_at"],
        "identifiers": ["id", "run_id", "human_task_id", "template_key"],
        "default_filters": _production_filter(),
        "sensitive_excluded_fields": ["recipient", "payload_summary_json", "provider_message_id", "error_message"],
        "query_studio_prompts": [
            "How many Workflow Studio notifications failed?",
            "Show notifications by template and status.",
        ],
        "metrics": [
            _field("notification_count", "Notification Count"),
            _field("pending_notification_count", "Pending Notifications"),
            _field("failed_notification_count", "Failed Notifications"),
        ],
        "dimensions": [
            _field("channel", "Channel"),
            _field("template_key", "Template"),
            _field("status", "Status"),
            _field("workflow_key", "Workflow"),
        ],
    }),
    _domain({
        "domain_key": "flowforge_dataset_artifacts",
        "display_name": "FlowForge Dataset Artifacts",
        "description": "Dataset artifact lifecycle, volume, storage kind, expiry, and run linkage for import/export operations.",
        "read_model": "v_flowforge_report_dataset_artifacts",
        "mode_field": "run_mode",
        "time_fields": ["expires_at", "created_at", "updated_at"],
        "identifiers": ["id", "run_id", "artifact_key"],
        "default_filters": _production_filter(),
        "sensitive_excluded_fields": ["storage_ref_json", "schema_json", "checksum"],
        "query_studio_prompts": [
            "Which Workflow Studio dataset artifacts are past retention?",
            "Show data movement artifact counts by status and storage kind.",
            "How many rows were exported by Workflow Studio this week?",
        ],
        "metrics": [
            _field("dataset_artifact_count", "Dataset Artifacts"),
            _field("expired_dataset_artifact_count", "Expired Dataset Artifacts"),
            _field("retention_pending_artifact_count", "Past-Retention Artifacts"),
        ],
        "dimensions": [
            _field("artifact_type", "Artifact Type"),
            _field("storage_kind", "Storage Kind"),
            _field("status", "Artifact Status"),
            _field("retention_state", "Retention State"),
        ],
    }),
    _domain({
        "domain_key": "flowforge_data_movement_audit",
        "display_name": "FlowForge Data Movement Audit",
        "description": "Operational import/export audit rows with action status, source/destination references, and timing.",
        "read_model": "v_flowforge_report_data_movement_audit",
        "mode_field": "run_mode",
        "time_fields": ["started_at", "completed_at", "created_at"],
        "identifiers": ["id", "run_id", "dataset_artifact_id"],
        "default_filters": _production_filter(),
        "sensitive_excluded_fields": ["request_json", "result_json", "idempotency_key"],
        "query_studio_prompts": [
            "Which Workflow Studio imports failed in the last day?",
            "Which Workflow Studio exports failed in the last day?",
            "Show import and export counts by source and destination.",
        ],
        "metrics": [
            _field("data_movement_audit_count", "Data Movement Audit Rows"),
            _field("failed_import_count", "Failed Imports"),
            _field("failed_export_count", "Failed Exports"),
        ],
        "dimensions": [
            _field("action_type", "Action Type"),
            _field("status", "Action Status"),
            _field("source_key", "Source"),
            _field("destination_key", "Destination"),
            _field("workflow_key", "Workflow"),
        ],
    }),
]


def expected_read_models() -> set[str]:
    return {str(domain["read_model"]) for domain in REPORTING_DOMAINS}


def validate_reporting_manifest(domains: list[dict[str, Any]] | None = None) -> list[str]:
    errors: list[str] = []
    seen_keys: set[str] = set()
    seen_models: set[str] = set()
    for index, domain in enumerate(domains or REPORTING_DOMAINS):
        prefix = str(domain.get("domain_key") or f"domain[{index}]")
        domain_key = str(domain.get("domain_key") or "").strip()
        read_model = str(domain.get("read_model") or "").strip()
        if not domain_key:
            errors.append(f"{prefix}: domain_key is required")
        elif domain_key in seen_keys:
            errors.append(f"{prefix}: duplicate domain_key")
        seen_keys.add(domain_key)
        if not read_model:
            errors.append(f"{prefix}: read_model is required")
        elif read_model in seen_models:
            errors.append(f"{prefix}: duplicate read_model")
        seen_models.add(read_model)
        for field_name in (
            "display_name",
            "description",
            "workspace_scope_field",
            "mode_field",
            "domain_source",
            "domain_group",
            "queryforge_visibility",
        ):
            if not str(domain.get(field_name) or "").strip():
                errors.append(f"{prefix}: {field_name} is required")
        for list_name in (
            "metrics",
            "dimensions",
            "sensitive_excluded_fields",
            "query_studio_prompts",
            "default_filters",
            "time_fields",
            "identifiers",
        ):
            if not isinstance(domain.get(list_name), list) or not domain.get(list_name):
                errors.append(f"{prefix}: {list_name} must be a non-empty list")
        for field in list(domain.get("metrics") or []) + list(domain.get("dimensions") or []):
            if not isinstance(field, dict) or not field.get("key") or not field.get("label"):
                errors.append(f"{prefix}: metric/dimension entries require key and label")
    return errors
