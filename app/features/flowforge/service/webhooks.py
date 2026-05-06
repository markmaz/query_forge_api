from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.exceptions.forge_error import ForgeError


class FlowForgeWebhookServiceMixin:
    def accept_jotform_integration_webhook(
        self,
        *,
        webhook_public_id: str,
        payload: dict[str, Any],
        token: str,
        source_ip: str | None = None,
        headers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        public_id = str(webhook_public_id or "").strip()
        integration = self._integration_repository.get_integration_config_by_public_id(webhook_public_id=public_id)
        if integration is None or str(integration.get("provider") or "").strip() != "jotform":
            raise ForgeError("Jotform integration was not found.", status_code=404)
        if not bool(integration.get("enabled")):
            raise ForgeError("Jotform integration is disabled.", status_code=403)
        self._assert_integration_webhook_secret(
            provided_token=token,
            expected_hash=str(integration.get("secret_hash") or "").strip(),
        )

        workspace_id = str(integration.get("workspace_id") or "").strip()
        normalized = self._normalize_jotform_payload(payload)
        idempotency_key = self._jotform_idempotency_key(
            webhook_public_id=public_id,
            normalized_payload=normalized,
            raw_payload=payload,
        )
        existing = self._integration_repository.get_intake_event_by_idempotency(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return self._serialize_persisted_jotform_webhook_response(
                integration=integration,
                intake_event_id=int(existing.get("id") or 0),
                normalized_payload=existing.get("normalized_payload_json") or normalized,
                trigger_evaluation=existing.get("trigger_evaluation_json") or {},
                workflow_runs=None,
                duplicate=True,
            )

        received_at = datetime.now(timezone.utc)
        raw_payload_expires_at = received_at + timedelta(days=self._raw_payload_retention_days(workspace_id=workspace_id))
        trigger_evaluation = self._evaluate_integration_triggers(
            workspace_id=workspace_id,
            integration_config_id=int(integration["id"]),
            normalized_payload=normalized,
        )
        intake_event_id = self._integration_repository.create_intake_event(
            workspace_id=workspace_id,
            integration_config_id=int(integration["id"]),
            provider="jotform",
            external_form_id=self._optional_string(normalized.get("form_id") or integration.get("external_form_id")),
            external_submission_id=self._optional_string(normalized.get("submission_id")),
            mode=str(integration.get("mode") or "production"),
            idempotency_key=idempotency_key,
            normalized_payload=normalized,
            raw_payload=payload,
            received_at=received_at,
            raw_payload_expires_at=raw_payload_expires_at,
            trigger_evaluation=trigger_evaluation,
            source_ip=source_ip,
            headers=headers or {},
        )
        workflow_runs = self._create_initial_runs_from_trigger_evaluation(
            workspace_id=workspace_id,
            integration=integration,
            intake_event_id=int(intake_event_id),
            normalized_payload=normalized,
            trigger_evaluation=trigger_evaluation,
        )
        trigger_evaluation = {
            **trigger_evaluation,
            "workflow_run_creation": "created" if workflow_runs else "none",
            "created_run_count": len(workflow_runs),
            "workflow_runs": workflow_runs,
        }
        self._integration_repository.update_intake_event_trigger_evaluation(
            workspace_id=workspace_id,
            intake_event_id=int(intake_event_id),
            trigger_evaluation=trigger_evaluation,
        )
        return self._serialize_persisted_jotform_webhook_response(
            integration=integration,
            intake_event_id=int(intake_event_id),
            normalized_payload=normalized,
            trigger_evaluation=trigger_evaluation,
            workflow_runs=workflow_runs,
            duplicate=False,
        )

    def _assert_integration_webhook_secret(self, *, provided_token: str, expected_hash: str) -> None:
        if not expected_hash:
            raise ForgeError("Jotform integration secret is not configured.", status_code=503)
        provided_hash = self._hash_webhook_secret(provided_token)
        if not provided_token or not secrets.compare_digest(provided_hash, expected_hash):
            raise ForgeError("Invalid Jotform webhook token.", status_code=401)

    def _normalize_jotform_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_request = payload.get("rawRequest")
        raw_submission: dict[str, Any] = {}
        if isinstance(raw_request, str) and raw_request.strip():
            try:
                parsed = json.loads(raw_request)
                if isinstance(parsed, dict):
                    raw_submission = parsed
            except json.JSONDecodeError:
                raw_submission = {}
        elif isinstance(raw_request, dict):
            raw_submission = raw_request

        merged = {**payload, **raw_submission}
        fields = {
            key: value
            for key, value in merged.items()
            if key
            not in {
                "rawRequest",
                "submissionID",
                "submission_id",
                "id",
                "formID",
                "form_id",
                "ip",
                "created_at",
            }
        }
        return {
            "provider": "jotform",
            "submission_id": self._first_string(
                merged.get("submissionID"),
                merged.get("submission_id"),
                merged.get("id"),
            ),
            "form_id": self._first_string(merged.get("formID"), merged.get("form_id")),
            "submitter_ip": self._first_string(merged.get("ip")),
            "submitted_at": self._first_string(merged.get("created_at")),
            "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "fields": fields,
            "raw": raw_submission or payload,
        }

    def _first_string(self, *values: Any) -> str | None:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return None

    def _jotform_idempotency_key(
        self,
        *,
        webhook_public_id: str,
        normalized_payload: dict[str, Any],
        raw_payload: dict[str, Any],
    ) -> str:
        submission_id = self._optional_string(normalized_payload.get("submission_id"))
        if submission_id:
            return f"jotform:{webhook_public_id}:submission:{submission_id}"
        fingerprint = hashlib.sha256(
            json.dumps(raw_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        return f"jotform:{webhook_public_id}:payload:{fingerprint}"

    def _raw_payload_retention_days(self, *, workspace_id: str) -> int:
        settings = self._settings_repository.get_settings(workspace_id=workspace_id)
        retention_days = int(settings.get("raw_payload_retention_days") or 30)
        max_days = int(settings.get("raw_payload_retention_max_days") or 90)
        return max(1, min(retention_days, max_days))

    def _serialize_persisted_jotform_webhook_response(
        self,
        *,
        integration: dict[str, Any],
        intake_event_id: int,
        normalized_payload: dict[str, Any],
        trigger_evaluation: dict[str, Any],
        workflow_runs: list[dict[str, Any]] | None = None,
        duplicate: bool,
    ) -> dict[str, Any]:
        return {
            "accepted": True,
            "duplicate": duplicate,
            "workspace_id": integration.get("workspace_id"),
            "integration_id": integration.get("id"),
            "integration_key": integration.get("integration_key"),
            "intake_event_id": intake_event_id,
            "mode": integration.get("mode"),
            "source": "jotform",
            "trigger_evaluation": trigger_evaluation,
            "workflow_runs": workflow_runs or trigger_evaluation.get("workflow_runs") or [],
            "event": {
                "id": f"jotform:{normalized_payload.get('submission_id') or intake_event_id or 'unknown'}",
                "event_type": "flowforge.integration.jotform.submission_received",
                "node_id": "intake",
                "message": "Jotform intake submission received.",
                "timestamp": normalized_payload.get("received_at"),
                "data": normalized_payload,
            },
            "notes": [
                "Persisted intake event stored.",
                "Trigger evaluation stored.",
                "Workflow run creation processed for selected triggers.",
                "Node execution is deferred to a later FlowForge runtime phase.",
            ],
        }
