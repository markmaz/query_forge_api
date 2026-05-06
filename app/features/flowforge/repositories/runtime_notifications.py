from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories.common import json_or_none as _json_or_none, json_value as _json_value, lastrowid as _lastrowid


class FlowForgeRuntimeNotificationRepositoryMixin:
    def list_pending_notifications(self, *, limit: int) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_notifications
            WHERE status = 'pending'
            ORDER BY created_at ASC, id ASC
            LIMIT :limit
            """,
            {"limit": int(limit)},
        )
        return [self._decode_notification(row) for row in rows]

    def create_notification(
        self,
        *,
        workspace_id: str,
        run_id: int | None,
        human_task_id: int | None,
        channel: str,
        recipient: str,
        template_key: str,
        status: str,
        idempotency_key: str,
        payload_summary: dict[str, Any] | None,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_notifications (
              workspace_id,
              run_id,
              human_task_id,
              channel,
              recipient,
              template_key,
              status,
              idempotency_key,
              payload_summary_json
            ) VALUES (
              :workspace_id,
              :run_id,
              :human_task_id,
              :channel,
              :recipient,
              :template_key,
              :status,
              :idempotency_key,
              :payload_summary_json
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id) if run_id is not None else None,
                "human_task_id": int(human_task_id) if human_task_id is not None else None,
                "channel": str(channel or "email").strip(),
                "recipient": str(recipient or "").strip(),
                "template_key": str(template_key or "").strip(),
                "status": str(status or "pending").strip(),
                "idempotency_key": str(idempotency_key or "").strip(),
                "payload_summary_json": _json_or_none(payload_summary),
            },
        )
        return _lastrowid(result)

    def list_run_notifications(self, *, workspace_id: str, run_id: int, limit: int) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_notifications
            WHERE workspace_id = :workspace_id
              AND run_id = :run_id
            ORDER BY created_at ASC, id ASC
            LIMIT :limit
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id),
                "limit": int(limit),
            },
        )
        return [self._decode_notification(row) for row in rows]

    def mark_notification_sent(
        self,
        *,
        workspace_id: str,
        notification_id: int,
        provider_message_id: str | None,
    ) -> bool:
        count = self._sql.execute_write(
            """
            UPDATE flowforge_notifications
            SET status = 'sent',
                provider_message_id = :provider_message_id,
                sent_at = CURRENT_TIMESTAMP,
                error_message = NULL
            WHERE workspace_id = :workspace_id
              AND id = :notification_id
              AND status = 'pending'
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "notification_id": int(notification_id),
                "provider_message_id": provider_message_id,
            },
        )
        return bool(count)

    def mark_notification_failed(
        self,
        *,
        workspace_id: str,
        notification_id: int,
        error_message: str,
    ) -> bool:
        count = self._sql.execute_write(
            """
            UPDATE flowforge_notifications
            SET status = 'failed',
                failed_at = CURRENT_TIMESTAMP,
                error_message = :error_message
            WHERE workspace_id = :workspace_id
              AND id = :notification_id
              AND status = 'pending'
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "notification_id": int(notification_id),
                "error_message": str(error_message or "").strip(),
            },
        )
        return bool(count)

    def _decode_notification(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        row["payload_summary_json"] = _json_value(row.get("payload_summary_json")) or {}
        return row
