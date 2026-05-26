from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.exceptions.forge_error import ForgeError
from app.features.flowforge.reporting import REPORTING_DOMAINS, FlowForgeSemanticSyncService


class FlowForgeReportServiceMixin:
    def list_reporting_domains(self, *, workspace_id: str) -> list[dict[str, Any]]:
        status_index = FlowForgeSemanticSyncService().domain_status_index(workspace_id=workspace_id)
        return [
            self._reporting_domain(
                workspace_id=workspace_id,
                domain=domain,
                registration=status_index.get(str(domain["domain_key"])),
            )
            for domain in REPORTING_DOMAINS
        ]

    def dry_run_reporting_domain_sync(self, *, workspace_id: str, actor_user_id: str | None = None) -> dict[str, Any]:
        return FlowForgeSemanticSyncService().sync_domains(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            dry_run=True,
        )

    def sync_reporting_domains(self, *, workspace_id: str, actor_user_id: str | None = None) -> dict[str, Any]:
        return FlowForgeSemanticSyncService().sync_domains(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            dry_run=False,
        )

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

    def get_intake_review_timeline(self, *, workspace_id: str, mode: str | None, days: int | None = 7) -> dict[str, Any]:
        normalized_mode = self._reporting_mode(mode)
        normalized_days = max(1, min(int(days or 7), 31))
        rows = self._runtime_repository.list_intake_review_events(
            workspace_id=workspace_id,
            mode=normalized_mode,
            days=normalized_days,
        )
        bucket_index = self._rolling_day_buckets(days=normalized_days)
        for row in rows:
            day = self._date_key(row.get("intake_date") or row.get("received_at"))
            if day not in bucket_index:
                continue
            event = self._intake_review_event(row)
            bucket = bucket_index[day]
            bucket["intake_count"] += 1
            if event["outcome"] == "accepted":
                bucket["accepted_count"] += 1
            elif event["outcome"] == "not_accepted":
                bucket["not_accepted_count"] += 1
            else:
                bucket["pending_count"] += 1
            bucket["events"].append(event)
        return {
            "workspace_id": workspace_id,
            "mode": normalized_mode,
            "days": normalized_days,
            "buckets": list(bucket_index.values()),
        }

    def get_intake_raw_form(self, *, workspace_id: str, intake_event_id: int) -> dict[str, Any]:
        raw_form = self._runtime_repository.get_intake_raw_form(
            workspace_id=workspace_id,
            intake_event_id=self._positive_int(intake_event_id, field_name="intake_event_id"),
        )
        if raw_form is None:
            raise ForgeError("FlowForge intake event not found.", status_code=404)
        return {
            "workspace_id": workspace_id,
            "intake_event_id": int(raw_form["intake_event_id"]),
            "provider": raw_form.get("provider"),
            "external_form_id": raw_form.get("external_form_id"),
            "external_submission_id": raw_form.get("external_submission_id"),
            "mode": raw_form.get("mode"),
            "received_at": raw_form.get("received_at"),
            "raw_payload_available": bool(raw_form.get("raw_payload_available")),
            "raw_payload_redacted_at": raw_form.get("raw_payload_redacted_at"),
            "raw_payload_redacted_by": raw_form.get("raw_payload_redacted_by"),
            "raw_payload_expires_at": raw_form.get("raw_payload_expires_at"),
            "raw_payload": raw_form.get("raw_payload_json") or {},
            "normalized_payload": raw_form.get("normalized_payload_json") or {},
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

    def _rolling_day_buckets(self, *, days: int) -> dict[str, dict[str, Any]]:
        today = date.today()
        start = today - timedelta(days=days - 1)
        buckets: dict[str, dict[str, Any]] = {}
        for offset in range(days):
            day = start + timedelta(days=offset)
            key = day.isoformat()
            buckets[key] = {
                "date": key,
                "intake_count": 0,
                "accepted_count": 0,
                "not_accepted_count": 0,
                "pending_count": 0,
                "events": [],
            }
        return buckets

    def _intake_review_event(self, row: dict[str, Any]) -> dict[str, Any]:
        assignment_id = row.get("assignment_id")
        no_match_reason = self._optional_string(row.get("no_match_reason"))
        accepted_by = self._optional_string(row.get("accepted_resource_display_name")) or self._optional_string(
            row.get("accepted_source_record_key")
        )
        if assignment_id is not None:
            outcome = "accepted"
            outcome_label = f"Accepted by {accepted_by}" if accepted_by else "Accepted"
        elif no_match_reason:
            outcome = "not_accepted"
            outcome_label = f"Not accepted: {no_match_reason}"
        else:
            outcome = "pending"
            outcome_label = "Pending acceptance"
        return {
            "intake_event_id": int(row["intake_event_id"]),
            "date": self._date_key(row.get("intake_date") or row.get("received_at")),
            "received_at": row.get("received_at"),
            "provider": row.get("provider"),
            "external_submission_id": row.get("external_submission_id"),
            "run_id": int(row["run_id"]) if row.get("run_id") is not None else None,
            "run_status": row.get("run_status"),
            "workflow_key": row.get("workflow_key"),
            "outcome": outcome,
            "outcome_label": outcome_label,
            "accepted_by": accepted_by,
            "accepted_resource_set_id": int(row["accepted_resource_set_id"]) if row.get("accepted_resource_set_id") is not None else None,
            "accepted_source_record_key": row.get("accepted_source_record_key"),
            "no_match_reason": no_match_reason,
            "raw_payload_available": row.get("raw_payload_redacted_at") is None,
        }

    def _date_key(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        text = str(value or "").strip()
        return text[:10]

    def _reporting_domain(
        self,
        *,
        workspace_id: str,
        domain: dict[str, Any],
        registration: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        registration_status = str((registration or {}).get("registration_status") or "registered")
        registration_issues = list((registration or {}).get("registration_issues") or [])
        return {
            "workspace_id": workspace_id,
            "domain_key": domain["domain_key"],
            "display_name": domain["display_name"],
            "description": domain["description"],
            "read_model": domain["read_model"],
            "semantic_registered": registration_status in {"validated", "registered"} and not registration_issues,
            "registration_status": registration_status,
            "registration_issues": registration_issues,
            "domain_group": domain["domain_group"],
            "domain_source": domain["domain_source"],
            "queryforge_visibility": domain["queryforge_visibility"],
            "workspace_scope_field": domain["workspace_scope_field"],
            "mode_field": domain["mode_field"],
            "time_fields": list(domain["time_fields"]),
            "identifiers": list(domain["identifiers"]),
            "queryforge_launch": dict((registration or {}).get("queryforge_launch") or {}),
            "default_filters": list(domain["default_filters"]),
            "sensitive_excluded_fields": list(domain["sensitive_excluded_fields"]),
            "query_studio_prompts": list(domain["query_studio_prompts"]),
            "metrics": list(domain["metrics"]),
            "dimensions": list(domain["dimensions"]),
        }
