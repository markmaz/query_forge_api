from __future__ import annotations

from typing import Any, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.features.flowforge.repositories.common import json_or_none as _json_or_none, json_value as _json_value, lastrowid as _lastrowid
from app.ports.sql_executor import ForgeQueryPort


class FlowForgeCommunicationTemplateRepository:
    _JSON_KEYS = {
        "body_blocks_json",
        "generated_body_blocks_json",
        "metadata_json",
        "required_actions_json",
        "validation_result_json",
    }

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_templates(
        self,
        *,
        workspace_id: str,
        status: str | None = None,
        purpose: str | None = None,
        channel: str | None = None,
        resource_set_id: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_communication_templates
            WHERE workspace_id = :workspace_id
              AND archived_at IS NULL
              AND (:status IS NULL OR status = :status)
              AND (:purpose IS NULL OR purpose = :purpose)
              AND (:channel IS NULL OR channel = :channel)
              AND (
                :resource_set_id IS NULL
                OR resource_set_id = :resource_set_id
                OR resource_set_id IS NULL
              )
            ORDER BY display_name ASC, id ASC
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "status": status,
                "purpose": purpose,
                "channel": channel,
                "resource_set_id": int(resource_set_id) if resource_set_id is not None else None,
            },
        )
        return [self._decode_template(row) for row in rows]

    def get_template(self, *, workspace_id: str, template_id: int) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_communication_templates
            WHERE workspace_id = :workspace_id
              AND id = :template_id
              AND archived_at IS NULL
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "template_id": int(template_id),
            },
        )
        if not rows:
            return None
        return self._decode_template(rows[0])

    def get_active_template_by_key(
        self,
        *,
        workspace_id: str,
        template_key: str,
        channel: str = "email",
    ) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_communication_templates
            WHERE workspace_id = :workspace_id
              AND template_key = :template_key
              AND channel = :channel
              AND status = 'active'
              AND validation_status = 'valid'
              AND archived_at IS NULL
            ORDER BY activated_at DESC, updated_at DESC, id DESC
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "template_key": str(template_key or "").strip(),
                "channel": str(channel or "email").strip(),
            },
        )
        if not rows:
            return None
        return self._decode_template(rows[0])

    def create_template(
        self,
        *,
        workspace_id: str,
        template_key: str,
        display_name: str,
        description: str | None,
        channel: str,
        purpose: str,
        resource_set_id: int | None,
        subject: str,
        body_blocks: list[dict[str, Any]],
        status: str,
        validation_status: str,
        validation_result: dict[str, Any],
        metadata: dict[str, Any] | None,
        created_by: str | None,
    ) -> dict[str, Any]:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_communication_templates (
              workspace_id,
              template_key,
              display_name,
              description,
              channel,
              purpose,
              resource_set_id,
              subject,
              body_blocks_json,
              status,
              validation_status,
              validation_result_json,
              metadata_json,
              created_by
            ) VALUES (
              :workspace_id,
              :template_key,
              :display_name,
              :description,
              :channel,
              :purpose,
              :resource_set_id,
              :subject,
              :body_blocks_json,
              :status,
              :validation_status,
              :validation_result_json,
              :metadata_json,
              :created_by
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "template_key": str(template_key or "").strip(),
                "display_name": str(display_name or "").strip(),
                "description": description,
                "channel": str(channel or "email").strip(),
                "purpose": str(purpose or "notification").strip(),
                "resource_set_id": int(resource_set_id) if resource_set_id is not None else None,
                "subject": str(subject or "").strip(),
                "body_blocks_json": _json_or_none(body_blocks),
                "status": str(status or "draft").strip(),
                "validation_status": str(validation_status or "pending").strip(),
                "validation_result_json": _json_or_none(validation_result),
                "metadata_json": _json_or_none(metadata or {}),
                "created_by": created_by,
            },
        )
        return {
            "id": _lastrowid(result),
            "workspace_id": str(workspace_id or "").strip(),
            "template_key": str(template_key or "").strip(),
            "display_name": str(display_name or "").strip(),
            "description": description,
            "channel": str(channel or "email").strip(),
            "purpose": str(purpose or "notification").strip(),
            "resource_set_id": int(resource_set_id) if resource_set_id is not None else None,
            "subject": str(subject or "").strip(),
            "body_blocks_json": body_blocks,
            "status": str(status or "draft").strip(),
            "validation_status": str(validation_status or "pending").strip(),
            "validation_result_json": validation_result,
            "metadata_json": metadata or {},
        }

    def update_template(
        self,
        *,
        workspace_id: str,
        template_id: int,
        payload: dict[str, Any],
        updated_by: str | None,
    ) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_communication_templates
            SET display_name = :display_name,
                description = :description,
                channel = :channel,
                purpose = :purpose,
                resource_set_id = :resource_set_id,
                subject = :subject,
                body_blocks_json = :body_blocks_json,
                status = :status,
                validation_status = :validation_status,
                validation_result_json = :validation_result_json,
                metadata_json = :metadata_json,
                updated_by = :updated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :template_id
              AND archived_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "template_id": int(template_id),
                "display_name": str(payload.get("display_name") or "").strip(),
                "description": payload.get("description"),
                "channel": str(payload.get("channel") or "email").strip(),
                "purpose": str(payload.get("purpose") or "notification").strip(),
                "resource_set_id": int(payload["resource_set_id"]) if payload.get("resource_set_id") is not None else None,
                "subject": str(payload.get("subject") or "").strip(),
                "body_blocks_json": _json_or_none(payload.get("body_blocks") or []),
                "status": str(payload.get("status") or "draft").strip(),
                "validation_status": str(payload.get("validation_status") or "pending").strip(),
                "validation_result_json": _json_or_none(payload.get("validation_result") or {}),
                "metadata_json": _json_or_none(payload.get("metadata") or {}),
                "updated_by": updated_by,
            },
        )
        return int(updated or 0) > 0

    def activate_template(
        self,
        *,
        workspace_id: str,
        template_id: int,
        validation_result: dict[str, Any],
        activated_by: str | None,
    ) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_communication_templates
            SET status = 'active',
                validation_status = 'valid',
                validation_result_json = :validation_result_json,
                activated_by = :activated_by,
                activated_at = CURRENT_TIMESTAMP,
                updated_by = :activated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :template_id
              AND archived_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "template_id": int(template_id),
                "validation_result_json": _json_or_none(validation_result),
                "activated_by": activated_by,
            },
        )
        return int(updated or 0) > 0

    def create_ai_draft(
        self,
        *,
        workspace_id: str,
        purpose: str,
        channel: str,
        resource_set_id: int | None,
        prompt: str,
        tone: str | None,
        required_actions: list[str],
        generated_subject: str,
        generated_body_blocks: list[dict[str, Any]],
        plain_language_summary: str | None,
        validation_status: str,
        validation_result: dict[str, Any],
        model_provider: str | None,
        model_name: str | None,
        status: str,
        created_by: str | None,
    ) -> dict[str, Any]:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_communication_template_ai_drafts (
              workspace_id,
              purpose,
              channel,
              resource_set_id,
              prompt,
              tone,
              required_actions_json,
              generated_subject,
              generated_body_blocks_json,
              plain_language_summary,
              validation_status,
              validation_result_json,
              model_provider,
              model_name,
              status,
              created_by
            ) VALUES (
              :workspace_id,
              :purpose,
              :channel,
              :resource_set_id,
              :prompt,
              :tone,
              :required_actions_json,
              :generated_subject,
              :generated_body_blocks_json,
              :plain_language_summary,
              :validation_status,
              :validation_result_json,
              :model_provider,
              :model_name,
              :status,
              :created_by
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "purpose": str(purpose or "notification").strip(),
                "channel": str(channel or "email").strip(),
                "resource_set_id": int(resource_set_id) if resource_set_id is not None else None,
                "prompt": str(prompt or "").strip(),
                "tone": tone,
                "required_actions_json": _json_or_none(required_actions),
                "generated_subject": str(generated_subject or "").strip(),
                "generated_body_blocks_json": _json_or_none(generated_body_blocks),
                "plain_language_summary": plain_language_summary,
                "validation_status": str(validation_status or "pending").strip(),
                "validation_result_json": _json_or_none(validation_result),
                "model_provider": model_provider,
                "model_name": model_name,
                "status": str(status or "drafted").strip(),
                "created_by": created_by,
            },
        )
        return {
            "id": _lastrowid(result),
            "workspace_id": str(workspace_id or "").strip(),
            "purpose": str(purpose or "notification").strip(),
            "channel": str(channel or "email").strip(),
            "resource_set_id": int(resource_set_id) if resource_set_id is not None else None,
            "prompt": str(prompt or "").strip(),
            "tone": tone,
            "required_actions_json": required_actions,
            "generated_subject": str(generated_subject or "").strip(),
            "generated_body_blocks_json": generated_body_blocks,
            "plain_language_summary": plain_language_summary,
            "validation_status": str(validation_status or "pending").strip(),
            "validation_result_json": validation_result,
            "model_provider": model_provider,
            "model_name": model_name,
            "status": str(status or "drafted").strip(),
        }

    def _decode_template(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        for key in self._JSON_KEYS:
            row[key] = _json_value(row.get(key))
        return row
