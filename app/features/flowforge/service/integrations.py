from __future__ import annotations

import secrets
from typing import Any

from flask import current_app, has_app_context

from app.exceptions.forge_error import ForgeError


class FlowForgeIntegrationServiceMixin:
    def list_integrations(self, *, workspace_id: str, provider: str | None = None) -> list[dict[str, Any]]:
        return [
            self._serialize_integration_config(row, include_secret=False)
            for row in self._integration_repository.list_integration_configs(
                workspace_id=workspace_id,
                provider=provider,
            )
        ]

    def create_jotform_integration(
        self,
        *,
        workspace_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        return self._create_webhook_backed_integration(
            workspace_id=workspace_id,
            payload=payload,
            actor_user_id=actor_user_id,
            provider="jotform",
            secret_prefix="ffjot_",
            public_id_prefix="ffj_",
        )

    def create_webhook_integration(
        self,
        *,
        workspace_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        return self._create_webhook_backed_integration(
            workspace_id=workspace_id,
            payload=payload,
            actor_user_id=actor_user_id,
            provider="webhook",
            secret_prefix="ffweb_",
            public_id_prefix="ffw_",
        )

    def create_file_watch_integration(
        self,
        *,
        workspace_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        integration_key = str(payload.get("integration_key") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()
        if not integration_key:
            raise ForgeError("integration_key is required.", status_code=400)
        if not display_name:
            raise ForgeError("display_name is required.", status_code=400)
        mode = str(payload.get("mode") or "production").strip()
        if mode not in {"production", "test"}:
            raise ForgeError("mode must be production or test.", status_code=400)
        settings = dict(payload.get("settings") if isinstance(payload.get("settings"), dict) else {})
        settings["source_events"] = self._normalize_source_events(payload.get("source_events"))
        settings["source_fields"] = self._normalize_source_fields(payload.get("source_fields"))
        settings["watch_config"] = dict(payload.get("watch_config") if isinstance(payload.get("watch_config"), dict) else {})
        public_id = "fffile_" + secrets.token_urlsafe(18)
        row = self._integration_repository.create_integration_config(
            workspace_id=workspace_id,
            provider="file_watch",
            integration_key=integration_key,
            display_name=display_name,
            external_form_id=None,
            mode=mode,
            webhook_public_id=public_id,
            secret_hash=self._hash_webhook_secret(public_id),
            field_mapping=payload.get("field_mapping") if isinstance(payload.get("field_mapping"), dict) else {},
            test_recipient_overrides=(
                payload.get("test_recipient_overrides") if isinstance(payload.get("test_recipient_overrides"), list) else []
            ),
            settings=settings,
            created_by=str(actor_user_id or "").strip() or None,
        )
        return self._serialize_integration_config(row, include_secret=True)

    def _create_webhook_backed_integration(
        self,
        *,
        workspace_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
        provider: str,
        secret_prefix: str,
        public_id_prefix: str,
    ) -> dict[str, Any]:
        integration_key = str(payload.get("integration_key") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()
        if not integration_key:
            raise ForgeError("integration_key is required.", status_code=400)
        if not display_name:
            raise ForgeError("display_name is required.", status_code=400)
        mode = str(payload.get("mode") or "production").strip()
        if mode not in {"production", "test"}:
            raise ForgeError("mode must be production or test.", status_code=400)
        settings = dict(payload.get("settings") if isinstance(payload.get("settings"), dict) else {})
        settings["source_events"] = self._normalize_source_events(payload.get("source_events"))
        settings["source_fields"] = self._normalize_source_fields(payload.get("source_fields"))
        webhook_secret = secret_prefix + secrets.token_urlsafe(32)
        webhook_public_id = public_id_prefix + secrets.token_urlsafe(18)
        row = self._integration_repository.create_integration_config(
            workspace_id=workspace_id,
            provider=provider,
            integration_key=integration_key,
            display_name=display_name,
            external_form_id=self._optional_string(payload.get("external_form_id")),
            mode=mode,
            webhook_public_id=webhook_public_id,
            secret_hash=self._hash_webhook_secret(webhook_secret),
            field_mapping=payload.get("field_mapping") if isinstance(payload.get("field_mapping"), dict) else {},
            test_recipient_overrides=(
                payload.get("test_recipient_overrides") if isinstance(payload.get("test_recipient_overrides"), list) else []
            ),
            settings=settings,
            created_by=str(actor_user_id or "").strip() or None,
        )
        serialized = self._serialize_integration_config(row, include_secret=True)
        serialized["webhook_secret"] = webhook_secret
        return serialized

    def list_integration_triggers(self, *, workspace_id: str, integration_config_id: int) -> list[dict[str, Any]]:
        integration = self._integration_repository.get_integration_config(
            workspace_id=workspace_id,
            integration_config_id=integration_config_id,
        )
        if integration is None:
            raise ForgeError(f"Integration '{integration_config_id}' was not found.", status_code=404)
        return [
            self._serialize_integration_trigger(row)
            for row in self._integration_repository.list_integration_triggers(
                workspace_id=workspace_id,
                integration_config_id=integration_config_id,
            )
        ]

    def create_integration_trigger(
        self,
        *,
        workspace_id: str,
        integration_config_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        integration = self._integration_repository.get_integration_config(
            workspace_id=workspace_id,
            integration_config_id=integration_config_id,
        )
        if integration is None:
            raise ForgeError(f"Integration '{integration_config_id}' was not found.", status_code=404)

        trigger_key = str(payload.get("trigger_key") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()
        if not trigger_key:
            raise ForgeError("trigger_key is required.", status_code=400)
        if not display_name:
            raise ForgeError("display_name is required.", status_code=400)

        trigger_mode = str(payload.get("trigger_mode") or "always").strip()
        if trigger_mode not in {"always", "conditional"}:
            raise ForgeError("trigger_mode must be always or conditional.", status_code=400)
        trigger_policy = str(payload.get("trigger_policy") or "all_matching").strip()
        if trigger_policy not in {"all_matching", "first_matching"}:
            raise ForgeError("trigger_policy must be all_matching or first_matching.", status_code=400)
        version_strategy = str(payload.get("version_strategy") or "pinned").strip()
        if version_strategy not in {"pinned", "latest_published"}:
            raise ForgeError("version_strategy must be pinned or latest_published.", status_code=400)

        workflow_definition_id = self._positive_int(payload.get("workflow_definition_id"), field_name="workflow_definition_id")
        workflow_version_id = self._optional_positive_int(payload.get("workflow_version_id"), field_name="workflow_version_id")
        if version_strategy == "pinned" and workflow_version_id is None:
            raise ForgeError("workflow_version_id is required when version_strategy is pinned.", status_code=400)

        condition = payload.get("condition")
        if trigger_mode == "conditional":
            if not isinstance(condition, dict) or not condition:
                raise ForgeError("condition must be a non-empty object when trigger_mode is conditional.", status_code=400)
        elif condition is None:
            condition = {}
        elif not isinstance(condition, dict):
            raise ForgeError("condition must be an object when supplied.", status_code=400)

        field_mapping = payload.get("field_mapping")
        if field_mapping is None:
            field_mapping = {}
        if not isinstance(field_mapping, dict):
            raise ForgeError("field_mapping must be an object when supplied.", status_code=400)
        no_match_config = payload.get("no_match_config")
        if no_match_config is None:
            no_match_config = {}
        if not isinstance(no_match_config, dict):
            raise ForgeError("no_match_config must be an object when supplied.", status_code=400)

        priority = self._positive_int(payload.get("priority", 100), field_name="priority")
        return self._serialize_integration_trigger(
            self._integration_repository.create_integration_trigger(
                workspace_id=workspace_id,
                integration_config_id=integration_config_id,
                trigger_key=trigger_key,
                display_name=display_name,
                priority=priority,
                trigger_mode=trigger_mode,
                trigger_policy=trigger_policy,
                version_strategy=version_strategy,
                workflow_definition_id=workflow_definition_id,
                workflow_version_id=workflow_version_id,
                condition=condition,
                field_mapping=field_mapping,
                no_match_config=no_match_config,
                created_by=str(actor_user_id or "").strip() or None,
            )
        )

    def _serialize_integration_config(self, row: dict[str, Any], *, include_secret: bool) -> dict[str, Any]:
        webhook_public_id = str(row.get("webhook_public_id") or "").strip()
        webhook_path = self._integration_webhook_path(
            provider=str(row.get("provider") or "").strip(),
            webhook_public_id=webhook_public_id,
        )
        webhook_base_url = (
            str(current_app.config.get("FLOWFORGE_WEBHOOK_BASE_URL") or "").strip() if has_app_context() else ""
        )
        webhook_url = f"{webhook_base_url.rstrip('/')}{webhook_path}" if webhook_base_url and webhook_path else webhook_path
        settings = row.get("settings") or row.get("settings_json") or {}
        source_events = self._source_events_from_settings(settings)
        source_fields = self._source_fields_from_settings(settings)
        out = {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "provider": row.get("provider"),
            "integration_key": row.get("integration_key"),
            "display_name": row.get("display_name"),
            "external_form_id": row.get("external_form_id"),
            "enabled": bool(row.get("enabled")),
            "mode": row.get("mode"),
            "webhook_public_id": webhook_public_id,
            "webhook_path": webhook_path,
            "webhook_url": webhook_url,
            "field_mapping": row.get("field_mapping") or row.get("field_mapping_json") or {},
            "source_events": source_events,
            "source_fields": source_fields,
            "test_recipient_overrides": row.get("test_recipient_overrides")
            or row.get("test_recipient_overrides_json")
            or [],
            "settings": settings,
        }
        if include_secret:
            out["webhook_secret"] = None
        return out

    def _integration_webhook_path(self, *, provider: str, webhook_public_id: str) -> str | None:
        if not webhook_public_id:
            return None
        if provider == "file_watch":
            return None
        provider_path = {
            "jotform": "jotform",
            "webhook": "generic",
        }.get(provider, provider)
        return f"/api/v1/flowforge/webhooks/{provider_path}/{webhook_public_id}"

    def _source_events_from_settings(self, settings: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(settings, dict):
            return []
        return self._normalize_source_events(settings.get("source_events"))

    def _normalize_source_events(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            event_key = str(item.get("event_key") or item.get("key") or "").strip()
            if not event_key or event_key in seen:
                continue
            seen.add(event_key)
            normalized.append(
                {
                    "event_key": event_key,
                    "display_name": str(item.get("display_name") or item.get("label") or event_key.replace("_", " ")).strip(),
                    "description": self._optional_string(item.get("description")),
                }
            )
        return normalized

    def _source_fields_from_settings(self, settings: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(settings, dict):
            return []
        return self._normalize_source_fields(settings.get("source_fields"))

    def _normalize_source_fields(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        valid_types = {"text", "number", "boolean", "date", "datetime", "email", "phone", "json", "unknown"}
        for item in value:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or item.get("key") or "").strip().strip(".")
            if not path or path in seen:
                continue
            field_type = str(item.get("type") or "text").strip().lower()
            if field_type not in valid_types:
                field_type = "unknown"
            seen.add(path)
            normalized.append(
                {
                    "path": path,
                    "label": str(item.get("label") or path.replace("_", " ").replace(".", " ")).strip(),
                    "type": field_type,
                    "required": bool(item.get("required")),
                    "sensitive": bool(item.get("sensitive")),
                }
            )
        return normalized

    def _serialize_integration_trigger(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "integration_config_id": row.get("integration_config_id"),
            "trigger_key": row.get("trigger_key"),
            "display_name": row.get("display_name"),
            "enabled": bool(row.get("enabled")),
            "priority": row.get("priority"),
            "trigger_mode": row.get("trigger_mode"),
            "trigger_policy": row.get("trigger_policy"),
            "version_strategy": row.get("version_strategy"),
            "workflow_definition_id": row.get("workflow_definition_id"),
            "workflow_version_id": row.get("workflow_version_id"),
            "condition": row.get("condition") or row.get("condition_json") or {},
            "field_mapping": row.get("field_mapping") or row.get("field_mapping_json") or {},
            "no_match_config": row.get("no_match_config") or row.get("no_match_config_json") or {},
        }
