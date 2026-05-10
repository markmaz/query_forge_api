from __future__ import annotations

from typing import Any

from app.exceptions.forge_error import ForgeError


class FlowForgeSettingsServiceMixin:
    def get_workspace_settings(self, *, workspace_id: str) -> dict[str, Any]:
        return self._serialize_workspace_settings(self._settings_repository.get_settings(workspace_id=workspace_id))

    def update_workspace_settings(
        self,
        *,
        workspace_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        current = self._settings_repository.get_settings(workspace_id=workspace_id)
        max_days = int(current.get("raw_payload_retention_max_days") or 90)

        update = {
            "enabled": bool(payload.get("enabled", current.get("enabled", False))),
            "allow_designer_publish": bool(
                payload.get("allow_designer_publish", current.get("allow_designer_publish", False))
            ),
            "block_sensitive_reporting_mcp": bool(
                payload.get(
                    "block_sensitive_reporting_mcp",
                    current.get("block_sensitive_reporting_mcp", False),
                )
            ),
            "allow_user_run_as_for_production": bool(
                payload.get(
                    "allow_user_run_as_for_production",
                    current.get("allow_user_run_as_for_production", False),
                )
            ),
            "require_service_principal_for_automated_triggers": bool(
                payload.get(
                    "require_service_principal_for_automated_triggers",
                    current.get("require_service_principal_for_automated_triggers", True),
                )
            ),
            "raw_payload_retention_days": self._bounded_int(
                payload.get("raw_payload_retention_days", current.get("raw_payload_retention_days", 30)),
                field_name="raw_payload_retention_days",
                minimum=1,
                maximum=max_days,
            ),
            "raw_payload_retention_max_days": max_days,
            "default_offer_timeout_minutes": self._bounded_int(
                payload.get("default_offer_timeout_minutes", current.get("default_offer_timeout_minutes", 1440)),
                field_name="default_offer_timeout_minutes",
                minimum=5,
                maximum=43200,
            ),
            "default_no_match_recipients": self._normalize_email_list(
                payload.get("default_no_match_recipients", current.get("default_no_match_recipients", [])),
                field_name="default_no_match_recipients",
            ),
            "default_test_recipients": self._normalize_email_list(
                payload.get("default_test_recipients", current.get("default_test_recipients", [])),
                field_name="default_test_recipients",
            ),
            "settings": payload.get("settings", current.get("settings", {})),
            "updated_by": self._optional_string(actor_user_id),
        }
        if not isinstance(update["settings"], dict):
            raise ForgeError("settings must be an object.", status_code=400)
        update["settings"] = {
            **update["settings"],
            "block_sensitive_reporting_mcp": update["block_sensitive_reporting_mcp"],
            "allow_user_run_as_for_production": update["allow_user_run_as_for_production"],
            "require_service_principal_for_automated_triggers": update[
                "require_service_principal_for_automated_triggers"
            ],
        }

        saved = self._settings_repository.upsert_settings(workspace_id=workspace_id, payload=update)
        return self._serialize_workspace_settings(saved)

    def _bounded_int(self, value: Any, *, field_name: str, minimum: int, maximum: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ForgeError(f"{field_name} must be an integer.", status_code=400) from None
        if number < minimum or number > maximum:
            raise ForgeError(f"{field_name} must be between {minimum} and {maximum}.", status_code=400)
        return number

    def _normalize_email_list(self, value: Any, *, field_name: str) -> list[str]:
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise ForgeError(f"{field_name} must be a list of email addresses.", status_code=400)
        emails = []
        for item in value:
            email = str(item or "").strip()
            if not email:
                continue
            if "@" not in email:
                raise ForgeError(f"{field_name} contains an invalid email address.", status_code=400)
            emails.append(email)
        return emails

    def _serialize_workspace_settings(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "workspace_id": row.get("workspace_id"),
            "enabled": bool(row.get("enabled")),
            "allow_designer_publish": bool(row.get("allow_designer_publish")),
            "block_sensitive_reporting_mcp": bool(
                row.get("block_sensitive_reporting_mcp")
                or (row.get("settings") or {}).get("block_sensitive_reporting_mcp", False)
            ),
            "allow_user_run_as_for_production": bool(
                row.get("allow_user_run_as_for_production")
                or (row.get("settings") or {}).get("allow_user_run_as_for_production", False)
            ),
            "require_service_principal_for_automated_triggers": bool(
                row.get("require_service_principal_for_automated_triggers")
                if row.get("require_service_principal_for_automated_triggers") is not None
                else (row.get("settings") or {}).get("require_service_principal_for_automated_triggers", True)
            ),
            "raw_payload_retention_days": int(row.get("raw_payload_retention_days") or 30),
            "raw_payload_retention_max_days": int(row.get("raw_payload_retention_max_days") or 90),
            "default_offer_timeout_minutes": int(row.get("default_offer_timeout_minutes") or 1440),
            "default_no_match_recipients": row.get("default_no_match_recipients") or [],
            "default_test_recipients": row.get("default_test_recipients") or [],
            "settings": row.get("settings") or {},
        }
