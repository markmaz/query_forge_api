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
        integration = self._get_webhook_integration(
            webhook_public_id=public_id,
            provider="jotform",
            provider_label="Jotform",
        )
        normalized = self._normalize_jotform_payload(payload)
        submission_id = self._optional_string(normalized.get("submission_id"))
        return self._accept_integration_webhook_event(
            integration=integration,
            webhook_public_id=public_id,
            payload=payload,
            token=token,
            source_ip=source_ip,
            headers=headers,
            provider="jotform",
            provider_label="Jotform",
            normalized_payload=normalized,
            idempotency_key=self._jotform_idempotency_key(
                webhook_public_id=public_id,
                normalized_payload=normalized,
                raw_payload=payload,
            ),
            external_form_id=self._optional_string(normalized.get("form_id") or integration.get("external_form_id")),
            external_submission_id=submission_id,
            event_id=f"jotform:{submission_id or 'unknown'}",
            event_type="flowforge.integration.jotform.submission_received",
            event_message="Jotform intake submission received.",
        )

    def accept_generic_integration_webhook(
        self,
        *,
        webhook_public_id: str,
        payload: dict[str, Any],
        token: str,
        source_ip: str | None = None,
        headers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        public_id = str(webhook_public_id or "").strip()
        integration = self._get_webhook_integration(
            webhook_public_id=public_id,
            provider="webhook",
            provider_label="Webhook",
        )
        normalized = self._normalize_generic_webhook_payload(payload)
        external_event_id = self._optional_string(normalized.get("external_event_id"))
        return self._accept_integration_webhook_event(
            integration=integration,
            webhook_public_id=public_id,
            payload=payload,
            token=token,
            source_ip=source_ip,
            headers=headers,
            provider="webhook",
            provider_label="Webhook",
            normalized_payload=normalized,
            idempotency_key=self._generic_webhook_idempotency_key(
                webhook_public_id=public_id,
                normalized_payload=normalized,
                raw_payload=payload,
            ),
            external_form_id=None,
            external_submission_id=external_event_id,
            event_id=f"webhook:{external_event_id or 'unknown'}",
            event_type="flowforge.integration.webhook.received",
            event_message="Webhook event received.",
        )

    def _get_webhook_integration(
        self,
        *,
        webhook_public_id: str,
        provider: str,
        provider_label: str,
    ) -> dict[str, Any]:
        integration = self._integration_repository.get_integration_config_by_public_id(webhook_public_id=webhook_public_id)
        if integration is None or str(integration.get("provider") or "").strip() != provider:
            raise ForgeError(f"{provider_label} integration was not found.", status_code=404)
        if not bool(integration.get("enabled")):
            raise ForgeError(f"{provider_label} integration is disabled.", status_code=403)
        return integration

    def _accept_integration_webhook_event(
        self,
        *,
        integration: dict[str, Any],
        webhook_public_id: str,
        payload: dict[str, Any],
        token: str,
        source_ip: str | None,
        headers: dict[str, Any] | None,
        provider: str,
        provider_label: str,
        normalized_payload: dict[str, Any],
        idempotency_key: str,
        external_form_id: str | None,
        external_submission_id: str | None,
        event_id: str,
        event_type: str,
        event_message: str,
    ) -> dict[str, Any]:
        del webhook_public_id
        self._assert_integration_webhook_secret(
            provided_token=token,
            expected_hash=str(integration.get("secret_hash") or "").strip(),
            provider_label=provider_label,
        )

        workspace_id = str(integration.get("workspace_id") or "").strip()
        existing = self._integration_repository.get_intake_event_by_idempotency(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return self._serialize_persisted_webhook_response(
                integration=integration,
                intake_event_id=int(existing.get("id") or 0),
                normalized_payload=existing.get("normalized_payload_json") or normalized_payload,
                trigger_evaluation=existing.get("trigger_evaluation_json") or {},
                workflow_runs=None,
                duplicate=True,
                source=provider,
                event_id=event_id,
                event_type=event_type,
                event_message=event_message,
            )

        received_at = datetime.now(timezone.utc)
        raw_payload_expires_at = received_at + timedelta(days=self._raw_payload_retention_days(workspace_id=workspace_id))
        trigger_evaluation = self._evaluate_integration_triggers(
            workspace_id=workspace_id,
            integration_config_id=int(integration["id"]),
            normalized_payload=normalized_payload,
        )
        intake_event_id = self._integration_repository.create_intake_event(
            workspace_id=workspace_id,
            integration_config_id=int(integration["id"]),
            provider=provider,
            external_form_id=external_form_id,
            external_submission_id=external_submission_id,
            mode=str(integration.get("mode") or "production"),
            idempotency_key=idempotency_key,
            normalized_payload=normalized_payload,
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
            normalized_payload=normalized_payload,
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
        return self._serialize_persisted_webhook_response(
            integration=integration,
            intake_event_id=int(intake_event_id),
            normalized_payload=normalized_payload,
            trigger_evaluation=trigger_evaluation,
            workflow_runs=workflow_runs,
            duplicate=False,
            source=provider,
            event_id=event_id,
            event_type=event_type,
            event_message=event_message,
        )

    def _assert_integration_webhook_secret(self, *, provided_token: str, expected_hash: str, provider_label: str = "Jotform") -> None:
        if not expected_hash:
            raise ForgeError(f"{provider_label} integration secret is not configured.", status_code=503)
        provided_hash = self._hash_webhook_secret(provided_token)
        if not provided_token or not secrets.compare_digest(provided_hash, expected_hash):
            raise ForgeError(f"Invalid {provider_label} webhook token.", status_code=401)

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

    def _normalize_generic_webhook_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        fields = payload.get("fields")
        if not isinstance(fields, dict):
            fields = {key: value for key, value in payload.items() if key not in {"fields", "raw"}}
        return {
            "provider": "webhook",
            "event_key": self._first_string(
                payload.get("event_key"),
                payload.get("event"),
                payload.get("eventType"),
                payload.get("type"),
            )
            or "webhook_received",
            "external_event_id": self._first_string(
                payload.get("event_id"),
                payload.get("eventId"),
                payload.get("id"),
            ),
            "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "fields": fields,
            "raw": payload,
        }

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

    def _generic_webhook_idempotency_key(
        self,
        *,
        webhook_public_id: str,
        normalized_payload: dict[str, Any],
        raw_payload: dict[str, Any],
    ) -> str:
        external_event_id = self._optional_string(normalized_payload.get("external_event_id"))
        if external_event_id:
            return f"webhook:{webhook_public_id}:event:{external_event_id}"
        fingerprint = hashlib.sha256(
            json.dumps(raw_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        return f"webhook:{webhook_public_id}:payload:{fingerprint}"

    def _raw_payload_retention_days(self, *, workspace_id: str) -> int:
        settings = self._settings_repository.get_settings(workspace_id=workspace_id)
        retention_days = int(settings.get("raw_payload_retention_days") or 30)
        max_days = int(settings.get("raw_payload_retention_max_days") or 90)
        return max(1, min(retention_days, max_days))

    def _serialize_persisted_webhook_response(
        self,
        *,
        integration: dict[str, Any],
        intake_event_id: int,
        normalized_payload: dict[str, Any],
        trigger_evaluation: dict[str, Any],
        workflow_runs: list[dict[str, Any]] | None = None,
        duplicate: bool,
        source: str,
        event_id: str,
        event_type: str,
        event_message: str,
    ) -> dict[str, Any]:
        if event_id.endswith(":unknown") and intake_event_id:
            event_id = f"{source}:{intake_event_id}"
        return {
            "accepted": True,
            "duplicate": duplicate,
            "workspace_id": integration.get("workspace_id"),
            "integration_id": integration.get("id"),
            "integration_key": integration.get("integration_key"),
            "intake_event_id": intake_event_id,
            "mode": integration.get("mode"),
            "source": source,
            "trigger_evaluation": trigger_evaluation,
            "workflow_runs": workflow_runs or trigger_evaluation.get("workflow_runs") or [],
            "event": {
                "id": event_id,
                "event_type": event_type,
                "node_id": "intake",
                "message": event_message,
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
