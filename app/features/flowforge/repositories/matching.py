from __future__ import annotations

from typing import Any, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.features.flowforge.repositories.common import json_or_none as _json_or_none, json_value as _json_value, lastrowid as _lastrowid


class FlowForgeMatchingRepository:
    _VERSION_JSON_KEYS = {
        "policy_json",
        "validation_result_json",
        "explanation_template_json",
    }
    _LLM_DRAFT_JSON_KEYS = {
        "generated_policy_json",
        "validation_result_json",
    }

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_policies(self, *, workspace_id: str) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_matching_policies
            WHERE workspace_id = :workspace_id
              AND archived_at IS NULL
            ORDER BY display_name ASC, id ASC
            """,
            {"workspace_id": str(workspace_id or "").strip()},
        )
        return [self._decode_policy(row) for row in rows]

    def get_policy(self, *, workspace_id: str, matching_policy_id: int) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_matching_policies
            WHERE workspace_id = :workspace_id
              AND id = :matching_policy_id
              AND archived_at IS NULL
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "matching_policy_id": int(matching_policy_id),
            },
        )
        if not rows:
            return None
        return self._decode_policy(rows[0])

    def archive_policy(self, *, workspace_id: str, matching_policy_id: int, updated_by: str | None) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_matching_policies
            SET archived_at = CURRENT_TIMESTAMP,
                updated_by = :updated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :matching_policy_id
              AND archived_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "matching_policy_id": int(matching_policy_id),
                "updated_by": updated_by,
            },
        )
        return int(updated or 0) > 0

    def create_policy(
        self,
        *,
        workspace_id: str,
        policy_key: str,
        display_name: str,
        description: str | None,
        resource_set_id: int,
        created_by: str | None,
        status: str = "draft",
    ) -> dict[str, Any]:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_matching_policies (
              workspace_id,
              policy_key,
              display_name,
              description,
              resource_set_id,
              status,
              created_by
            ) VALUES (
              :workspace_id,
              :policy_key,
              :display_name,
              :description,
              :resource_set_id,
              :status,
              :created_by
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "policy_key": str(policy_key or "").strip(),
                "display_name": str(display_name or "").strip(),
                "description": description,
                "resource_set_id": int(resource_set_id),
                "status": str(status or "draft").strip(),
                "created_by": created_by,
            },
        )
        return {
            "id": _lastrowid(result),
            "workspace_id": str(workspace_id or "").strip(),
            "policy_key": str(policy_key or "").strip(),
            "display_name": str(display_name or "").strip(),
            "description": description,
            "resource_set_id": int(resource_set_id),
            "status": str(status or "draft").strip(),
            "current_draft_version_id": None,
            "latest_published_version_id": None,
        }

    def list_policy_versions(self, *, workspace_id: str, matching_policy_id: int) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_matching_policy_versions
            WHERE workspace_id = :workspace_id
              AND matching_policy_id = :matching_policy_id
              AND version_status <> 'deleted'
            ORDER BY version_number DESC, id DESC
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "matching_policy_id": int(matching_policy_id),
            },
        )
        return [self._decode_policy_version(row) for row in rows]

    def get_policy_version(self, *, workspace_id: str, version_id: int) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_matching_policy_versions
            WHERE workspace_id = :workspace_id
              AND id = :version_id
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "version_id": int(version_id),
            },
        )
        if not rows:
            return None
        return self._decode_policy_version(rows[0])

    def create_policy_version(
        self,
        *,
        workspace_id: str,
        matching_policy_id: int,
        resource_set_id: int,
        version_number: int,
        policy: dict[str, Any],
        created_by: str | None,
        version_status: str = "draft",
        validation_status: str = "pending",
        validation_result: dict[str, Any] | None = None,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_matching_policy_versions (
              workspace_id,
              matching_policy_id,
              resource_set_id,
              version_number,
              version_status,
              policy_json,
              validation_status,
              validation_result_json,
              created_by
            ) VALUES (
              :workspace_id,
              :matching_policy_id,
              :resource_set_id,
              :version_number,
              :version_status,
              :policy_json,
              :validation_status,
              :validation_result_json,
              :created_by
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "matching_policy_id": int(matching_policy_id),
                "resource_set_id": int(resource_set_id),
                "version_number": int(version_number),
                "version_status": str(version_status or "draft").strip(),
                "policy_json": _json_or_none(policy),
                "validation_status": str(validation_status or "pending").strip(),
                "validation_result_json": _json_or_none(validation_result),
                "created_by": created_by,
            },
        )
        return _lastrowid(result)

    def delete_policy_version(
        self,
        *,
        workspace_id: str,
        matching_policy_id: int,
        matching_policy_version_id: int,
        updated_by: str | None,
    ) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_matching_policy_versions
            SET version_status = 'deleted'
            WHERE workspace_id = :workspace_id
              AND matching_policy_id = :matching_policy_id
              AND id = :matching_policy_version_id
              AND version_status <> 'published'
              AND version_status <> 'deleted'
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "matching_policy_id": int(matching_policy_id),
                "matching_policy_version_id": int(matching_policy_version_id),
            },
        )
        del updated_by
        return int(updated or 0) > 0

    def delete_non_published_policy_versions(self, *, workspace_id: str, matching_policy_id: int, updated_by: str | None) -> int:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_matching_policy_versions
            SET version_status = 'deleted'
            WHERE workspace_id = :workspace_id
              AND matching_policy_id = :matching_policy_id
              AND version_status <> 'published'
              AND version_status <> 'deleted'
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "matching_policy_id": int(matching_policy_id),
            },
        )
        del updated_by
        return int(updated or 0)

    def set_current_draft_version(
        self,
        *,
        workspace_id: str,
        matching_policy_id: int,
        matching_policy_version_id: int,
        updated_by: str | None,
    ) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_matching_policies
            SET current_draft_version_id = :matching_policy_version_id,
                updated_by = :updated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :matching_policy_id
              AND archived_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "matching_policy_id": int(matching_policy_id),
                "matching_policy_version_id": int(matching_policy_version_id),
                "updated_by": updated_by,
            },
        )
        return int(updated or 0) > 0

    def clear_current_draft_version(
        self,
        *,
        workspace_id: str,
        matching_policy_id: int,
        matching_policy_version_id: int,
        updated_by: str | None,
    ) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_matching_policies
            SET current_draft_version_id = NULL,
                updated_by = :updated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :matching_policy_id
              AND current_draft_version_id = :matching_policy_version_id
              AND archived_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "matching_policy_id": int(matching_policy_id),
                "matching_policy_version_id": int(matching_policy_version_id),
                "updated_by": updated_by,
            },
        )
        return int(updated or 0) > 0

    def list_llm_drafts(self, *, workspace_id: str, matching_policy_id: int) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_matching_policy_llm_drafts
            WHERE workspace_id = :workspace_id
              AND matching_policy_id = :matching_policy_id
            ORDER BY created_at DESC, id DESC
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "matching_policy_id": int(matching_policy_id),
            },
        )
        return [self._decode_llm_draft(row) for row in rows]

    def get_llm_draft(
        self,
        *,
        workspace_id: str,
        matching_policy_id: int,
        draft_id: int,
    ) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_matching_policy_llm_drafts
            WHERE workspace_id = :workspace_id
              AND matching_policy_id = :matching_policy_id
              AND id = :draft_id
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "matching_policy_id": int(matching_policy_id),
                "draft_id": int(draft_id),
            },
        )
        if not rows:
            return None
        return self._decode_llm_draft(rows[0])

    def create_llm_draft(
        self,
        *,
        workspace_id: str,
        matching_policy_id: int | None,
        resource_set_id: int,
        prompt: str,
        generated_policy: dict[str, Any] | None,
        plain_language_summary: str | None,
        validation_status: str,
        validation_result: dict[str, Any] | None,
        model_provider: str | None,
        model_name: str | None,
        status: str,
        created_by: str | None,
    ) -> dict[str, Any]:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_matching_policy_llm_drafts (
              workspace_id,
              matching_policy_id,
              resource_set_id,
              prompt,
              generated_policy_json,
              plain_language_summary,
              validation_status,
              validation_result_json,
              model_provider,
              model_name,
              status,
              created_by
            ) VALUES (
              :workspace_id,
              :matching_policy_id,
              :resource_set_id,
              :prompt,
              :generated_policy_json,
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
                "matching_policy_id": int(matching_policy_id) if matching_policy_id is not None else None,
                "resource_set_id": int(resource_set_id),
                "prompt": str(prompt or "").strip(),
                "generated_policy_json": _json_or_none(generated_policy),
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
            "matching_policy_id": int(matching_policy_id) if matching_policy_id is not None else None,
            "resource_set_id": int(resource_set_id),
            "prompt": str(prompt or "").strip(),
            "generated_policy_json": generated_policy or {},
            "plain_language_summary": plain_language_summary,
            "validation_status": str(validation_status or "pending").strip(),
            "validation_result_json": validation_result or {},
            "model_provider": model_provider,
            "model_name": model_name,
            "status": str(status or "drafted").strip(),
            "created_by": created_by,
        }

    def mark_llm_draft_reviewed(
        self,
        *,
        workspace_id: str,
        matching_policy_id: int,
        draft_id: int,
        status: str,
        reviewed_by: str | None,
    ) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_matching_policy_llm_drafts
            SET status = :status,
                reviewed_by = :reviewed_by,
                reviewed_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND matching_policy_id = :matching_policy_id
              AND id = :draft_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "matching_policy_id": int(matching_policy_id),
                "draft_id": int(draft_id),
                "status": str(status or "reviewed").strip(),
                "reviewed_by": reviewed_by,
            },
        )
        return int(updated or 0) > 0

    def _decode_policy(self, raw: dict[str, Any]) -> dict[str, Any]:
        return dict(raw)

    def _decode_policy_version(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        for key in self._VERSION_JSON_KEYS:
            row[key] = _json_value(row.get(key))
        return row

    def _decode_llm_draft(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        for key in self._LLM_DRAFT_JSON_KEYS:
            row[key] = _json_value(row.get(key))
        return row
