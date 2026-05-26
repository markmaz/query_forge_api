from __future__ import annotations

from flask_restx import fields


def register_report_models(namespace):
    reporting_field = namespace.model(
        "FlowForgeReportingField",
        {
            "key": fields.String(required=True),
            "label": fields.String(required=True),
        },
    )
    reporting_filter = namespace.model(
        "FlowForgeReportingDefaultFilter",
        {
            "field": fields.String(required=True),
            "operator": fields.String(required=True),
            "value": fields.Raw(required=True),
        },
    )
    reporting_domain = namespace.model(
        "FlowForgeReportingDomain",
        {
            "workspace_id": fields.String(required=True),
            "domain_key": fields.String(required=True),
            "display_name": fields.String(required=True),
            "description": fields.String(required=True),
            "read_model": fields.String(required=True),
            "semantic_registered": fields.Boolean(required=True),
            "registration_status": fields.String(required=False),
            "registration_issues": fields.List(fields.String, required=False),
            "domain_group": fields.String(required=False),
            "domain_source": fields.String(required=False),
            "queryforge_visibility": fields.String(required=False),
            "workspace_scope_field": fields.String(required=False),
            "mode_field": fields.String(required=False),
            "time_fields": fields.List(fields.String, required=False),
            "identifiers": fields.List(fields.String, required=False),
            "queryforge_launch": fields.Raw(required=False),
            "default_filters": fields.List(fields.Nested(reporting_filter), required=True),
            "sensitive_excluded_fields": fields.List(fields.String, required=True),
            "query_studio_prompts": fields.List(fields.String, required=True),
            "metrics": fields.List(fields.Nested(reporting_field), required=True),
            "dimensions": fields.List(fields.Nested(reporting_field), required=True),
        },
    )
    reporting_domain_sync = namespace.model(
        "FlowForgeReportingDomainSync",
        {
            "workspace_id": fields.String(required=True),
            "dry_run": fields.Boolean(required=True),
            "status": fields.String(required=True),
            "domain_count": fields.Integer(required=True),
            "registered_count": fields.Integer(required=True),
            "domains": fields.List(fields.Raw, required=True),
        },
    )
    report_summary = namespace.model(
        "FlowForgeReportSummary",
        {
            "workspace_id": fields.String(required=True),
            "mode": fields.String(required=False),
            "default_filters": fields.List(fields.Nested(reporting_filter), required=True),
            "metrics": fields.Raw(required=True),
        },
    )
    report_dashboard = namespace.model(
        "FlowForgeReportDashboard",
        {
            "workspace_id": fields.String(required=True),
            "mode": fields.String(required=True),
            "default_filters": fields.List(fields.Nested(reporting_filter), required=True),
            "metrics": fields.Raw(required=True),
            "domains": fields.List(fields.Nested(reporting_domain), required=True),
        },
    )
    intake_review_event = namespace.model(
        "FlowForgeIntakeReviewEvent",
        {
            "intake_event_id": fields.Integer(required=True),
            "date": fields.String(required=True),
            "received_at": fields.Raw(required=False),
            "provider": fields.String(required=False),
            "external_submission_id": fields.String(required=False),
            "run_id": fields.Integer(required=False),
            "run_status": fields.String(required=False),
            "workflow_key": fields.String(required=False),
            "outcome": fields.String(required=True),
            "outcome_label": fields.String(required=True),
            "accepted_by": fields.String(required=False),
            "accepted_resource_set_id": fields.Integer(required=False),
            "accepted_source_record_key": fields.String(required=False),
            "no_match_reason": fields.String(required=False),
            "raw_payload_available": fields.Boolean(required=True),
        },
    )
    intake_review_bucket = namespace.model(
        "FlowForgeIntakeReviewBucket",
        {
            "date": fields.String(required=True),
            "intake_count": fields.Integer(required=True),
            "accepted_count": fields.Integer(required=True),
            "not_accepted_count": fields.Integer(required=True),
            "pending_count": fields.Integer(required=True),
            "events": fields.List(fields.Nested(intake_review_event), required=True),
        },
    )
    intake_review_timeline = namespace.model(
        "FlowForgeIntakeReviewTimeline",
        {
            "workspace_id": fields.String(required=True),
            "mode": fields.String(required=True),
            "days": fields.Integer(required=True),
            "buckets": fields.List(fields.Nested(intake_review_bucket), required=True),
        },
    )
    intake_raw_form = namespace.model(
        "FlowForgeIntakeRawForm",
        {
            "workspace_id": fields.String(required=True),
            "intake_event_id": fields.Integer(required=True),
            "provider": fields.String(required=False),
            "external_form_id": fields.String(required=False),
            "external_submission_id": fields.String(required=False),
            "mode": fields.String(required=False),
            "received_at": fields.Raw(required=False),
            "raw_payload_available": fields.Boolean(required=True),
            "raw_payload_redacted_at": fields.Raw(required=False),
            "raw_payload_redacted_by": fields.String(required=False),
            "raw_payload_expires_at": fields.Raw(required=False),
            "raw_payload": fields.Raw(required=True),
            "normalized_payload": fields.Raw(required=True),
        },
    )
    return {
        "reporting_domain": reporting_domain,
        "reporting_domain_sync": reporting_domain_sync,
        "report_summary": report_summary,
        "report_dashboard": report_dashboard,
        "intake_review_timeline": intake_review_timeline,
        "intake_raw_form": intake_raw_form,
    }
