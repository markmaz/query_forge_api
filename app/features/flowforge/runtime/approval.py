from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.features.flowforge.repositories import FlowForgeDataMovementRepository, FlowForgeRuntimeRepository
from app.features.flowforge.runtime.node_executor import NodeExecutionResult


class FlowForgeApprovalGateExecutor:
    def __init__(
        self,
        *,
        runtime_repository: FlowForgeRuntimeRepository | None = None,
        data_movement_repository: FlowForgeDataMovementRepository | None = None,
    ) -> None:
        self._runtime_repository = runtime_repository or FlowForgeRuntimeRepository()
        self._data_movement_repository = data_movement_repository or FlowForgeDataMovementRepository()

    def execute(
        self,
        *,
        workspace_id: str,
        run_id: int,
        node: dict[str, Any],
        run_context: dict[str, Any],
    ) -> NodeExecutionResult:
        node_id = str(node.get("id") or "").strip()
        config = self._node_config(node)
        approval_context = self._approval_context(config=config, run_context=run_context)
        task_idempotency_key = f"run:{int(run_id)}:node:{node_id}:approval:task"
        task_id = self._runtime_repository.create_human_task(
            workspace_id=workspace_id,
            run_id=run_id,
            task_type="approval",
            resource_set_id=self._optional_int(config.get("resource_set_id")),
            source_record_key=None,
            status="waiting",
            assigned_to_principal_type=self._assignee_type(config),
            assigned_to_principal_id=self._assignee_id(config),
            due_at=self._due_at(config),
            response={
                "allowed_actions": ["approve", "decline"],
                "approval": approval_context,
            },
            idempotency_key=task_idempotency_key,
        )
        self._data_movement_repository.create_data_movement_audit(
            workspace_id=workspace_id,
            run_id=run_id,
            node_id=node_id,
            action_type="approval",
            status="waiting",
            source_key=approval_context.get("source_key"),
            destination_key=approval_context.get("destination_key"),
            dataset_artifact_id=approval_context.get("dataset_artifact_id"),
            resource_set_id=self._optional_int(config.get("resource_set_id")),
            actor_type="system",
            actor_id="flowforge",
            request=approval_context,
            result={"human_task_id": int(task_id), "status": "waiting"},
            error_message=None,
            idempotency_key=f"run:{int(run_id)}:node:{node_id}:approval:requested",
            completed_at=None,
        )
        return NodeExecutionResult(
            status="waiting",
            next_node_id=node_id,
            event_payload={
                "node_type": "approval",
                "reason": "approval_required",
                "human_task_id": int(task_id),
                "approval": approval_context,
            },
        )

    def _approval_context(self, *, config: dict[str, Any], run_context: dict[str, Any]) -> dict[str, Any]:
        last_artifact = run_context.get("last_artifact") if isinstance(run_context, dict) else {}
        if not isinstance(last_artifact, dict):
            last_artifact = {}
        destination = last_artifact.get("destination") if isinstance(last_artifact.get("destination"), dict) else {}
        return {
            "approval_reason": str(config.get("approval_reason") or config.get("reason") or "").strip()
            or "Approval is required before workflow execution continues.",
            "artifact": last_artifact or None,
            "dataset_artifact_id": self._optional_int(
                config.get("dataset_artifact_id") or last_artifact.get("artifact_id")
            ),
            "source_key": self._optional_string(config.get("source_key")),
            "destination_key": self._optional_string(config.get("destination_key") or destination.get("destination_key")),
            "source_ref": config.get("source_ref") if isinstance(config.get("source_ref"), dict) else None,
            "destination_ref": destination or (config.get("destination_ref") if isinstance(config.get("destination_ref"), dict) else None),
        }

    @staticmethod
    def _node_config(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        return {**data, **config}

    def _assignee_type(self, config: dict[str, Any]) -> str:
        value = self._optional_string(config.get("assigned_to_principal_type"))
        if value:
            return value
        if self._optional_string(config.get("approval_group")):
            return "group"
        return "role"

    def _assignee_id(self, config: dict[str, Any]) -> str:
        return (
            self._optional_string(config.get("assigned_to_principal_id"))
            or self._optional_string(config.get("approval_group"))
            or self._optional_string(config.get("approval_role"))
            or "flowforge:operator"
        )

    def _due_at(self, config: dict[str, Any]) -> datetime | str | None:
        due_at = self._optional_string(config.get("due_at"))
        if due_at:
            return due_at
        timeout_minutes = self._optional_int(config.get("timeout_minutes") or config.get("approval_timeout_minutes"))
        if timeout_minutes is None:
            return None
        return datetime.now(UTC) + timedelta(minutes=max(1, timeout_minutes))

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)
