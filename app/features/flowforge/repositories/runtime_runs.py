from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories.common import json_or_none as _json_or_none, json_value as _json_value, lastrowid as _lastrowid


class FlowForgeRuntimeRunRepositoryMixin:
    def create_run(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        workflow_version_id: int,
        intake_event_id: int | None,
        mode: str,
        status: str,
        current_node_id: str | None,
        idempotency_key: str,
        run_context: dict[str, Any] | None,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_runs (
              workspace_id,
              workflow_definition_id,
              workflow_version_id,
              intake_event_id,
              mode,
              status,
              current_node_id,
              idempotency_key,
              run_context_json
            ) VALUES (
              :workspace_id,
              :workflow_definition_id,
              :workflow_version_id,
              :intake_event_id,
              :mode,
              :status,
              :current_node_id,
              :idempotency_key,
              :run_context_json
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "workflow_definition_id": int(workflow_definition_id),
                "workflow_version_id": int(workflow_version_id),
                "intake_event_id": int(intake_event_id) if intake_event_id is not None else None,
                "mode": str(mode or "production").strip(),
                "status": str(status or "waiting").strip(),
                "current_node_id": current_node_id,
                "idempotency_key": str(idempotency_key or "").strip(),
                "run_context_json": _json_or_none(run_context),
            },
        )
        return _lastrowid(result)

    def get_run_by_idempotency(self, *, workspace_id: str, idempotency_key: str) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_runs
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
        row = dict(rows[0])
        row["run_context_json"] = _json_value(row.get("run_context_json")) or {}
        return row

    def list_runs(
        self,
        *,
        workspace_id: str,
        status: str | None,
        mode: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        status_filter = str(status or "").strip()
        mode_filter = str(mode or "").strip()
        where_status = "AND status = :status" if status_filter else ""
        where_mode = "AND mode = :mode" if mode_filter else ""
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT *
            FROM flowforge_runs
            WHERE workspace_id = :workspace_id
              {where_status}
              {where_mode}
            ORDER BY started_at DESC, id DESC
            LIMIT :limit OFFSET :offset
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "status": status_filter,
                "mode": mode_filter,
                "limit": int(limit),
                "offset": int(offset),
            },
        )
        return [self._decode_run(row) for row in rows]

    def get_run(self, *, workspace_id: str, run_id: int) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_runs
            WHERE workspace_id = :workspace_id
              AND id = :run_id
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id),
            },
        )
        if not rows:
            return None
        return self._decode_run(rows[0])

    def update_run_status(
        self,
        *,
        workspace_id: str,
        run_id: int,
        status: str,
        current_node_id: str | None,
    ) -> bool:
        count = self._sql.execute_write(
            """
            UPDATE flowforge_runs
            SET status = :status,
                current_node_id = :current_node_id
            WHERE workspace_id = :workspace_id
              AND id = :run_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id),
                "status": str(status or "").strip(),
                "current_node_id": current_node_id,
            },
        )
        return bool(count)

    def update_run_context(self, *, workspace_id: str, run_id: int, run_context: dict[str, Any]) -> bool:
        count = self._sql.execute_write(
            """
            UPDATE flowforge_runs
            SET run_context_json = :run_context_json
            WHERE workspace_id = :workspace_id
              AND id = :run_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id),
                "run_context_json": _json_or_none(run_context),
            },
        )
        return bool(count)

    def complete_run(self, *, workspace_id: str, run_id: int, current_node_id: str | None) -> bool:
        count = self._sql.execute_write(
            """
            UPDATE flowforge_runs
            SET status = 'completed',
                current_node_id = :current_node_id,
                completed_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :run_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id),
                "current_node_id": current_node_id,
            },
        )
        return bool(count)

    def fail_run(
        self,
        *,
        workspace_id: str,
        run_id: int,
        current_node_id: str | None,
        error_code: str,
        error_message: str,
    ) -> bool:
        del error_code, error_message
        count = self._sql.execute_write(
            """
            UPDATE flowforge_runs
            SET status = 'failed',
                current_node_id = :current_node_id,
                failed_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :run_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id),
                "current_node_id": current_node_id,
            },
        )
        return bool(count)

    def get_report_summary(self, *, workspace_id: str, mode: str | None) -> dict[str, Any]:
        mode_filter = str(mode or "").strip()
        mode_clause = "AND mode = :mode" if mode_filter else ""
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              COUNT(*) AS run_count,
              SUM(CASE WHEN status IN ('waiting', 'running') THEN 1 ELSE 0 END) AS active_run_count,
              SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_run_count,
              SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_run_count,
              SUM(CASE WHEN status = 'needs_attention' THEN 1 ELSE 0 END) AS needs_attention_count,
              SUM(CASE WHEN mode = 'test' THEN 1 ELSE 0 END) AS test_run_count,
              SUM(CASE WHEN mode = 'production' THEN 1 ELSE 0 END) AS production_run_count
            FROM flowforge_runs
            WHERE workspace_id = :workspace_id
              {mode_clause}
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "mode": mode_filter,
            },
        )
        return dict(rows[0]) if rows else {}

    def get_reporting_dashboard_metrics(self, *, workspace_id: str, mode: str) -> dict[str, Any]:
        normalized_mode = str(mode or "production").strip()
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              (SELECT COUNT(*)
                 FROM flowforge_runs r
                WHERE r.workspace_id = :workspace_id
                  AND r.mode = :mode) AS run_count,
              (SELECT COUNT(*)
                 FROM flowforge_runs r
                WHERE r.workspace_id = :workspace_id
                  AND r.mode = :mode
                  AND r.status IN ('waiting', 'running', 'queued')) AS active_run_count,
              (SELECT COUNT(*)
                 FROM flowforge_runs r
                WHERE r.workspace_id = :workspace_id
                  AND r.mode = :mode
                  AND r.status = 'completed') AS completed_run_count,
              (SELECT COUNT(*)
                 FROM flowforge_runs r
                WHERE r.workspace_id = :workspace_id
                  AND r.mode = :mode
                  AND r.status = 'failed') AS failed_run_count,
              (SELECT COUNT(*)
                 FROM flowforge_runs r
                WHERE r.workspace_id = :workspace_id
                  AND r.mode = :mode
                  AND r.status = 'needs_attention') AS needs_attention_count,
              (SELECT COUNT(*)
                 FROM flowforge_intake_events i
                WHERE i.workspace_id = :workspace_id
                  AND i.mode = :mode) AS intake_event_count,
              (SELECT COUNT(*)
                 FROM flowforge_matching_evaluations e
                 JOIN flowforge_runs r
                   ON r.workspace_id = e.workspace_id
                  AND r.id = e.run_id
                WHERE e.workspace_id = :workspace_id
                  AND r.mode = :mode) AS matching_evaluation_count,
              (SELECT COUNT(*)
                 FROM flowforge_matching_evaluations e
                 JOIN flowforge_runs r
                   ON r.workspace_id = e.workspace_id
                  AND r.id = e.run_id
                WHERE e.workspace_id = :workspace_id
                  AND r.mode = :mode
                  AND e.no_match_reason IS NOT NULL
                  AND e.no_match_reason <> '') AS no_match_outcome_count,
              (SELECT COUNT(*)
                 FROM flowforge_resource_snapshot_records rs
                 JOIN flowforge_resource_snapshot_batches b
                   ON b.workspace_id = rs.workspace_id
                  AND b.id = rs.snapshot_batch_id
                WHERE rs.workspace_id = :workspace_id
                  AND b.mode = :mode) AS resource_snapshot_record_count,
              (SELECT COUNT(*)
                 FROM flowforge_resource_snapshot_records rs
                 JOIN flowforge_resource_snapshot_batches b
                   ON b.workspace_id = rs.workspace_id
                  AND b.id = rs.snapshot_batch_id
                WHERE rs.workspace_id = :workspace_id
                  AND b.mode = :mode
                  AND rs.effective_status = 'active'
                  AND COALESCE(rs.availability_status, '') IN ('', 'available')) AS available_resource_count,
              (SELECT COUNT(*)
                 FROM flowforge_human_tasks h
                 JOIN flowforge_runs r
                   ON r.workspace_id = h.workspace_id
                  AND r.id = h.run_id
                WHERE h.workspace_id = :workspace_id
                  AND r.mode = :mode
                  AND h.task_type = 'offer') AS offer_count,
              (SELECT COUNT(*)
                 FROM flowforge_human_tasks h
                 JOIN flowforge_runs r
                   ON r.workspace_id = h.workspace_id
                  AND r.id = h.run_id
                WHERE h.workspace_id = :workspace_id
                  AND r.mode = :mode
                  AND h.task_type = 'offer'
                  AND h.status = 'pending') AS pending_offer_count,
              (SELECT COUNT(*)
                 FROM flowforge_human_tasks h
                 JOIN flowforge_runs r
                   ON r.workspace_id = h.workspace_id
                  AND r.id = h.run_id
                WHERE h.workspace_id = :workspace_id
                  AND r.mode = :mode
                  AND h.task_type = 'offer'
                  AND h.status IN ('accepted', 'declined', 'timed_out', 'completed')) AS completed_offer_count,
              (SELECT COUNT(*)
                 FROM flowforge_assignments a
                 JOIN flowforge_runs r
                   ON r.workspace_id = a.workspace_id
                  AND r.id = a.run_id
                WHERE a.workspace_id = :workspace_id
                  AND r.mode = :mode) AS assignment_count,
              (SELECT COUNT(*)
                 FROM flowforge_notifications n
                 JOIN flowforge_runs r
                   ON r.workspace_id = n.workspace_id
                  AND r.id = n.run_id
                WHERE n.workspace_id = :workspace_id
                  AND r.mode = :mode) AS notification_count,
              (SELECT COUNT(*)
                 FROM flowforge_notifications n
                 JOIN flowforge_runs r
                   ON r.workspace_id = n.workspace_id
                  AND r.id = n.run_id
                WHERE n.workspace_id = :workspace_id
                  AND r.mode = :mode
                  AND n.status = 'pending') AS pending_notification_count,
              (SELECT COUNT(*)
                 FROM flowforge_notifications n
                 JOIN flowforge_runs r
                   ON r.workspace_id = n.workspace_id
                  AND r.id = n.run_id
                WHERE n.workspace_id = :workspace_id
                  AND r.mode = :mode
                  AND n.status = 'failed') AS failed_notification_count
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "mode": normalized_mode,
            },
        )
        return dict(rows[0]) if rows else {}

    def _decode_run(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        row["run_context_json"] = _json_value(row.get("run_context_json")) or {}
        return row
