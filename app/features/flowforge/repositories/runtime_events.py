from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories.common import json_or_none as _json_or_none, json_value as _json_value, lastrowid as _lastrowid


class FlowForgeRuntimeEventRepositoryMixin:
    def get_run_event_by_idempotency(self, *, workspace_id: str, idempotency_key: str) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_run_events
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
        return self._decode_run_event(rows[0])

    def list_run_events(self, *, workspace_id: str, run_id: int, limit: int) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_run_events
            WHERE workspace_id = :workspace_id
              AND run_id = :run_id
            ORDER BY created_at ASC, id ASC
            LIMIT :limit
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id),
                "limit": int(limit),
            },
        )
        return [self._decode_run_event(row) for row in rows]

    def append_run_event(
        self,
        *,
        workspace_id: str,
        run_id: int,
        event_type: str,
        node_id: str | None,
        message: str | None,
        event_payload: dict[str, Any] | None,
        actor_type: str | None,
        actor_id: str | None,
        idempotency_key: str | None,
        sensitive_payload: dict[str, Any] | None = None,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_run_events (
              workspace_id,
              run_id,
              event_type,
              node_id,
              message,
              event_payload_json,
              sensitive_payload_json,
              actor_type,
              actor_id,
              idempotency_key
            ) VALUES (
              :workspace_id,
              :run_id,
              :event_type,
              :node_id,
              :message,
              :event_payload_json,
              :sensitive_payload_json,
              :actor_type,
              :actor_id,
              :idempotency_key
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id),
                "event_type": str(event_type or "").strip(),
                "node_id": node_id,
                "message": message,
                "event_payload_json": _json_or_none(event_payload),
                "sensitive_payload_json": _json_or_none(sensitive_payload),
                "actor_type": actor_type,
                "actor_id": actor_id,
                "idempotency_key": idempotency_key,
            },
        )
        return _lastrowid(result)

    def _decode_run_event(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        row["event_payload_json"] = _json_value(row.get("event_payload_json")) or {}
        row["sensitive_payload_json"] = _json_value(row.get("sensitive_payload_json")) or {}
        return row
