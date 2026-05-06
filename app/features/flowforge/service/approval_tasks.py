from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.exceptions.forge_error import ForgeError


class FlowForgeApprovalTaskServiceMixin:
    def complete_approval_task(
        self,
        *,
        workspace_id: str,
        human_task_id: int,
        action: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        task = self._runtime_repository.get_human_task(
            workspace_id=workspace_id,
            human_task_id=human_task_id,
        )
        if task is None:
            raise ForgeError(f"FlowForge human task '{human_task_id}' was not found.", status_code=404)
        if str(task.get("task_type") or "") != "approval":
            raise ForgeError("Human task is not an approval task.", status_code=400)
        if str(task.get("status") or "") not in {"pending", "waiting"}:
            raise ForgeError("Approval task is no longer pending.", status_code=409)

        normalized_action = self._normalize_approval_action(action)
        response = self._approval_response(
            task=task,
            action=normalized_action,
            payload=payload,
            actor_user_id=actor_user_id,
        )
        task_status = "approved" if normalized_action == "approve" else "declined"
        self._runtime_repository.update_human_task_response(
            workspace_id=workspace_id,
            human_task_id=human_task_id,
            status=task_status,
            response=response,
        )
        self._runtime_repository.append_run_event(
            workspace_id=workspace_id,
            run_id=int(task["run_id"]),
            event_type=f"workflow.approval.{task_status}",
            node_id=None,
            message=f"Approval task {task_status}.",
            event_payload={
                "human_task_id": int(human_task_id),
                "action": normalized_action,
                "approval": response.get("approval"),
            },
            actor_type="user",
            actor_id=self._optional_string(actor_user_id),
            idempotency_key=self._optional_string((payload or {}).get("idempotency_key"))
            or f"human-task:{int(human_task_id)}:approval:{normalized_action}",
        )
        self._record_approval_decision_audit(
            workspace_id=workspace_id,
            task=task,
            action=normalized_action,
            status=task_status,
            response=response,
            actor_user_id=actor_user_id,
        )
        runtime_result = self._advance_after_approval_decision(
            workspace_id=workspace_id,
            task=task,
            action=normalized_action,
            actor_user_id=actor_user_id,
        )
        return {
            "human_task_id": int(human_task_id),
            "run_id": int(task["run_id"]),
            "action": normalized_action,
            "status": task_status,
            "runtime": runtime_result,
        }

    def _advance_after_approval_decision(
        self,
        *,
        workspace_id: str,
        task: dict[str, Any],
        action: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        from app.features.flowforge.runtime.human_responses import FlowForgeHumanResponseRuntime

        runtime_result = FlowForgeHumanResponseRuntime(
            runtime_repository=self._runtime_repository,
            workflow_repository=self._workflow_repository,
        ).advance_after_human_action(
            workspace_id=workspace_id,
            run_id=int(task["run_id"]),
            action=action,
            human_task_id=int(task["id"]),
            resource_set_id=task.get("resource_set_id"),
            source_record_key=task.get("source_record_key"),
        )
        if action == "decline" and runtime_result.get("status") == "no_target":
            self._runtime_repository.fail_run(
                workspace_id=workspace_id,
                run_id=int(task["run_id"]),
                current_node_id=runtime_result.get("from_node_id"),
                error_code="approval_declined",
                error_message="Approval task was declined and no decline branch was configured.",
            )
            self._runtime_repository.append_run_event(
                workspace_id=workspace_id,
                run_id=int(task["run_id"]),
                event_type="workflow.approval.decline_failed_run",
                node_id=runtime_result.get("from_node_id"),
                message="Approval was declined and the workflow run was marked failed.",
                event_payload={
                    "human_task_id": int(task["id"]),
                    "action": action,
                },
                actor_type="user",
                actor_id=self._optional_string(actor_user_id),
                idempotency_key=f"human-task:{int(task['id'])}:approval:decline:failed-run",
            )
            return {
                **runtime_result,
                "status": "failed",
                "reason": "approval_declined",
            }
        return runtime_result

    def _record_approval_decision_audit(
        self,
        *,
        workspace_id: str,
        task: dict[str, Any],
        action: str,
        status: str,
        response: dict[str, Any],
        actor_user_id: str,
    ) -> None:
        approval = response.get("approval") if isinstance(response.get("approval"), dict) else {}
        self._data_movement_repository.create_data_movement_audit(
            workspace_id=workspace_id,
            run_id=int(task["run_id"]),
            node_id=None,
            action_type="approval",
            status=status,
            source_key=approval.get("source_key"),
            destination_key=approval.get("destination_key"),
            dataset_artifact_id=approval.get("dataset_artifact_id"),
            resource_set_id=task.get("resource_set_id"),
            actor_type="user",
            actor_id=self._optional_string(actor_user_id),
            request={"human_task_id": int(task["id"]), "action": action},
            result=response,
            error_message=None,
            idempotency_key=f"human-task:{int(task['id'])}:approval:{action}:audit",
            completed_at=datetime.now(UTC),
        )

    def _approval_response(
        self,
        *,
        task: dict[str, Any],
        action: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        existing_response = task.get("response") or task.get("response_json") or {}
        approval = existing_response.get("approval") if isinstance(existing_response, dict) else {}
        return {
            "action": action,
            "decision_note": self._optional_string((payload or {}).get("decision_note")),
            "decline_reason": self._optional_string((payload or {}).get("decline_reason")),
            "decided_by": self._optional_string(actor_user_id),
            "decided_at": datetime.now(UTC).isoformat(),
            "approval": approval if isinstance(approval, dict) else {},
        }

    @staticmethod
    def _normalize_approval_action(action: str) -> str:
        normalized = str(action or "").strip().lower()
        if normalized in {"approve", "approved", "accept", "accepted"}:
            return "approve"
        if normalized in {"decline", "declined", "reject", "rejected", "deny", "denied"}:
            return "decline"
        raise ForgeError("Unsupported approval action.", status_code=400)
