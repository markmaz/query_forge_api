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
            "default_filters": fields.List(fields.Nested(reporting_filter), required=True),
            "sensitive_excluded_fields": fields.List(fields.String, required=True),
            "query_studio_prompts": fields.List(fields.String, required=True),
            "metrics": fields.List(fields.Nested(reporting_field), required=True),
            "dimensions": fields.List(fields.Nested(reporting_field), required=True),
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
    return {
        "reporting_domain": reporting_domain,
        "report_summary": report_summary,
        "report_dashboard": report_dashboard,
    }
