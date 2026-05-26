from __future__ import annotations

from datetime import datetime
from typing import Any

from app.features.flowforge.repositories.common import json_or_none as _json_or_none, lastrowid as _lastrowid


class FlowForgeDataMovementScheduleRepositoryMixin:
    def create_schedule_run(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        workflow_version_id: int | None,
        trigger_node_id: str,
        schedule_key: str,
        scheduled_for: datetime | str,
        window_start: datetime | str,
        window_end: datetime | str | None,
        status: str,
        run_id: int | None,
        idempotency_key: str,
        trigger_payload: dict[str, Any] | None,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_schedule_runs (
              workspace_id,
              workflow_definition_id,
              workflow_version_id,
              trigger_node_id,
              schedule_key,
              scheduled_for,
              window_start,
              window_end,
              status,
              run_id,
              idempotency_key,
              trigger_payload_json
            ) VALUES (
              :workspace_id,
              :workflow_definition_id,
              :workflow_version_id,
              :trigger_node_id,
              :schedule_key,
              :scheduled_for,
              :window_start,
              :window_end,
              :status,
              :run_id,
              :idempotency_key,
              :trigger_payload_json
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "workflow_version_id": int(workflow_version_id) if workflow_version_id is not None else None,
                "trigger_node_id": str(trigger_node_id or "").strip(),
                "schedule_key": str(schedule_key or "").strip(),
                "scheduled_for": scheduled_for,
                "window_start": window_start,
                "window_end": window_end,
                "status": str(status or "pending").strip(),
                "run_id": int(run_id) if run_id is not None else None,
                "idempotency_key": str(idempotency_key or "").strip(),
                "trigger_payload_json": _json_or_none(trigger_payload),
            },
        )
        return _lastrowid(result)

    def get_schedule_run_by_idempotency(self, *, workspace_id: str, idempotency_key: str) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_schedule_runs
            WHERE workspace_id = :workspace_id
              AND idempotency_key = :idempotency_key
            LIMIT 1
            """,
            {"workspace_id": str(workspace_id or "").strip(), "idempotency_key": str(idempotency_key or "").strip()},
        )
        if not rows:
            return None
        return self._decode_schedule_run(rows[0])

    def update_schedule_run_status(
        self,
        *,
        workspace_id: str,
        schedule_run_id: int,
        status: str,
        run_id: int | None,
        error_message: str | None = None,
    ) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_schedule_runs
            SET status = :status,
                run_id = :run_id,
                error_message = :error_message,
                started_at = CASE WHEN :status = 'started' THEN CURRENT_TIMESTAMP ELSE started_at END,
                completed_at = CASE WHEN :status IN ('completed', 'failed', 'skipped') THEN CURRENT_TIMESTAMP ELSE completed_at END,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :schedule_run_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "schedule_run_id": int(schedule_run_id),
                "status": str(status or "").strip(),
                "run_id": int(run_id) if run_id is not None else None,
                "error_message": str(error_message or "").strip() or None,
            },
        )
        return bool(updated)
