from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.flowforge.repositories import FlowForgeRuntimeRepository

EmailSender = Callable[[str, str, str], Any]


class FlowForgeNotificationDispatcher:
    def __init__(
        self,
        *,
        runtime_repository: FlowForgeRuntimeRepository | None = None,
        email_sender: EmailSender | None = None,
    ) -> None:
        self._runtime_repository = runtime_repository or FlowForgeRuntimeRepository()
        self._email_sender = email_sender or self._send_email

    def dispatch_pending(self, *, limit: int = 25) -> dict[str, Any]:
        notifications = self._runtime_repository.list_pending_notifications(limit=max(1, min(int(limit or 25), 100)))
        sent = 0
        failed = 0
        for notification in notifications:
            try:
                self._dispatch_notification(notification)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self._mark_failed(notification=notification, error_message=str(exc))
        return {"status": "completed", "processed": len(notifications), "sent": sent, "failed": failed}

    def _dispatch_notification(self, notification: dict[str, Any]) -> None:
        recipient = str(notification.get("recipient") or "").strip()
        if not recipient:
            raise ValueError("FlowForge notification recipient is required.")
        if str(notification.get("channel") or "email").strip() != "email":
            raise ValueError("Only email FlowForge notifications are supported.")
        subject, html = self._render_email(notification)
        self._email_sender(recipient, subject, html)
        notification_id = int(notification["id"])
        workspace_id = str(notification.get("workspace_id") or "").strip()
        self._runtime_repository.mark_notification_sent(
            workspace_id=workspace_id,
            notification_id=notification_id,
            provider_message_id="local-email",
        )
        self._append_notification_event(
            notification=notification,
            event_type="workflow.notification.sent",
            message="FlowForge notification sent.",
            payload={"notification_id": notification_id, "template_key": notification.get("template_key")},
        )

    def _mark_failed(self, *, notification: dict[str, Any], error_message: str) -> None:
        notification_id = int(notification["id"])
        workspace_id = str(notification.get("workspace_id") or "").strip()
        self._runtime_repository.mark_notification_failed(
            workspace_id=workspace_id,
            notification_id=notification_id,
            error_message=error_message[:1000],
        )
        self._append_notification_event(
            notification=notification,
            event_type="workflow.notification.failed",
            message="FlowForge notification failed.",
            payload={
                "notification_id": notification_id,
                "template_key": notification.get("template_key"),
                "error_message": error_message[:500],
            },
        )

    def _append_notification_event(
        self,
        *,
        notification: dict[str, Any],
        event_type: str,
        message: str,
        payload: dict[str, Any],
    ) -> None:
        run_id = notification.get("run_id")
        if run_id is None:
            return
        notification_id = int(notification["id"])
        self._runtime_repository.append_run_event(
            workspace_id=str(notification.get("workspace_id") or "").strip(),
            run_id=int(run_id),
            event_type=event_type,
            node_id=None,
            message=message,
            event_payload=payload,
            actor_type="system",
            actor_id="flowforge",
            idempotency_key=f"notification:{notification_id}:{event_type}",
        )

    def _render_email(self, notification: dict[str, Any]) -> tuple[str, str]:
        template_key = str(notification.get("template_key") or "flowforge.notification").strip()
        payload_summary = notification.get("payload_summary") or notification.get("payload_summary_json") or {}
        reason = self._safe_summary_value(payload_summary, "reason") or "A FlowForge workflow requires attention."
        subject = "FlowForge workflow notification"
        if template_key == "flowforge.offer":
            action_url = self._safe_summary_value(payload_summary, "action_url")
            subject = "FlowForge workflow offer"
            html = (
                "<p>A FlowForge workflow offer is waiting for your response.</p>"
                + (f'<p><a href="{self._escape(action_url)}">Review this offer</a></p>' if action_url else "")
                + "<p>Open QueryForge to review the full workflow context.</p>"
            )
            return subject, html
        if template_key == "flowforge.no_match":
            subject = "FlowForge no-match workflow alert"
        html = (
            "<p>A FlowForge workflow notification was generated.</p>"
            f"<p><strong>Reason:</strong> {self._escape(reason)}</p>"
            "<p>Open QueryForge to review the full workflow context.</p>"
        )
        return subject, html

    @staticmethod
    def _safe_summary_value(payload_summary: Any, key: str) -> str | None:
        if not isinstance(payload_summary, dict):
            return None
        value = str(payload_summary.get(key) or "").strip()
        return value or None

    @staticmethod
    def _escape(value: str) -> str:
        return (
            str(value or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )

    @staticmethod
    def _send_email(recipient: str, subject: str, html: str) -> None:
        from app.email.mailer import get_logo, send_email

        send_email(get_logo(), subject, recipient, html)
