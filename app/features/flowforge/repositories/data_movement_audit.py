from __future__ import annotations

from datetime import datetime
from typing import Any

from app.features.flowforge.repositories.common import json_or_none as _json_or_none, lastrowid as _lastrowid


class FlowForgeDataMovementAuditRepositoryMixin:
    def create_data_movement_audit(
        self,
        *,
        workspace_id: str,
        run_id: int | None,
        node_id: str | None,
        action_type: str,
        status: str,
        source_key: str | None,
        destination_key: str | None,
        dataset_artifact_id: int | None,
        resource_set_id: int | None,
        actor_type: str | None,
        actor_id: str | None,
        request: dict[str, Any] | None,
        result: dict[str, Any] | None,
        error_message: str | None,
        idempotency_key: str | None,
        completed_at: datetime | str | None,
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = self.get_data_movement_audit_by_idempotency(
                workspace_id=workspace_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return existing
        insert_result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_data_movement_audit (
              workspace_id,
              run_id,
              node_id,
              action_type,
              status,
              source_key,
              destination_key,
              dataset_artifact_id,
              resource_set_id,
              actor_type,
              actor_id,
              request_json,
              result_json,
              error_message,
              idempotency_key,
              completed_at
            ) VALUES (
              :workspace_id,
              :run_id,
              :node_id,
              :action_type,
              :status,
              :source_key,
              :destination_key,
              :dataset_artifact_id,
              :resource_set_id,
              :actor_type,
              :actor_id,
              :request_json,
              :result_json,
              :error_message,
              :idempotency_key,
              :completed_at
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id) if run_id is not None else None,
                "node_id": str(node_id or "").strip() or None,
                "action_type": str(action_type or "").strip(),
                "status": str(status or "").strip(),
                "source_key": str(source_key or "").strip() or None,
                "destination_key": str(destination_key or "").strip() or None,
                "dataset_artifact_id": int(dataset_artifact_id) if dataset_artifact_id is not None else None,
                "resource_set_id": int(resource_set_id) if resource_set_id is not None else None,
                "actor_type": str(actor_type or "").strip() or None,
                "actor_id": str(actor_id or "").strip() or None,
                "request_json": _json_or_none(request),
                "result_json": _json_or_none(result),
                "error_message": str(error_message or "").strip() or None,
                "idempotency_key": str(idempotency_key or "").strip() or None,
                "completed_at": completed_at,
            },
        )
        return {
            "id": _lastrowid(insert_result),
            "workspace_id": str(workspace_id or "").strip(),
            "run_id": int(run_id) if run_id is not None else None,
            "node_id": str(node_id or "").strip() or None,
            "action_type": str(action_type or "").strip(),
            "status": str(status or "").strip(),
            "source_key": str(source_key or "").strip() or None,
            "destination_key": str(destination_key or "").strip() or None,
            "dataset_artifact_id": int(dataset_artifact_id) if dataset_artifact_id is not None else None,
            "resource_set_id": int(resource_set_id) if resource_set_id is not None else None,
            "actor_type": str(actor_type or "").strip() or None,
            "actor_id": str(actor_id or "").strip() or None,
            "request_json": request or {},
            "result_json": result or {},
            "error_message": str(error_message or "").strip() or None,
            "idempotency_key": str(idempotency_key or "").strip() or None,
            "completed_at": completed_at,
        }

    def get_data_movement_audit_by_idempotency(
        self, *, workspace_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_data_movement_audit
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
        return self._decode_audit(rows[0])

    def list_data_movement_audit(
        self,
        *,
        workspace_id: str,
        run_id: int | None = None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        run_filter = "AND run_id = :run_id" if run_id is not None else ""
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT *
            FROM flowforge_data_movement_audit
            WHERE workspace_id = :workspace_id
              {run_filter}
            ORDER BY started_at DESC, id DESC
            LIMIT :limit OFFSET :offset
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id) if run_id is not None else None,
                "limit": int(limit),
                "offset": int(offset),
            },
        )
        return [self._decode_audit(row) for row in rows]
