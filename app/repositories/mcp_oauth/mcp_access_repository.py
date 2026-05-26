from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _json_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class WorkspaceMCPSettingsRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_settings(self, *, workspace_id: str) -> Dict[str, Any]:
        workspace = str(workspace_id or "").strip()
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM workspace_mcp_settings
            WHERE workspace_id = :workspace_id
            LIMIT 1
            """,
            {"workspace_id": workspace},
        )
        if not rows:
            return {
                "workspace_id": workspace,
                "enabled": False,
                "default_preview_row_limit": 100,
                "max_preview_row_limit": 500,
                "block_sensitive_domains": False,
            }
        row = dict(rows[0])
        row["enabled"] = _bool(row.get("enabled"))
        row["block_sensitive_domains"] = _bool(row.get("block_sensitive_domains"))
        row["default_preview_row_limit"] = int(row.get("default_preview_row_limit") or 100)
        row["max_preview_row_limit"] = int(row.get("max_preview_row_limit") or 500)
        return row

    def set_enabled(self, *, workspace_id: str, enabled: bool, actor_user_id: str) -> Dict[str, Any]:
        workspace = str(workspace_id or "").strip()
        actor = str(actor_user_id or "").strip() or None
        enabled_int = 1 if enabled else 0
        self._sql.execute_write(
            """
            INSERT INTO workspace_mcp_settings (
              workspace_id,
              enabled,
              enabled_by,
              enabled_at,
              disabled_by,
              disabled_at
            )
            VALUES (
              :workspace_id,
              :enabled,
              :enabled_by,
              CASE WHEN :enabled = 1 THEN CURRENT_TIMESTAMP ELSE NULL END,
              :disabled_by,
              CASE WHEN :enabled = 0 THEN CURRENT_TIMESTAMP ELSE NULL END
            )
            ON DUPLICATE KEY UPDATE
              enabled = VALUES(enabled),
              enabled_by = CASE WHEN VALUES(enabled) = 1 THEN VALUES(enabled_by) ELSE enabled_by END,
              enabled_at = CASE WHEN VALUES(enabled) = 1 THEN CURRENT_TIMESTAMP ELSE enabled_at END,
              disabled_by = CASE WHEN VALUES(enabled) = 0 THEN VALUES(disabled_by) ELSE disabled_by END,
              disabled_at = CASE WHEN VALUES(enabled) = 0 THEN CURRENT_TIMESTAMP ELSE disabled_at END,
              updated_at = CURRENT_TIMESTAMP
            """,
            {
                "workspace_id": workspace,
                "enabled": enabled_int,
                "enabled_by": actor if enabled else None,
                "disabled_by": actor if not enabled else None,
            },
        )
        return self.get_settings(workspace_id=workspace)


class MCPPrincipalGrantRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_active_grant(
        self,
        *,
        principal_type: str,
        principal_id: str,
        workspace_id: str,
        now: datetime,
    ) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM mcp_principal_grants
            WHERE principal_type = :principal_type
              AND principal_id = :principal_id
              AND workspace_id = :workspace_id
              AND enabled = 1
              AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > :now)
            LIMIT 1
            """,
            {
                "principal_type": str(principal_type or "").strip(),
                "principal_id": str(principal_id or "").strip(),
                "workspace_id": str(workspace_id or "").strip(),
                "now": now,
            },
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["allowed_tools"] = _json_value(row.get("allowed_tools")) or []
        row["allowed_domain_keys"] = _json_value(row.get("allowed_domain_keys")) or []
        row["can_preview"] = _bool(row.get("can_preview"))
        row["enabled"] = _bool(row.get("enabled"))
        row["preview_row_limit"] = int(row.get("preview_row_limit") or 100)
        return row

    def upsert_app_grant(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        enabled: bool,
        allowed_tools: Optional[list[str]],
        allowed_domain_keys: Optional[list[str]],
        can_preview: bool,
        preview_row_limit: int,
        created_by: str,
        expires_at: Optional[str],
    ) -> Dict[str, Any]:
        principal = str(principal_id or "").strip()
        workspace = str(workspace_id or "").strip()
        self._sql.execute_write(
            """
            INSERT INTO mcp_principal_grants (
              principal_type,
              principal_id,
              workspace_id,
              enabled,
              allowed_tools,
              allowed_domain_keys,
              can_preview,
              preview_row_limit,
              created_by,
              expires_at
            ) VALUES (
              'app',
              :principal_id,
              :workspace_id,
              :enabled,
              :allowed_tools,
              :allowed_domain_keys,
              :can_preview,
              :preview_row_limit,
              :created_by,
              :expires_at
            )
            ON DUPLICATE KEY UPDATE
              enabled = VALUES(enabled),
              allowed_tools = VALUES(allowed_tools),
              allowed_domain_keys = VALUES(allowed_domain_keys),
              can_preview = VALUES(can_preview),
              preview_row_limit = VALUES(preview_row_limit),
              expires_at = VALUES(expires_at),
              revoked_at = NULL,
              updated_at = CURRENT_TIMESTAMP
            """,
            {
                "principal_id": principal,
                "workspace_id": workspace,
                "enabled": 1 if enabled else 0,
                "allowed_tools": _json_or_none(allowed_tools),
                "allowed_domain_keys": _json_or_none(allowed_domain_keys),
                "can_preview": 1 if can_preview else 0,
                "preview_row_limit": int(preview_row_limit),
                "created_by": str(created_by or "").strip() or None,
                "expires_at": expires_at,
            },
        )
        row = self.get_app_grant(principal_id=principal, workspace_id=workspace)
        return row or {}

    def get_app_grant(self, *, principal_id: str, workspace_id: str) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM mcp_principal_grants
            WHERE principal_type = 'app'
              AND principal_id = :principal_id
              AND workspace_id = :workspace_id
            LIMIT 1
            """,
            {
                "principal_id": str(principal_id or "").strip(),
                "workspace_id": str(workspace_id or "").strip(),
            },
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["allowed_tools"] = _json_value(row.get("allowed_tools")) or []
        row["allowed_domain_keys"] = _json_value(row.get("allowed_domain_keys")) or []
        row["can_preview"] = _bool(row.get("can_preview"))
        row["enabled"] = _bool(row.get("enabled"))
        row["preview_row_limit"] = int(row.get("preview_row_limit") or 100)
        return row

    def revoke_app_grant(self, *, principal_id: str, workspace_id: str) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE mcp_principal_grants
            SET enabled = 0,
                revoked_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE principal_type = 'app'
              AND principal_id = :principal_id
              AND workspace_id = :workspace_id
              AND revoked_at IS NULL
            """,
            {
                "principal_id": str(principal_id or "").strip(),
                "workspace_id": str(workspace_id or "").strip(),
            },
        )
        return int(updated or 0) > 0


class MCPAppClientRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_active_client(self, *, client_id: str, now: datetime) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM mcp_app_clients
            WHERE client_id = :client_id
              AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > :now)
              AND (rotation_required_at IS NULL OR rotation_required_at > :now)
            LIMIT 1
            """,
            {
                "client_id": str(client_id or "").strip(),
                "now": now,
            },
        )
        if not rows:
            return None
        return dict(rows[0])

    def touch_last_used(self, *, client_id: str, now: datetime) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE mcp_app_clients
            SET last_used_at = :now
            WHERE client_id = :client_id
              AND revoked_at IS NULL
            """,
            {
                "client_id": str(client_id or "").strip(),
                "now": now,
            },
        )
        return int(updated or 0) > 0

    def list_workspace_clients(self, *, workspace_id: str) -> list[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              c.client_id,
              c.display_name,
              c.description,
              c.owning_workspace_id,
              c.owner_user_id,
              c.created_by,
              c.created_at,
              c.last_used_at,
              c.expires_at,
              c.revoked_at,
              c.rotation_required_at,
              g.enabled AS grant_enabled,
              g.allowed_tools,
              g.allowed_domain_keys,
              g.can_preview,
              g.preview_row_limit,
              g.expires_at AS grant_expires_at,
              g.revoked_at AS grant_revoked_at,
              g.updated_at AS grant_updated_at
            FROM mcp_app_clients c
            LEFT JOIN mcp_principal_grants g
              ON g.principal_type = 'app'
             AND g.principal_id = c.client_id
             AND g.workspace_id = :workspace_id
            WHERE c.owning_workspace_id = :workspace_id
            ORDER BY c.created_at DESC, c.client_id ASC
            """,
            {"workspace_id": str(workspace_id or "").strip()},
        )
        result: list[Dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            row["allowed_tools"] = _json_value(row.get("allowed_tools")) or []
            row["allowed_domain_keys"] = _json_value(row.get("allowed_domain_keys")) or []
            row["grant_enabled"] = _bool(row.get("grant_enabled"))
            row["can_preview"] = _bool(row.get("can_preview"))
            row["preview_row_limit"] = int(row.get("preview_row_limit") or 100)
            result.append(row)
        return result

    def create_client(self, *, payload: Dict[str, Any]) -> None:
        self._sql.execute_insert(
            """
            INSERT INTO mcp_app_clients (
              client_id,
              client_secret_hash,
              display_name,
              description,
              owning_workspace_id,
              owner_user_id,
              created_by,
              expires_at
            ) VALUES (
              :client_id,
              :client_secret_hash,
              :display_name,
              :description,
              :owning_workspace_id,
              :owner_user_id,
              :created_by,
              :expires_at
            )
            """,
            payload,
        )

    def get_client(self, *, client_id: str, workspace_id: str) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM mcp_app_clients
            WHERE client_id = :client_id
              AND owning_workspace_id = :workspace_id
            LIMIT 1
            """,
            {
                "client_id": str(client_id or "").strip(),
                "workspace_id": str(workspace_id or "").strip(),
            },
        )
        if not rows:
            return None
        return dict(rows[0])

    def revoke_client(self, *, client_id: str, workspace_id: str) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE mcp_app_clients
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE client_id = :client_id
              AND owning_workspace_id = :workspace_id
              AND revoked_at IS NULL
            """,
            {
                "client_id": str(client_id or "").strip(),
                "workspace_id": str(workspace_id or "").strip(),
            },
        )
        return int(updated or 0) > 0


__all__ = ["MCPAppClientRepository", "MCPPrincipalGrantRepository", "WorkspaceMCPSettingsRepository"]
