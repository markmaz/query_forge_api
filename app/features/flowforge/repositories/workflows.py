from __future__ import annotations

from typing import Any, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.features.flowforge.repositories.common import json_or_none as _json_or_none, json_value as _json_value, lastrowid as _lastrowid


class FlowForgeWorkflowRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def create_workflow_definition(
        self,
        *,
        workspace_id: str,
        workflow_key: str,
        name: str,
        description: str | None,
        created_by: str | None,
        owner_user_id: str | None = None,
        run_as_principal_type: str | None = None,
        run_as_principal_id: str | None = None,
        lifecycle: str = "development",
    ) -> int:
        owner = str(owner_user_id or created_by or "").strip() or None
        run_as_id = str(run_as_principal_id or owner or "").strip() or None
        run_as_type = str(run_as_principal_type or ("user" if run_as_id else "")).strip() or None
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_workflow_definitions (
              workspace_id,
              workflow_key,
              name,
              description,
              owner_user_id,
              run_as_principal_type,
              run_as_principal_id,
              lifecycle,
              created_by
            ) VALUES (
              :workspace_id,
              :workflow_key,
              :name,
              :description,
              :owner_user_id,
              :run_as_principal_type,
              :run_as_principal_id,
              :lifecycle,
              :created_by
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_key": str(workflow_key or "").strip(),
                "name": str(name or "").strip(),
                "description": description,
                "owner_user_id": owner,
                "run_as_principal_type": run_as_type,
                "run_as_principal_id": run_as_id,
                "lifecycle": str(lifecycle or "development").strip() or "development",
                "created_by": created_by,
            },
        )
        return _lastrowid(result)

    def update_workflow_owner(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        owner_user_id: str,
        updated_by: str | None,
    ) -> bool:
        count = self._sql.execute_write(
            """
            UPDATE flowforge_workflow_definitions
            SET owner_user_id = :owner_user_id,
                updated_by = :updated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :workflow_definition_id
              AND archived_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "owner_user_id": str(owner_user_id or "").strip(),
                "updated_by": updated_by,
            },
        )
        return bool(count)

    def update_workflow_metadata(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        name: str,
        description: str | None,
        updated_by: str | None,
    ) -> bool:
        count = self._sql.execute_write(
            """
            UPDATE flowforge_workflow_definitions
            SET name = :name,
                description = :description,
                updated_by = :updated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :workflow_definition_id
              AND archived_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "name": str(name or "").strip(),
                "description": description,
                "updated_by": updated_by,
            },
        )
        return bool(count)

    def update_workflow_run_as(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        principal_type: str,
        principal_id: str,
        updated_by: str | None,
    ) -> bool:
        count = self._sql.execute_write(
            """
            UPDATE flowforge_workflow_definitions
            SET run_as_principal_type = :principal_type,
                run_as_principal_id = :principal_id,
                updated_by = :updated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :workflow_definition_id
              AND archived_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "principal_type": str(principal_type or "").strip(),
                "principal_id": str(principal_id or "").strip(),
                "updated_by": updated_by,
            },
        )
        return bool(count)

    def list_workflow_acl(self, *, workspace_id: str, workflow_definition_id: int) -> list[dict[str, Any]]:
        return self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_workflow_acl
            WHERE workspace_id = :workspace_id
              AND workflow_definition_id = :workflow_definition_id
              AND revoked_at IS NULL
            ORDER BY permission DESC, principal_type ASC, principal_id ASC
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
            },
        )

    def grant_workflow_permission(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        principal_type: str,
        principal_id: str,
        permission: str,
        granted_by: str | None,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_workflow_acl (
              workspace_id,
              workflow_definition_id,
              principal_type,
              principal_id,
              permission,
              granted_by
            ) VALUES (
              :workspace_id,
              :workflow_definition_id,
              :principal_type,
              :principal_id,
              :permission,
              :granted_by
            )
            ON DUPLICATE KEY UPDATE
              permission = VALUES(permission),
              granted_by = VALUES(granted_by),
              granted_at = CURRENT_TIMESTAMP,
              revoked_by = NULL,
              revoked_at = NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "principal_type": str(principal_type or "").strip(),
                "principal_id": str(principal_id or "").strip(),
                "permission": str(permission or "").strip(),
                "granted_by": granted_by,
            },
        )
        return _lastrowid(result)

    def revoke_workflow_permission(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        principal_type: str,
        principal_id: str,
        revoked_by: str | None,
    ) -> bool:
        count = self._sql.execute_write(
            """
            UPDATE flowforge_workflow_acl
            SET revoked_by = :revoked_by,
                revoked_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND workflow_definition_id = :workflow_definition_id
              AND principal_type = :principal_type
              AND principal_id = :principal_id
              AND revoked_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "principal_type": str(principal_type or "").strip(),
                "principal_id": str(principal_id or "").strip(),
                "revoked_by": revoked_by,
            },
        )
        return bool(count)

    def list_workflow_definitions(self, *, workspace_id: str) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.*,
              v.graph_json,
              v.validation_status,
              v.validation_result_json,
              COALESCE(
                NULLIF(TRIM(CONCAT_WS(' ', owner_user.first_name, owner_user.last_name)), ''),
                NULLIF(owner_user.email, ''),
                NULLIF(owner_user.username, '')
              ) AS owner_display_name,
              COALESCE(
                NULLIF(TRIM(CONCAT_WS(' ', run_as_user.first_name, run_as_user.last_name)), ''),
                NULLIF(run_as_user.email, ''),
                NULLIF(run_as_user.username, '')
              ) AS run_as_user_display_name
            FROM flowforge_workflow_definitions d
            LEFT JOIN flowforge_workflow_versions v
              ON v.id = COALESCE(d.current_draft_version_id, d.latest_published_version_id)
             AND v.workspace_id = d.workspace_id
            LEFT JOIN users owner_user
              ON owner_user.user_id COLLATE utf8mb4_unicode_ci =
                 d.owner_user_id COLLATE utf8mb4_unicode_ci
            LEFT JOIN users run_as_user
              ON d.run_as_principal_type = 'user'
             AND run_as_user.user_id COLLATE utf8mb4_unicode_ci =
                 d.run_as_principal_id COLLATE utf8mb4_unicode_ci
            WHERE d.workspace_id = :workspace_id
              AND d.archived_at IS NULL
            ORDER BY d.updated_at DESC, d.id DESC
            """,
            {"workspace_id": str(workspace_id or "").strip()},
        )
        return [self._decode_workflow_definition(row) for row in rows]

    def get_workflow_definition(self, *, workspace_id: str, workflow_definition_id: int) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.*,
              v.graph_json,
              v.validation_status,
              v.validation_result_json,
              COALESCE(
                NULLIF(TRIM(CONCAT_WS(' ', owner_user.first_name, owner_user.last_name)), ''),
                NULLIF(owner_user.email, ''),
                NULLIF(owner_user.username, '')
              ) AS owner_display_name,
              COALESCE(
                NULLIF(TRIM(CONCAT_WS(' ', run_as_user.first_name, run_as_user.last_name)), ''),
                NULLIF(run_as_user.email, ''),
                NULLIF(run_as_user.username, '')
              ) AS run_as_user_display_name
            FROM flowforge_workflow_definitions d
            LEFT JOIN flowforge_workflow_versions v
              ON v.id = COALESCE(d.current_draft_version_id, d.latest_published_version_id)
             AND v.workspace_id = d.workspace_id
            LEFT JOIN users owner_user
              ON owner_user.user_id COLLATE utf8mb4_unicode_ci =
                 d.owner_user_id COLLATE utf8mb4_unicode_ci
            LEFT JOIN users run_as_user
              ON d.run_as_principal_type = 'user'
             AND run_as_user.user_id COLLATE utf8mb4_unicode_ci =
                 d.run_as_principal_id COLLATE utf8mb4_unicode_ci
            WHERE d.workspace_id = :workspace_id
              AND d.id = :workflow_definition_id
              AND d.archived_at IS NULL
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
            },
        )
        if not rows:
            return None
        return self._decode_workflow_definition(rows[0])

    def get_user_display_name(self, *, user_id: str) -> str | None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return None
        rows = self._sql.execute_query_mappings(
            """
            SELECT COALESCE(
              NULLIF(TRIM(CONCAT_WS(' ', first_name, last_name)), ''),
              NULLIF(email, ''),
              NULLIF(username, '')
            ) AS display_name
            FROM users
            WHERE user_id = :user_id
            LIMIT 1
            """,
            {"user_id": normalized_user_id},
        )
        if not rows:
            return None
        return str(rows[0].get("display_name") or "").strip() or None

    def create_workflow_version(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        version_number: int,
        graph: dict[str, Any],
        created_by: str | None,
        version_status: str = "draft",
        validation_status: str = "pending",
        validation_result: dict[str, Any] | None = None,
        matching_policy_refs: list[dict[str, Any]] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_workflow_versions (
              workspace_id,
              workflow_definition_id,
              version_number,
              version_status,
              graph_json,
              validation_status,
              validation_result_json,
              matching_policy_refs_json,
              settings_json,
              created_by
            ) VALUES (
              :workspace_id,
              :workflow_definition_id,
              :version_number,
              :version_status,
              :graph_json,
              :validation_status,
              :validation_result_json,
              :matching_policy_refs_json,
              :settings_json,
              :created_by
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "version_number": int(version_number),
                "version_status": str(version_status or "draft").strip(),
                "graph_json": _json_or_none(graph),
                "validation_status": str(validation_status or "pending").strip(),
                "validation_result_json": _json_or_none(validation_result),
                "matching_policy_refs_json": _json_or_none(matching_policy_refs),
                "settings_json": _json_or_none(settings),
                "created_by": created_by,
            },
        )
        return _lastrowid(result)

    def set_current_draft_version(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        version_id: int,
        updated_by: str | None,
    ) -> bool:
        count = self._sql.execute_write(
            """
            UPDATE flowforge_workflow_definitions
            SET current_draft_version_id = :version_id,
                updated_by = :updated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :workflow_definition_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "version_id": int(version_id),
                "updated_by": updated_by,
            },
        )
        return bool(count)

    def archive_workflow_definition(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        archived_by: str | None,
    ) -> bool:
        count = self._sql.execute_write(
            """
            UPDATE flowforge_workflow_definitions
            SET archived_at = CURRENT_TIMESTAMP,
                archived_by = :archived_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :workflow_definition_id
              AND archived_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "archived_by": archived_by,
            },
        )
        return bool(count)

    def list_workflow_versions(self, *, workspace_id: str, workflow_definition_id: int) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_workflow_versions
            WHERE workspace_id = :workspace_id
              AND workflow_definition_id = :workflow_definition_id
              AND archived_at IS NULL
            ORDER BY version_number DESC, id DESC
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
            },
        )
        return [self._decode_workflow_version(row) for row in rows]

    def get_workflow_version(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        version_id: int,
    ) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_workflow_versions
            WHERE workspace_id = :workspace_id
              AND workflow_definition_id = :workflow_definition_id
              AND id = :version_id
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "version_id": int(version_id),
            },
        )
        if not rows:
            return None
        return self._decode_workflow_version(rows[0])

    def publish_workflow_version(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        version_id: int,
        published_by: str | None,
    ) -> bool:
        version_count = self._sql.execute_write(
            """
            UPDATE flowforge_workflow_versions
            SET version_status = 'published',
                published_by = :published_by,
                published_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND workflow_definition_id = :workflow_definition_id
              AND id = :version_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "version_id": int(version_id),
                "published_by": published_by,
            },
        )
        definition_count = self._sql.execute_write(
            """
            UPDATE flowforge_workflow_definitions
            SET status = 'published',
                latest_published_version_id = :version_id
            WHERE workspace_id = :workspace_id
              AND id = :workflow_definition_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "version_id": int(version_id),
            },
        )
        return bool(version_count and definition_count)

    def list_published_schedule_workflow_versions(self, *, limit: int) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.workspace_id,
              d.id AS workflow_definition_id,
              d.workflow_key,
              d.name,
              d.run_as_principal_type,
              d.run_as_principal_id,
              d.lifecycle,
              v.id AS workflow_version_id,
              v.version_number,
              v.graph_json,
              v.settings_json,
              v.created_at,
              v.published_at
            FROM flowforge_workflow_definitions d
            INNER JOIN flowforge_workflow_versions v
              ON v.workspace_id = d.workspace_id
             AND v.id = d.latest_published_version_id
             AND v.workflow_definition_id = d.id
            WHERE d.status = 'published'
              AND d.archived_at IS NULL
              AND v.version_status = 'published'
              AND v.archived_at IS NULL
              AND v.graph_json LIKE '%schedule_trigger%'
            ORDER BY v.published_at ASC, v.id ASC
            LIMIT :limit
            """,
            {"limit": int(limit)},
        )
        return [self._decode_workflow_version(row) for row in rows]

    def _decode_workflow_version(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        row["graph_json"] = _json_value(row.get("graph_json")) or {}
        row["validation_result_json"] = _json_value(row.get("validation_result_json")) or {}
        row["matching_policy_refs_json"] = _json_value(row.get("matching_policy_refs_json")) or []
        row["settings_json"] = _json_value(row.get("settings_json")) or {}
        return row

    def _decode_workflow_definition(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        row["graph_json"] = _json_value(row.get("graph_json")) or {"nodes": [], "edges": []}
        row["validation_result_json"] = _json_value(row.get("validation_result_json")) or {}
        return row
