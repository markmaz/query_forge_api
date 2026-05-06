from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories.common import json_or_none as _json_or_none, json_value as _json_value, lastrowid as _lastrowid


class FlowForgeRuntimeSignedActionRepositoryMixin:
    def create_signed_action_token(
        self,
        *,
        workspace_id: str,
        human_task_id: int,
        token_hash: str,
        allowed_actions: list[str],
        expires_at: Any,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_signed_action_tokens (
              workspace_id,
              human_task_id,
              token_hash,
              allowed_actions_json,
              expires_at
            ) VALUES (
              :workspace_id,
              :human_task_id,
              :token_hash,
              :allowed_actions_json,
              :expires_at
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "human_task_id": int(human_task_id),
                "token_hash": str(token_hash or "").strip(),
                "allowed_actions_json": _json_or_none(allowed_actions),
                "expires_at": expires_at,
            },
        )
        return _lastrowid(result)

    def get_signed_action_token(self, *, token_hash: str) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              sat.*,
              ht.task_type,
              ht.run_id,
              ht.status AS task_status,
              ht.resource_set_id,
              ht.source_record_key,
              ht.response_json
            FROM flowforge_signed_action_tokens sat
            JOIN flowforge_human_tasks ht
              ON ht.workspace_id = sat.workspace_id
             AND ht.id = sat.human_task_id
            WHERE sat.token_hash = :token_hash
            LIMIT 1
            """,
            {"token_hash": str(token_hash or "").strip()},
        )
        if not rows:
            return None
        return self._decode_signed_action_token(rows[0])

    def mark_signed_action_token_used(self, *, token_hash: str, used_action: str, used_ip: str | None) -> bool:
        count = self._sql.execute_write(
            """
            UPDATE flowforge_signed_action_tokens
            SET used_at = CURRENT_TIMESTAMP,
                used_action = :used_action,
                used_ip = :used_ip
            WHERE token_hash = :token_hash
              AND used_at IS NULL
              AND revoked_at IS NULL
            """,
            {
                "token_hash": str(token_hash or "").strip(),
                "used_action": str(used_action or "").strip(),
                "used_ip": used_ip,
            },
        )
        return bool(count)

    def _decode_signed_action_token(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        row["allowed_actions_json"] = _json_value(row.get("allowed_actions_json")) or []
        row["response_json"] = _json_value(row.get("response_json")) or {}
        return row
