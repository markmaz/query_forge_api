from __future__ import annotations

from typing import Any

from app.exceptions.forge_error import ForgeError


class FlowForgeNotificationServiceMixin:
    def list_run_notifications(self, *, workspace_id: str, run_id: int, limit: int) -> dict[str, Any]:
        run = self._runtime_repository.get_run(workspace_id=workspace_id, run_id=run_id)
        if run is None:
            raise ForgeError(f"FlowForge run '{run_id}' was not found.", status_code=404)
        safe_limit = min(max(int(limit or 100), 1), 500)
        rows = self._runtime_repository.list_run_notifications(
            workspace_id=workspace_id,
            run_id=run_id,
            limit=safe_limit,
        )
        return {
            "workspace_id": workspace_id,
            "run_id": int(run_id),
            "limit": safe_limit,
            "notifications": [self._serialize_notification(row) for row in rows],
        }

    def create_no_match_escalation(
        self,
        *,
        workspace_id: str,
        run_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        run = self._runtime_repository.get_run(workspace_id=workspace_id, run_id=run_id)
        if run is None:
            raise ForgeError(f"FlowForge run '{run_id}' was not found.", status_code=404)

        reason = str((payload or {}).get("reason") or "").strip()
        if not reason:
            raise ForgeError("reason is required.", status_code=400)
        recipients = self._normalize_recipients((payload or {}).get("recipients"))
        if not recipients:
            settings = self._settings_repository.get_settings(workspace_id=workspace_id)
            recipients = self._normalize_recipients(settings.get("default_no_match_recipients"))
        if not recipients:
            raise ForgeError("At least one no-match recipient is required.", status_code=400)

        self._runtime_repository.update_run_status(
            workspace_id=workspace_id,
            run_id=run_id,
            status="needs_attention",
            current_node_id="no_match",
        )
        payload_summary = {
            "reason": reason,
            "run_id": int(run_id),
            "workflow_definition_id": run.get("workflow_definition_id"),
            "workflow_version_id": run.get("workflow_version_id"),
            "mode": run.get("mode"),
        }
        for recipient in recipients:
            self._runtime_repository.create_notification(
                workspace_id=workspace_id,
                run_id=run_id,
                human_task_id=None,
                channel="email",
                recipient=recipient,
                template_key="flowforge.no_match",
                status="pending",
                idempotency_key=f"no-match:{run_id}:{recipient}",
                payload_summary=payload_summary,
            )
        self._runtime_repository.append_run_event(
            workspace_id=workspace_id,
            run_id=run_id,
            event_type="workflow.no_match.escalated",
            node_id="no_match",
            message="No-match escalation queued.",
            event_payload={"reason": reason, "recipient_count": len(recipients)},
            actor_type="user",
            actor_id=self._optional_string(actor_user_id),
            idempotency_key=self._optional_string((payload or {}).get("idempotency_key")),
        )
        return {
            "run_id": int(run_id),
            "status": "needs_attention",
            "reason": reason,
            "recipients": recipients,
            "notification_count": len(recipients),
        }

    def _serialize_notification(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "run_id": row.get("run_id"),
            "human_task_id": row.get("human_task_id"),
            "channel": row.get("channel"),
            "recipient": row.get("recipient"),
            "template_key": row.get("template_key"),
            "status": row.get("status"),
            "payload_summary": row.get("payload_summary") or row.get("payload_summary_json") or {},
            "provider_message_id": row.get("provider_message_id"),
            "error_message": row.get("error_message"),
            "created_at": row.get("created_at"),
            "sent_at": row.get("sent_at"),
            "failed_at": row.get("failed_at"),
        }

    def _normalize_recipients(self, raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        recipients = []
        for value in raw:
            text = str(value or "").strip()
            if text and text not in recipients:
                recipients.append(text)
        return recipients
