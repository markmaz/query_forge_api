from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories.common import json_or_none as _json_or_none, json_value as _json_value, lastrowid as _lastrowid


class FlowForgeRuntimeHumanTaskRepositoryMixin:
    def create_human_task(
        self,
        *,
        workspace_id: str,
        run_id: int,
        task_type: str,
        resource_set_id: int | None,
        source_record_key: str | None,
        status: str,
        assigned_to_principal_type: str | None,
        assigned_to_principal_id: str | None,
        due_at: Any | None,
        response: dict[str, Any] | None,
        idempotency_key: str | None = None,
    ) -> int:
        if idempotency_key:
            existing = self.get_human_task_by_idempotency(
                workspace_id=workspace_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return int(existing["id"])
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_human_tasks (
              workspace_id,
              run_id,
              task_type,
              resource_set_id,
              source_record_key,
              status,
              assigned_to_principal_type,
              assigned_to_principal_id,
              due_at,
              response_json,
              idempotency_key
            ) VALUES (
              :workspace_id,
              :run_id,
              :task_type,
              :resource_set_id,
              :source_record_key,
              :status,
              :assigned_to_principal_type,
              :assigned_to_principal_id,
              :due_at,
              :response_json,
              :idempotency_key
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id),
                "task_type": str(task_type or "").strip(),
                "resource_set_id": int(resource_set_id) if resource_set_id is not None else None,
                "source_record_key": source_record_key,
                "status": str(status or "pending").strip(),
                "assigned_to_principal_type": assigned_to_principal_type,
                "assigned_to_principal_id": assigned_to_principal_id,
                "due_at": due_at,
                "response_json": _json_or_none(response),
                "idempotency_key": idempotency_key,
            },
        )
        return _lastrowid(result)

    def get_human_task_by_idempotency(self, *, workspace_id: str, idempotency_key: str) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_human_tasks
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
        return self._decode_human_task(rows[0])

    def list_run_human_tasks(self, *, workspace_id: str, run_id: int, limit: int) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_human_tasks
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
        return [self._decode_human_task(row) for row in rows]

    def list_human_tasks(
        self,
        *,
        workspace_id: str,
        task_type: str | None,
        statuses: list[str] | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        where_parts = ["workspace_id = :workspace_id"]
        params: dict[str, Any] = {
            "workspace_id": str(workspace_id or "").strip(),
            "limit": int(limit),
            "offset": int(offset),
        }
        if task_type:
            where_parts.append("task_type = :task_type")
            params["task_type"] = str(task_type or "").strip()
        safe_statuses = [str(status or "").strip() for status in (statuses or []) if str(status or "").strip()]
        if safe_statuses:
            placeholders = []
            for index, status in enumerate(safe_statuses):
                key = f"status_{index}"
                placeholders.append(f":{key}")
                params[key] = status
            where_parts.append(f"status IN ({', '.join(placeholders)})")
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT *
            FROM flowforge_human_tasks
            WHERE {' AND '.join(where_parts)}
            ORDER BY
              CASE WHEN due_at IS NULL THEN 1 ELSE 0 END,
              due_at ASC,
              created_at ASC,
              id ASC
            LIMIT :limit
            OFFSET :offset
            """,
            params,
        )
        return [self._decode_human_task(row) for row in rows]

    def list_due_human_tasks(self, *, limit: int) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_human_tasks
            WHERE status IN ('pending', 'waiting')
              AND due_at IS NOT NULL
              AND due_at <= CURRENT_TIMESTAMP
            ORDER BY due_at ASC, id ASC
            LIMIT :limit
            """,
            {"limit": int(limit)},
        )
        return [self._decode_human_task(row) for row in rows]

    def get_human_task(self, *, workspace_id: str, human_task_id: int) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_human_tasks
            WHERE workspace_id = :workspace_id
              AND id = :human_task_id
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "human_task_id": int(human_task_id),
            },
        )
        if not rows:
            return None
        return self._decode_human_task(rows[0])

    def update_human_task_response(
        self,
        *,
        workspace_id: str,
        human_task_id: int,
        status: str,
        response: dict[str, Any],
    ) -> bool:
        count = self._sql.execute_write(
            """
            UPDATE flowforge_human_tasks
            SET status = :status,
                completed_at = CURRENT_TIMESTAMP,
                response_json = :response_json
            WHERE workspace_id = :workspace_id
              AND id = :human_task_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "human_task_id": int(human_task_id),
                "status": str(status or "").strip(),
                "response_json": _json_or_none(response),
            },
        )
        return bool(count)

    def _decode_human_task(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        row["response_json"] = _json_value(row.get("response_json")) or {}
        return row
