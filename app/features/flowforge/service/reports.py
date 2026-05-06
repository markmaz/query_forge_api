from __future__ import annotations

from typing import Any


_REPORTING_DOMAINS: list[dict[str, Any]] = [
    {
        "domain_key": "flowforge_workflow_runs",
        "display_name": "FlowForge Workflow Runs",
        "description": "Workspace-scoped workflow run status, mode, timing, and operational outcome metrics.",
        "read_model": "v_flowforge_report_workflow_runs",
        "default_filters": [{"field": "mode", "operator": "equals", "value": "production"}],
        "sensitive_excluded_fields": ["run_context_json", "idempotency_key"],
        "query_studio_prompts": [
            "How many FlowForge runs completed this week?",
            "Which FlowForge runs need attention?",
            "Show run counts by workflow and status.",
        ],
        "metrics": [
            {"key": "run_count", "label": "Run Count"},
            {"key": "active_run_count", "label": "Active Runs"},
            {"key": "completed_run_count", "label": "Completed Runs"},
            {"key": "failed_run_count", "label": "Failed Runs"},
            {"key": "needs_attention_count", "label": "Needs Attention Runs"},
        ],
        "dimensions": [
            {"key": "mode", "label": "Mode"},
            {"key": "status", "label": "Run Status"},
            {"key": "workflow_definition_id", "label": "Workflow Definition"},
            {"key": "workflow_version_id", "label": "Workflow Version"},
        ],
    },
    {
        "domain_key": "flowforge_intake_events",
        "display_name": "FlowForge Intake Events",
        "description": "Safe intake event metadata without raw payloads, normalized payloads, headers, or sensitive fields.",
        "read_model": "v_flowforge_report_intake_events",
        "default_filters": [{"field": "mode", "operator": "equals", "value": "production"}],
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
        "metrics": [{"key": "intake_event_count", "label": "Intake Event Count"}],
        "dimensions": [
            {"key": "provider", "label": "Provider"},
            {"key": "mode", "label": "Mode"},
            {"key": "status", "label": "Status"},
        ],
    },
    {
        "domain_key": "flowforge_matching_evaluations",
        "display_name": "FlowForge Matching Evaluations",
        "description": "Matching outcomes, selected resource keys, and no-match reasons without input context payloads.",
        "read_model": "v_flowforge_report_matching_evaluations",
        "default_filters": [{"field": "run_mode", "operator": "equals", "value": "production"}],
        "sensitive_excluded_fields": ["input_context_json", "summary_json"],
        "query_studio_prompts": [
            "What are the top no-match reasons?",
            "How many matching evaluations selected a resource?",
        ],
        "metrics": [
            {"key": "matching_evaluation_count", "label": "Matching Evaluation Count"},
            {"key": "no_match_outcome_count", "label": "No-Match Outcomes"},
        ],
        "dimensions": [
            {"key": "status", "label": "Evaluation Status"},
            {"key": "no_match_reason", "label": "No-Match Reason"},
            {"key": "resource_set_id", "label": "Resource Set"},
        ],
    },
    {
        "domain_key": "flowforge_resource_snapshots",
        "display_name": "FlowForge Resource Snapshots",
        "description": "Compiled resource snapshot availability, capacity, and status fields with contact/sensitive profiles excluded.",
        "read_model": "v_flowforge_report_resource_snapshots",
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
            {"key": "resource_snapshot_record_count", "label": "Resource Snapshot Records"},
            {"key": "available_resource_count", "label": "Available Resources"},
        ],
        "dimensions": [
            {"key": "effective_status", "label": "Effective Status"},
            {"key": "availability_status", "label": "Availability Status"},
            {"key": "resource_set_id", "label": "Resource Set"},
        ],
    },
    {
        "domain_key": "flowforge_offers_responses",
        "display_name": "FlowForge Offers and Responses",
        "description": "Human offer task status, due/completion timing, and resource references without signed-token data.",
        "read_model": "v_flowforge_report_offers_responses",
        "default_filters": [{"field": "run_mode", "operator": "equals", "value": "production"}],
        "sensitive_excluded_fields": ["response_json", "idempotency_key", "signed_action_tokens"],
        "query_studio_prompts": [
            "What is the offer acceptance rate?",
            "Which offers are still pending?",
        ],
        "metrics": [
            {"key": "offer_count", "label": "Offer Count"},
            {"key": "pending_offer_count", "label": "Pending Offers"},
            {"key": "completed_offer_count", "label": "Completed Offers"},
        ],
        "dimensions": [
            {"key": "status", "label": "Offer Status"},
            {"key": "resource_set_id", "label": "Resource Set"},
        ],
    },
    {
        "domain_key": "flowforge_assignments",
        "display_name": "FlowForge Assignments",
        "description": "Assignment outcomes and resource references created by FlowForge workflows.",
        "read_model": "v_flowforge_report_assignments",
        "default_filters": [{"field": "run_mode", "operator": "equals", "value": "production"}],
        "sensitive_excluded_fields": ["assignment_json", "idempotency_key"],
        "query_studio_prompts": [
            "How many assignments were created this month?",
            "Show assignments by resource set and status.",
        ],
        "metrics": [{"key": "assignment_count", "label": "Assignment Count"}],
        "dimensions": [
            {"key": "status", "label": "Assignment Status"},
            {"key": "resource_set_id", "label": "Resource Set"},
        ],
    },
    {
        "domain_key": "flowforge_notifications",
        "display_name": "FlowForge Notifications",
        "description": "Notification delivery status and template usage with recipient addresses and payload details excluded.",
        "read_model": "v_flowforge_report_notifications",
        "default_filters": [{"field": "run_mode", "operator": "equals", "value": "production"}],
        "sensitive_excluded_fields": ["recipient", "payload_summary_json", "provider_message_id", "error_message"],
        "query_studio_prompts": [
            "How many FlowForge notifications failed?",
            "Show notifications by template and status.",
        ],
        "metrics": [
            {"key": "notification_count", "label": "Notification Count"},
            {"key": "pending_notification_count", "label": "Pending Notifications"},
            {"key": "failed_notification_count", "label": "Failed Notifications"},
        ],
        "dimensions": [
            {"key": "channel", "label": "Channel"},
            {"key": "template_key", "label": "Template"},
            {"key": "status", "label": "Status"},
        ],
    },
]


