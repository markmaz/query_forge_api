from __future__ import annotations

import json
from typing import Any, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.features.flowforge.repositories.common import bool_value as _bool, json_value as _json_value


class FlowForgeSettingsRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_settings(self, *, workspace_id: str) -> dict[str, Any]:
        workspace = str(workspace_id or "").strip()
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_workspace_settings
            WHERE workspace_id = :workspace_id
            LIMIT 1
            """,
            {"workspace_id": workspace},
        )
        if not rows:
            return {
                "workspace_id": workspace,
                "enabled": False,
                "allow_designer_publish": False,
                "block_sensitive_reporting_mcp": False,
                "raw_payload_retention_days": 30,
                "raw_payload_retention_max_days": 90,
                "default_offer_timeout_minutes": 1440,
                "default_no_match_recipients": [],
                "default_test_recipients": [],
                "settings": {},
            }
        row = dict(rows[0])
        row["enabled"] = _bool(row.get("enabled"))
        row["allow_designer_publish"] = _bool(row.get("allow_designer_publish"))
        row["raw_payload_retention_days"] = int(row.get("raw_payload_retention_days") or 30)
        row["raw_payload_retention_max_days"] = int(row.get("raw_payload_retention_max_days") or 90)
        row["default_offer_timeout_minutes"] = int(row.get("default_offer_timeout_minutes") or 1440)
        row["default_no_match_recipients"] = _json_value(row.get("default_no_match_recipients_json")) or []
        row["default_test_recipients"] = _json_value(row.get("default_test_recipients_json")) or []
        row["settings"] = _json_value(row.get("settings_json")) or {}
        row["block_sensitive_reporting_mcp"] = _bool(row["settings"].get("block_sensitive_reporting_mcp"))
        return row

    def upsert_settings(self, *, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        workspace = str(workspace_id or "").strip()
        params = {
            "workspace_id": workspace,
            "enabled": 1 if payload.get("enabled") else 0,
            "allow_designer_publish": 1 if payload.get("allow_designer_publish") else 0,
            "raw_payload_retention_days": int(payload.get("raw_payload_retention_days") or 30),
            "raw_payload_retention_max_days": int(payload.get("raw_payload_retention_max_days") or 90),
            "default_offer_timeout_minutes": int(payload.get("default_offer_timeout_minutes") or 1440),
            "default_no_match_recipients_json": json.dumps(payload.get("default_no_match_recipients") or []),
            "default_test_recipients_json": json.dumps(payload.get("default_test_recipients") or []),
            "settings_json": json.dumps(payload.get("settings") or {}),
        }
        self._sql.execute_write(
            """
            INSERT INTO flowforge_workspace_settings (
              workspace_id,
              enabled,
              allow_designer_publish,
              raw_payload_retention_days,
              raw_payload_retention_max_days,
              default_offer_timeout_minutes,
              default_no_match_recipients_json,
              default_test_recipients_json,
              settings_json
            )
            VALUES (
              :workspace_id,
              :enabled,
              :allow_designer_publish,
              :raw_payload_retention_days,
              :raw_payload_retention_max_days,
              :default_offer_timeout_minutes,
              :default_no_match_recipients_json,
              :default_test_recipients_json,
              :settings_json
            )
            ON DUPLICATE KEY UPDATE
              enabled = VALUES(enabled),
              allow_designer_publish = VALUES(allow_designer_publish),
              raw_payload_retention_days = VALUES(raw_payload_retention_days),
              default_offer_timeout_minutes = VALUES(default_offer_timeout_minutes),
              default_no_match_recipients_json = VALUES(default_no_match_recipients_json),
              default_test_recipients_json = VALUES(default_test_recipients_json),
              settings_json = VALUES(settings_json),
              updated_at = CURRENT_TIMESTAMP
            """,
            params,
        )
        return self.get_settings(workspace_id=workspace)
