from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.flowforge.repositories import FlowForgeCommunicationTemplateRepository, FlowForgeRuntimeRepository
from app.features.flowforge.runtime.communication_templates import CommunicationTemplateRenderer

EmailSender = Callable[[str, str, str], Any]


class FlowForgeNotificationDispatcher:
    def __init__(
        self,
        *,
        runtime_repository: FlowForgeRuntimeRepository | None = None,
        communication_template_repository: FlowForgeCommunicationTemplateRepository | None = None,
        communication_template_renderer: CommunicationTemplateRenderer | None = None,
        email_sender: EmailSender | None = None,
    ) -> None:
        self._runtime_repository = runtime_repository or FlowForgeRuntimeRepository()
        self._communication_template_repository = communication_template_repository or FlowForgeCommunicationTemplateRepository()
        self._communication_template_renderer = communication_template_renderer or CommunicationTemplateRenderer()
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
        return {
            "status": "completed_with_failures" if failed else "completed",
            "processed": len(notifications),
            "sent": sent,
            "failed": failed,
        }

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
        self._mark_run_needs_attention(notification=notification)
        self._append_notification_event(
            notification=notification,
            event_type="workflow.notification.failed",
            message="FlowForge notification failed.",
            payload={
                "notification_id": notification_id,
                "template_key": notification.get("template_key"),
                "error_message": error_message[:500],
                "run_status": "needs_attention",
            },
        )

    def _mark_run_needs_attention(self, *, notification: dict[str, Any]) -> None:
        run_id = notification.get("run_id")
        if run_id is None:
            return
        self._runtime_repository.mark_run_needs_attention(
            workspace_id=str(notification.get("workspace_id") or "").strip(),
            run_id=int(run_id),
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
        custom_template = self._communication_template_repository.get_active_template_by_key(
            workspace_id=str(notification.get("workspace_id") or "").strip(),
            template_key=template_key,
            channel=str(notification.get("channel") or "email").strip(),
        )
        if custom_template is not None:
            rendered = self._communication_template_renderer.render_email(
                template=self._template_contract(custom_template),
                context=self._render_context(notification=notification, payload_summary=payload_summary),
                action_url=self._safe_summary_value(payload_summary, "action_url"),
                action_urls=self._action_urls(payload_summary),
            )
            return self._workflow_email_copy(rendered["subject"] or "Workflow notification", rendered["html"])

        reason = self._safe_summary_value(payload_summary, "reason") or "A workflow requires attention."
        subject = "Workflow notification"
        if template_key == "flowforge.human_task":
            action_url = self._safe_summary_value(payload_summary, "action_url")
            subject = "Workflow task"
            html = (
                "<p>A workflow task is waiting for your response.</p>"
                + (f'<p><a href="{self._escape(action_url)}">Review this task</a></p>' if action_url else "")
                + "<p>Open QueryForge to review the full workflow context.</p>"
            )
            return subject, html
        if template_key == "flowforge.no_match":
            subject = "Workflow no-match alert"
        html = (
            "<p>A workflow notification was generated.</p>"
            f"<p><strong>Reason:</strong> {self._escape(reason)}</p>"
            "<p>Open QueryForge to review the full workflow context.</p>"
        )
        return subject, html

    @staticmethod
    def _template_contract(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "template_key": str(row.get("template_key") or ""),
            "channel": str(row.get("channel") or "email"),
            "purpose": str(row.get("purpose") or "notification"),
            "subject": str(row.get("subject") or ""),
            "body_blocks": row.get("body_blocks") or row.get("body_blocks_json") or [],
        }

    def _render_context(self, *, notification: dict[str, Any], payload_summary: Any) -> dict[str, Any]:
        payload = payload_summary if isinstance(payload_summary, dict) else {}
        selected_resource = self._selected_resource_context(payload)
        intake = payload.get("intake") if isinstance(payload.get("intake"), dict) else {}
        task_due_at = self._safe_summary_value(payload, "expires_at")
        return {
            "context": payload,
            "intake": dict(intake),
            "notification": {
                "id": notification.get("id"),
                "template_key": notification.get("template_key"),
            },
            "run": {
                "id": notification.get("run_id"),
            },
            "task": {
                "id": notification.get("human_task_id"),
                "type": "human_task" if notification.get("human_task_id") is not None else "notification",
                "due_at": task_due_at,
            },
            "resource": selected_resource,
            "selected_resource": selected_resource,
        }

    @staticmethod
    def _selected_resource_context(payload: dict[str, Any]) -> dict[str, Any]:
        resource = payload.get("selected_resource") or payload.get("resource")
        if isinstance(resource, dict):
            return dict(resource)
        return {
            "display_name": payload.get("resource_display_name"),
            "source_record_key": payload.get("source_record_key"),
        }

    @staticmethod
    def _safe_summary_value(payload_summary: Any, key: str) -> str | None:
        if not isinstance(payload_summary, dict):
            return None
        value = str(payload_summary.get(key) or "").strip()
        return value or None

    @staticmethod
    def _action_urls(payload_summary: Any) -> dict[str, str] | None:
        if not isinstance(payload_summary, dict):
            return None
        raw_action_urls = payload_summary.get("action_urls")
        if not isinstance(raw_action_urls, dict):
            return None
        action_urls: dict[str, str] = {}
        for action, url in raw_action_urls.items():
            action_key = str(action or "").strip()
            url_value = str(url or "").strip()
            if action_key and url_value:
                action_urls[action_key] = url_value
        return action_urls or None

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
    def _workflow_email_copy(subject: str, html: str) -> tuple[str, str]:
        return str(subject or "").replace("FlowForge", "Workflow"), str(html or "").replace("FlowForge", "Workflow")

    @staticmethod
    def _send_email(recipient: str, subject: str, html: str) -> None:
        from app.email.mailer import get_logo, send_email

        send_email(get_logo(), subject, recipient, html)
