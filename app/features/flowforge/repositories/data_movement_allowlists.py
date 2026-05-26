from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories.common import json_or_none as _json_or_none


class FlowForgeDataMovementAllowlistRepositoryMixin:
    def upsert_data_source(
        self,
        *,
        workspace_id: str,
        source_key: str,
        display_name: str,
        source_type: str,
        enabled: bool,
        mode: str,
        config: dict[str, Any] | None,
        actor_user_id: str | None,
    ) -> dict[str, Any]:
        self._sql.execute_write(
            """
            INSERT INTO flowforge_data_sources (
              workspace_id,
              source_key,
              display_name,
              source_type,
              enabled,
              mode,
              config_json,
              created_by,
              updated_by
            ) VALUES (
              :workspace_id,
              :source_key,
              :display_name,
              :source_type,
              :enabled,
              :mode,
              :config_json,
              :actor_user_id,
              :actor_user_id
            )
            ON DUPLICATE KEY UPDATE
              display_name = VALUES(display_name),
              source_type = VALUES(source_type),
              enabled = VALUES(enabled),
              mode = VALUES(mode),
              config_json = VALUES(config_json),
              updated_by = VALUES(updated_by),
              updated_at = CURRENT_TIMESTAMP,
              archived_at = NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "source_key": str(source_key or "").strip(),
                "display_name": str(display_name or "").strip(),
                "source_type": str(source_type or "").strip(),
                "enabled": 1 if enabled else 0,
                "mode": str(mode or "test").strip(),
                "config_json": _json_or_none(config),
                "actor_user_id": actor_user_id,
            },
        )
        return self.get_data_source_by_key(workspace_id=workspace_id, source_key=source_key) or {
            "workspace_id": str(workspace_id or "").strip(),
            "source_key": str(source_key or "").strip(),
            "display_name": str(display_name or "").strip(),
            "source_type": str(source_type or "").strip(),
            "enabled": enabled,
            "mode": str(mode or "test").strip(),
            "config_json": config or {},
        }

    def list_data_sources(self, *, workspace_id: str) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_data_sources
            WHERE workspace_id = :workspace_id
              AND archived_at IS NULL
            ORDER BY display_name ASC, source_key ASC
            """,
            {"workspace_id": str(workspace_id or "").strip()},
        )
        return [self._decode_allowlist(row) for row in rows]

    def get_data_source_by_key(self, *, workspace_id: str, source_key: str) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_data_sources
            WHERE workspace_id = :workspace_id
              AND source_key = :source_key
              AND archived_at IS NULL
            LIMIT 1
            """,
            {"workspace_id": str(workspace_id or "").strip(), "source_key": str(source_key or "").strip()},
        )
        if not rows:
            return None
        return self._decode_allowlist(rows[0])

    def update_data_source_enabled(self, *, workspace_id: str, source_key: str, enabled: bool, updated_by: str | None) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_data_sources
            SET enabled = :enabled,
                updated_by = :updated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND source_key = :source_key
              AND archived_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "source_key": str(source_key or "").strip(),
                "enabled": 1 if enabled else 0,
                "updated_by": updated_by,
            },
        )
        return bool(updated)

    def upsert_data_destination(
        self,
        *,
        workspace_id: str,
        destination_key: str,
        display_name: str,
        destination_type: str,
        enabled: bool,
        mode: str,
        config: dict[str, Any] | None,
        actor_user_id: str | None,
    ) -> dict[str, Any]:
        self._sql.execute_write(
            """
            INSERT INTO flowforge_data_destinations (
              workspace_id,
              destination_key,
              display_name,
              destination_type,
              enabled,
              mode,
              config_json,
              created_by,
              updated_by
            ) VALUES (
              :workspace_id,
              :destination_key,
              :display_name,
              :destination_type,
              :enabled,
              :mode,
              :config_json,
              :actor_user_id,
              :actor_user_id
            )
            ON DUPLICATE KEY UPDATE
              display_name = VALUES(display_name),
              destination_type = VALUES(destination_type),
              enabled = VALUES(enabled),
              mode = VALUES(mode),
              config_json = VALUES(config_json),
              updated_by = VALUES(updated_by),
              updated_at = CURRENT_TIMESTAMP,
              archived_at = NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "destination_key": str(destination_key or "").strip(),
                "display_name": str(display_name or "").strip(),
                "destination_type": str(destination_type or "").strip(),
                "enabled": 1 if enabled else 0,
                "mode": str(mode or "test").strip(),
                "config_json": _json_or_none(config),
                "actor_user_id": actor_user_id,
            },
        )
        return self.get_data_destination_by_key(workspace_id=workspace_id, destination_key=destination_key) or {
            "workspace_id": str(workspace_id or "").strip(),
            "destination_key": str(destination_key or "").strip(),
            "display_name": str(display_name or "").strip(),
            "destination_type": str(destination_type or "").strip(),
            "enabled": enabled,
            "mode": str(mode or "test").strip(),
            "config_json": config or {},
        }

    def list_data_destinations(self, *, workspace_id: str) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_data_destinations
            WHERE workspace_id = :workspace_id
              AND archived_at IS NULL
            ORDER BY display_name ASC, destination_key ASC
            """,
            {"workspace_id": str(workspace_id or "").strip()},
        )
        return [self._decode_allowlist(row) for row in rows]

    def get_data_destination_by_key(self, *, workspace_id: str, destination_key: str) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_data_destinations
            WHERE workspace_id = :workspace_id
              AND destination_key = :destination_key
              AND archived_at IS NULL
            LIMIT 1
            """,
            {"workspace_id": str(workspace_id or "").strip(), "destination_key": str(destination_key or "").strip()},
        )
        if not rows:
            return None
        return self._decode_allowlist(rows[0])

    def update_data_destination_enabled(
        self,
        *,
        workspace_id: str,
        destination_key: str,
        enabled: bool,
        updated_by: str | None,
    ) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_data_destinations
            SET enabled = :enabled,
                updated_by = :updated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND destination_key = :destination_key
              AND archived_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "destination_key": str(destination_key or "").strip(),
                "enabled": 1 if enabled else 0,
                "updated_by": updated_by,
            },
        )
        return bool(updated)
