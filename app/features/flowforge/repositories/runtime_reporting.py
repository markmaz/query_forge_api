from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories.common import json_value as _json_value


class FlowForgeRuntimeReportingRepositoryMixin:
    def list_intake_review_events(self, *, workspace_id: str, mode: str, days: int) -> list[dict[str, Any]]:
        lookback_days = max(0, min(int(days or 7), 31) - 1)
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              i.id AS intake_event_id,
              DATE(i.received_at) AS intake_date,
              i.received_at,
              i.provider,
              i.external_form_id,
              i.external_submission_id,
              i.raw_payload_redacted_at,
              i.raw_payload_expires_at,
              r.id AS run_id,
              r.status AS run_status,
              r.workflow_definition_id,
              r.workflow_version_id,
              r.workflow_key,
              a.id AS assignment_id,
              a.status AS assignment_status,
              a.resource_set_id AS accepted_resource_set_id,
              a.source_record_key AS accepted_source_record_key,
              rs.display_name AS accepted_resource_display_name,
              me.no_match_reason AS no_match_reason
            FROM flowforge_intake_events i
            LEFT JOIN flowforge_runs r
              ON r.workspace_id = i.workspace_id
             AND r.intake_event_id = i.id
            LEFT JOIN flowforge_assignments a
              ON a.workspace_id = r.workspace_id
             AND a.run_id = r.id
             AND a.id = (
                SELECT MAX(a2.id)
                FROM flowforge_assignments a2
                WHERE a2.workspace_id = r.workspace_id
                  AND a2.run_id = r.id
             )
            LEFT JOIN flowforge_resource_snapshot_records rs
              ON rs.workspace_id = a.workspace_id
             AND rs.resource_set_id = a.resource_set_id
             AND rs.source_record_key = a.source_record_key
             AND rs.id = (
                SELECT MAX(rs2.id)
                FROM flowforge_resource_snapshot_records rs2
                WHERE rs2.workspace_id = a.workspace_id
                  AND rs2.resource_set_id = a.resource_set_id
                  AND rs2.source_record_key = a.source_record_key
             )
            LEFT JOIN flowforge_matching_evaluations me
              ON me.workspace_id = r.workspace_id
             AND me.run_id = r.id
             AND me.id = (
                SELECT MAX(me2.id)
                FROM flowforge_matching_evaluations me2
                WHERE me2.workspace_id = r.workspace_id
                  AND me2.run_id = r.id
             )
            WHERE i.workspace_id = :workspace_id
              AND i.mode = :mode
              AND i.received_at >= DATE_SUB(CURRENT_DATE, INTERVAL {lookback_days} DAY)
              AND i.received_at < DATE_ADD(CURRENT_DATE, INTERVAL 1 DAY)
            ORDER BY i.received_at ASC, i.id ASC
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "mode": str(mode or "production").strip(),
            },
        )
        return [dict(row) for row in rows]

    def get_intake_raw_form(self, *, workspace_id: str, intake_event_id: int) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id AS intake_event_id,
              workspace_id,
              integration_config_id,
              provider,
              external_form_id,
              external_submission_id,
              mode,
              received_at,
              raw_payload_json,
              normalized_payload_json,
              raw_payload_expires_at,
              raw_payload_redacted_at,
              raw_payload_redacted_by
            FROM flowforge_intake_events
            WHERE workspace_id = :workspace_id
              AND id = :intake_event_id
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "intake_event_id": int(intake_event_id),
            },
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["raw_payload_json"] = _json_value(row.get("raw_payload_json")) or {}
        row["normalized_payload_json"] = _json_value(row.get("normalized_payload_json")) or {}
        row["raw_payload_available"] = bool(row["raw_payload_json"]) and row.get("raw_payload_redacted_at") is None
        return row
