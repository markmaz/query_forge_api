from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.features.flowforge.repositories.common import bool_value as _bool, json_or_none as _json_or_none, json_value as _json_value, lastrowid as _lastrowid


class FlowForgeIntegrationRepository:
    _CONFIG_JSON_KEYS = {
        "field_mapping_json",
        "test_recipient_overrides_json",
        "settings_json",
    }
    _TRIGGER_JSON_KEYS = {
        "condition_json",
        "field_mapping_json",
        "no_match_config_json",
    }

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_integration_configs(self, *, workspace_id: str, provider: str | None = None) -> list[dict[str, Any]]:
        provider_filter = str(provider or "").strip()
        where_provider = "AND provider = :provider" if provider_filter else ""
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT *
            FROM flowforge_integration_configs
            WHERE workspace_id = :workspace_id
              {where_provider}
            ORDER BY provider ASC, display_name ASC, id ASC
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "provider": provider_filter,
            },
        )
        return [self._decode_integration_config(row) for row in rows]

    def get_integration_config_by_public_id(self, *, webhook_public_id: str) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_integration_configs
            WHERE webhook_public_id = :webhook_public_id
            LIMIT 1
            """,
            {"webhook_public_id": str(webhook_public_id or "").strip()},
        )
        if not rows:
            return None
        return self._decode_integration_config(rows[0])

    def get_integration_config(self, *, workspace_id: str, integration_config_id: int) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_integration_configs
            WHERE workspace_id = :workspace_id
              AND id = :integration_config_id
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "integration_config_id": int(integration_config_id),
            },
        )
        if not rows:
            return None
        return self._decode_integration_config(rows[0])

    def create_integration_config(
        self,
        *,
        workspace_id: str,
        provider: str,
        integration_key: str,
        display_name: str,
        webhook_public_id: str,
        secret_hash: str,
        created_by: str | None,
        external_form_id: str | None = None,
        mode: str = "production",
        field_mapping: dict[str, Any] | None = None,
        test_recipient_overrides: list[Any] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_integration_configs (
              workspace_id,
              provider,
              integration_key,
              display_name,
              external_form_id,
              mode,
              webhook_public_id,
              secret_hash,
              field_mapping_json,
              test_recipient_overrides_json,
              settings_json,
              created_by
            ) VALUES (
              :workspace_id,
              :provider,
              :integration_key,
              :display_name,
              :external_form_id,
              :mode,
              :webhook_public_id,
              :secret_hash,
              :field_mapping_json,
              :test_recipient_overrides_json,
              :settings_json,
              :created_by
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "provider": str(provider or "").strip(),
                "integration_key": str(integration_key or "").strip(),
                "display_name": str(display_name or "").strip(),
                "external_form_id": external_form_id,
                "mode": str(mode or "production").strip(),
                "webhook_public_id": str(webhook_public_id or "").strip(),
                "secret_hash": str(secret_hash or "").strip(),
                "field_mapping_json": _json_or_none(field_mapping),
                "test_recipient_overrides_json": _json_or_none(test_recipient_overrides or []),
                "settings_json": _json_or_none(settings),
                "created_by": created_by,
            },
        )
        return {
            "id": _lastrowid(result),
            "workspace_id": str(workspace_id or "").strip(),
            "provider": str(provider or "").strip(),
            "integration_key": str(integration_key or "").strip(),
            "display_name": str(display_name or "").strip(),
            "external_form_id": external_form_id,
            "enabled": True,
            "mode": str(mode or "production").strip(),
            "webhook_public_id": str(webhook_public_id or "").strip(),
            "field_mapping_json": field_mapping or {},
            "test_recipient_overrides_json": test_recipient_overrides or [],
            "settings_json": settings or {},
        }

    def list_integration_triggers(self, *, workspace_id: str, integration_config_id: int) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_integration_triggers
            WHERE workspace_id = :workspace_id
              AND integration_config_id = :integration_config_id
            ORDER BY enabled DESC, priority ASC, id ASC
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "integration_config_id": int(integration_config_id),
            },
        )
        return [self._decode_integration_trigger(row) for row in rows]

    def create_integration_trigger(
        self,
        *,
        workspace_id: str,
        integration_config_id: int,
        trigger_key: str,
        display_name: str,
        priority: int,
        trigger_mode: str,
        trigger_policy: str,
        version_strategy: str,
        workflow_definition_id: int,
        workflow_version_id: int | None,
        condition: dict[str, Any] | None,
        field_mapping: dict[str, Any] | None,
        no_match_config: dict[str, Any] | None,
        created_by: str | None,
    ) -> dict[str, Any]:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_integration_triggers (
              workspace_id,
              integration_config_id,
              trigger_key,
              display_name,
              priority,
              trigger_mode,
              trigger_policy,
              version_strategy,
              workflow_definition_id,
              workflow_version_id,
              condition_json,
              field_mapping_json,
              no_match_config_json,
              created_by
            ) VALUES (
              :workspace_id,
              :integration_config_id,
              :trigger_key,
              :display_name,
              :priority,
              :trigger_mode,
              :trigger_policy,
              :version_strategy,
              :workflow_definition_id,
              :workflow_version_id,
              :condition_json,
              :field_mapping_json,
              :no_match_config_json,
              :created_by
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "integration_config_id": int(integration_config_id),
                "trigger_key": str(trigger_key or "").strip(),
                "display_name": str(display_name or "").strip(),
                "priority": int(priority),
                "trigger_mode": str(trigger_mode or "always").strip(),
                "trigger_policy": str(trigger_policy or "all_matching").strip(),
                "version_strategy": str(version_strategy or "pinned").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "workflow_version_id": int(workflow_version_id) if workflow_version_id is not None else None,
                "condition_json": _json_or_none(condition or {}),
                "field_mapping_json": _json_or_none(field_mapping or {}),
                "no_match_config_json": _json_or_none(no_match_config or {}),
                "created_by": created_by,
            },
        )
        return {
            "id": _lastrowid(result),
            "workspace_id": str(workspace_id or "").strip(),
            "integration_config_id": int(integration_config_id),
            "trigger_key": str(trigger_key or "").strip(),
            "display_name": str(display_name or "").strip(),
            "enabled": True,
            "priority": int(priority),
            "trigger_mode": str(trigger_mode or "always").strip(),
            "trigger_policy": str(trigger_policy or "all_matching").strip(),
            "version_strategy": str(version_strategy or "pinned").strip(),
            "workflow_definition_id": int(workflow_definition_id),
            "workflow_version_id": int(workflow_version_id) if workflow_version_id is not None else None,
            "condition_json": condition or {},
            "field_mapping_json": field_mapping or {},
            "no_match_config_json": no_match_config or {},
        }

    def create_intake_event(
        self,
        *,
        workspace_id: str,
        integration_config_id: int,
        provider: str,
        external_form_id: str | None,
        external_submission_id: str | None,
        mode: str,
        idempotency_key: str,
        normalized_payload: dict[str, Any],
        raw_payload: dict[str, Any] | None,
        received_at: datetime,
        raw_payload_expires_at: datetime | None,
        trigger_evaluation: dict[str, Any] | None = None,
        source_ip: str | None = None,
        headers: dict[str, Any] | None = None,
        sensitive_fields: dict[str, Any] | None = None,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_intake_events (
              workspace_id,
              integration_config_id,
              provider,
              external_form_id,
              external_submission_id,
              mode,
              idempotency_key,
              received_at,
              source_ip,
              headers_json,
              raw_payload_json,
              normalized_payload_json,
              sensitive_fields_json,
              trigger_evaluation_json,
              raw_payload_expires_at
            ) VALUES (
              :workspace_id,
              :integration_config_id,
              :provider,
              :external_form_id,
              :external_submission_id,
              :mode,
              :idempotency_key,
              :received_at,
              :source_ip,
              :headers_json,
              :raw_payload_json,
              :normalized_payload_json,
              :sensitive_fields_json,
              :trigger_evaluation_json,
              :raw_payload_expires_at
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "integration_config_id": int(integration_config_id),
                "provider": str(provider or "").strip(),
                "external_form_id": external_form_id,
                "external_submission_id": external_submission_id,
                "mode": str(mode or "production").strip(),
                "idempotency_key": str(idempotency_key or "").strip(),
                "received_at": received_at,
                "source_ip": source_ip,
                "headers_json": _json_or_none(headers),
                "raw_payload_json": _json_or_none(raw_payload),
                "normalized_payload_json": _json_or_none(normalized_payload),
                "sensitive_fields_json": _json_or_none(sensitive_fields),
                "trigger_evaluation_json": _json_or_none(trigger_evaluation),
                "raw_payload_expires_at": raw_payload_expires_at,
            },
        )
        return _lastrowid(result)

    def get_intake_event_by_idempotency(self, *, workspace_id: str, idempotency_key: str) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_intake_events
            WHERE workspace_id = :workspace_id
              AND idempotency_key = :idempotency_key
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "idempotency_key": str(idempotency_key or "").strip(),
            },
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["headers_json"] = _json_value(row.get("headers_json")) or {}
        row["raw_payload_json"] = _json_value(row.get("raw_payload_json")) or {}
        row["normalized_payload_json"] = _json_value(row.get("normalized_payload_json")) or {}
        row["sensitive_fields_json"] = _json_value(row.get("sensitive_fields_json")) or {}
        row["trigger_evaluation_json"] = _json_value(row.get("trigger_evaluation_json")) or {}
        return row

    def update_intake_event_trigger_evaluation(
        self,
        *,
        workspace_id: str,
        intake_event_id: int,
        trigger_evaluation: dict[str, Any],
    ) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_intake_events
            SET trigger_evaluation_json = :trigger_evaluation_json,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :intake_event_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "intake_event_id": int(intake_event_id),
                "trigger_evaluation_json": _json_or_none(trigger_evaluation),
            },
        )
        return int(updated or 0) > 0

    def purge_expired_raw_payloads(self, *, limit: int = 500) -> int:
        purged = self._sql.execute_write(
            """
            UPDATE flowforge_intake_events
            SET raw_payload_json = NULL,
                headers_json = NULL,
                sensitive_fields_json = NULL,
                raw_payload_redacted_at = CURRENT_TIMESTAMP,
                raw_payload_redacted_by = 'flowforge.retention_purge',
                updated_at = CURRENT_TIMESTAMP
            WHERE raw_payload_expires_at IS NOT NULL
              AND raw_payload_expires_at <= CURRENT_TIMESTAMP
              AND raw_payload_redacted_at IS NULL
            LIMIT :limit
            """,
            {"limit": max(1, min(int(limit or 500), 5000))},
        )
        return int(purged or 0)

    def _decode_integration_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        row["enabled"] = _bool(row.get("enabled"))
        for key in self._CONFIG_JSON_KEYS:
            row[key] = _json_value(row.get(key))
        return row

    def _decode_integration_trigger(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        row["enabled"] = _bool(row.get("enabled"))
        row["priority"] = int(row.get("priority") or 100)
        for key in self._TRIGGER_JSON_KEYS:
            row[key] = _json_value(row.get(key)) or {}
        return row
