from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories.common import json_or_none as _json_or_none, lastrowid as _lastrowid


class FlowForgeRuntimeAssignmentRepositoryMixin:
    def create_assignment(
        self,
        *,
        workspace_id: str,
        run_id: int,
        human_task_id: int | None,
        resource_set_id: int,
        source_record_key: str,
        status: str,
        assignment: dict[str, Any] | None,
        idempotency_key: str,
    ) -> int:
        existing = self.get_assignment_by_idempotency(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return int(existing["id"])
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_assignments (
              workspace_id,
              run_id,
              human_task_id,
              resource_set_id,
              source_record_key,
              status,
              assignment_json,
              idempotency_key
            ) VALUES (
              :workspace_id,
              :run_id,
              :human_task_id,
              :resource_set_id,
              :source_record_key,
              :status,
              :assignment_json,
              :idempotency_key
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id),
                "human_task_id": int(human_task_id) if human_task_id is not None else None,
                "resource_set_id": int(resource_set_id),
                "source_record_key": str(source_record_key or "").strip(),
                "status": str(status or "assigned").strip(),
                "assignment_json": _json_or_none(assignment or {}),
                "idempotency_key": str(idempotency_key or "").strip(),
            },
        )
        return _lastrowid(result)

    def get_assignment_by_idempotency(self, *, workspace_id: str, idempotency_key: str) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_assignments
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
        return dict(rows[0])
