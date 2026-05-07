from __future__ import annotations

from typing import Any

from app.exceptions.forge_error import ForgeError


class FlowForgeRunServiceMixin:
    def list_runs(
        self,
        *,
        workspace_id: str,
        status: str | None,
        mode: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        safe_limit = min(max(int(limit or 100), 1), 500)
        safe_offset = max(int(offset or 0), 0)
        rows = self._runtime_repository.list_runs(
            workspace_id=workspace_id,
            status=self._optional_string(status),
            mode=self._optional_string(mode),
            limit=safe_limit,
            offset=safe_offset,
        )
        return {
            "workspace_id": workspace_id,
            "status": self._optional_string(status),
            "mode": self._optional_string(mode),
            "limit": safe_limit,
            "offset": safe_offset,
            "runs": [self._serialize_run(row) for row in rows],
        }

    def get_run(self, *, workspace_id: str, run_id: int) -> dict[str, Any] | None:
        row = self._runtime_repository.get_run(workspace_id=workspace_id, run_id=run_id)
        if row is None:
            return None
        return self._serialize_run(row)

    def list_run_events(self, *, workspace_id: str, run_id: int, limit: int) -> dict[str, Any]:
        safe_limit = min(max(int(limit or 100), 1), 500)
        rows = self._runtime_repository.list_run_events(
            workspace_id=workspace_id,
            run_id=run_id,
            limit=safe_limit,
        )
        return {
            "workspace_id": workspace_id,
            "run_id": int(run_id),
            "limit": safe_limit,
            "events": [self._serialize_run_event(row) for row in rows],
        }

    def list_run_human_tasks(self, *, workspace_id: str, run_id: int, limit: int) -> dict[str, Any]:
        run = self._runtime_repository.get_run(workspace_id=workspace_id, run_id=run_id)
        if run is None:
            raise ForgeError(f"FlowForge run '{run_id}' was not found.", status_code=404)

        safe_limit = min(max(int(limit or 100), 1), 500)
        rows = self._runtime_repository.list_run_human_tasks(
            workspace_id=workspace_id,
            run_id=run_id,
            limit=safe_limit,
        )
        return {
            "workspace_id": workspace_id,
            "run_id": int(run_id),
            "limit": safe_limit,
            "tasks": [self._serialize_human_task(row) for row in rows],
        }

    def list_human_tasks(
        self,
        *,
        workspace_id: str,
        task_type: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        safe_limit = min(max(int(limit or 100), 1), 500)
        safe_offset = max(int(offset or 0), 0)
        statuses = [
            entry.strip()
            for entry in str(status or "").split(",")
            if entry.strip()
        ]
        rows = self._runtime_repository.list_human_tasks(
            workspace_id=workspace_id,
            task_type=self._optional_string(task_type),
            statuses=statuses or None,
            limit=safe_limit,
            offset=safe_offset,
        )
        return {
            "workspace_id": workspace_id,
            "task_type": self._optional_string(task_type),
            "status": ",".join(statuses) if statuses else None,
            "limit": safe_limit,
            "offset": safe_offset,
            "tasks": [self._serialize_human_task(row) for row in rows],
        }

    def add_run_note(
        self,
        *,
        workspace_id: str,
        run_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        run = self._runtime_repository.get_run(workspace_id=workspace_id, run_id=run_id)
        if run is None:
            raise ForgeError(f"FlowForge run '{run_id}' was not found.", status_code=404)

        note = str((payload or {}).get("note") or "").strip()
        if not note:
            raise ForgeError("note is required.", status_code=400)
        if len(note) > 4000:
            raise ForgeError("note must be 4000 characters or fewer.", status_code=400)

        idempotency_key = self._optional_string((payload or {}).get("idempotency_key"))
        event = {
            "workspace_id": workspace_id,
            "run_id": int(run_id),
            "event_type": "workflow.operator.note",
            "node_id": None,
            "message": "Operator note added.",
            "event_payload": {"note": note},
            "actor_type": "user",
            "actor_id": self._optional_string(actor_user_id),
            "idempotency_key": idempotency_key,
        }
        event_id = self._runtime_repository.append_run_event(
            workspace_id=workspace_id,
            run_id=int(run_id),
            event_type=event["event_type"],
            node_id=None,
            message=event["message"],
            event_payload=event["event_payload"],
            actor_type=event["actor_type"],
            actor_id=event["actor_id"],
            idempotency_key=idempotency_key,
        )
        event["id"] = event_id
        return self._serialize_run_event(event)

    def _serialize_run(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "workflow_definition_id": row.get("workflow_definition_id"),
            "workflow_version_id": row.get("workflow_version_id"),
            "intake_event_id": row.get("intake_event_id"),
            "mode": row.get("mode"),
            "status": row.get("status"),
            "current_node_id": row.get("current_node_id"),
            "idempotency_key": row.get("idempotency_key"),
            "run_context": row.get("run_context") or row.get("run_context_json") or {},
            "started_at": row.get("started_at"),
            "completed_at": row.get("completed_at"),
            "failed_at": row.get("failed_at"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def _serialize_run_event(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "run_id": row.get("run_id"),
            "event_type": row.get("event_type"),
            "node_id": row.get("node_id"),
            "message": row.get("message"),
            "event_payload": row.get("event_payload") or row.get("event_payload_json") or {},
            "actor_type": row.get("actor_type"),
            "actor_id": row.get("actor_id"),
            "created_at": row.get("created_at"),
        }

    def _serialize_human_task(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "run_id": row.get("run_id"),
            "task_type": row.get("task_type"),
            "resource_set_id": row.get("resource_set_id"),
            "source_record_key": row.get("source_record_key"),
            "status": row.get("status"),
            "assigned_to_principal_type": row.get("assigned_to_principal_type"),
            "assigned_to_principal_id": row.get("assigned_to_principal_id"),
            "due_at": row.get("due_at"),
            "completed_at": row.get("completed_at"),
            "response": row.get("response") or row.get("response_json") or {},
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