class FlowForgeReportServiceMixin:
    def list_reporting_domains(self, *, workspace_id: str) -> list[dict[str, Any]]:
        return [self._reporting_domain(workspace_id=workspace_id, domain=domain) for domain in _REPORTING_DOMAINS]

    def get_report_summary(self, *, workspace_id: str, mode: str | None) -> dict[str, Any]:
        normalized_mode = self._reporting_mode(mode)
        summary = self._runtime_repository.get_report_summary(workspace_id=workspace_id, mode=normalized_mode)
        return {
            "workspace_id": workspace_id,
            "mode": normalized_mode,
            "default_filters": [{"field": "mode", "operator": "equals", "value": normalized_mode}],
            "metrics": {
                "run_count": int(summary.get("run_count") or 0),
                "active_run_count": int(summary.get("active_run_count") or 0),
                "completed_run_count": int(summary.get("completed_run_count") or 0),
                "failed_run_count": int(summary.get("failed_run_count") or 0),
                "needs_attention_count": int(summary.get("needs_attention_count") or 0),
                "test_run_count": int(summary.get("test_run_count") or 0),
                "production_run_count": int(summary.get("production_run_count") or 0),
            },
        }

    def get_report_dashboard(self, *, workspace_id: str, mode: str | None) -> dict[str, Any]:
        normalized_mode = self._reporting_mode(mode)
        metrics = self._runtime_repository.get_reporting_dashboard_metrics(
            workspace_id=workspace_id,
            mode=normalized_mode,
        )
        safe_metrics = {key: self._metric_int(value) for key, value in metrics.items() if key not in {"workspace_id", "mode"}}
        return {
            "workspace_id": workspace_id,
            "mode": normalized_mode,
            "default_filters": [{"field": "mode", "operator": "equals", "value": normalized_mode}],
            "metrics": safe_metrics,
            "domains": self.list_reporting_domains(workspace_id=workspace_id),
        }

    def _reporting_mode(self, mode: str | None) -> str:
        normalized = self._optional_string(mode) or "production"
        if normalized not in {"production", "test"}:
            normalized = "production"
        return normalized

    def _metric_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _reporting_domain(self, *, workspace_id: str, domain: dict[str, Any]) -> dict[str, Any]:
        return {
            "workspace_id": workspace_id,
            "domain_key": domain["domain_key"],
            "display_name": domain["display_name"],
            "description": domain["description"],
            "read_model": domain["read_model"],
            "semantic_registered": True,
            "default_filters": list(domain["default_filters"]),
            "sensitive_excluded_fields": list(domain["sensitive_excluded_fields"]),
            "query_studio_prompts": list(domain["query_studio_prompts"]),
            "metrics": list(domain["metrics"]),
            "dimensions": list(domain["dimensions"]),
        }
