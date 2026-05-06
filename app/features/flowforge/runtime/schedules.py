from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from app.features.flowforge.repositories import (
    FlowForgeDataMovementRepository,
    FlowForgeRuntimeRepository,
    FlowForgeWorkflowRepository,
)
from app.features.flowforge.runtime.schedule_windows import UTC, ScheduleWindow, ScheduleWindowCalculator

logger = logging.getLogger(__name__)


class FlowForgeScheduleRuntime:
    def __init__(
        self,
        *,
        workflow_repository: FlowForgeWorkflowRepository | None = None,
        data_movement_repository: FlowForgeDataMovementRepository | None = None,
        runtime_repository: FlowForgeRuntimeRepository | None = None,
        now_provider: Callable[[], datetime] | None = None,
        enqueue_dispatch: Callable[..., None] | None = None,
    ) -> None:
        self._workflow_repository = workflow_repository or FlowForgeWorkflowRepository()
        self._data_movement_repository = data_movement_repository or FlowForgeDataMovementRepository()
        self._runtime_repository = runtime_repository or FlowForgeRuntimeRepository()
        self._now_provider = now_provider or (lambda: datetime.now(UTC))
        self._enqueue_dispatch = enqueue_dispatch or self._enqueue_run_dispatch
        self._window_calculator = ScheduleWindowCalculator()

    def dispatch_due_schedules(self, *, limit: int = 100) -> dict[str, Any]:
        safe_limit = max(1, min(int(limit or 100), 500))
        now = self._window_calculator.as_utc(self._now_provider())
        candidates = self._workflow_repository.list_published_schedule_workflow_versions(limit=safe_limit)
        result = {"status": "completed", "scanned": 0, "due": 0, "created": 0, "skipped": []}
        for workflow in candidates:
            for node in self._schedule_nodes(workflow.get("graph_json") or workflow.get("graph") or {}):
                result["scanned"] += 1
                outcome = self._process_schedule_node(workflow=workflow, node=node, now=now)
                if outcome["status"] == "created":
                    result["due"] += 1
                    result["created"] += 1
                elif outcome["status"] == "duplicate":
                    result["due"] += 1
                    result["skipped"].append(outcome)
                elif outcome["status"] != "not_due":
                    result["skipped"].append(outcome)
        return result

    def _process_schedule_node(self, *, workflow: dict[str, Any], node: dict[str, Any], now: datetime) -> dict[str, Any]:
        config = self._node_config(node)
        node_id = str(node.get("id") or "").strip()
        workflow_definition_id = int(workflow["workflow_definition_id"])
        workflow_version_id = int(workflow["workflow_version_id"])
        workspace_id = str(workflow.get("workspace_id") or "").strip()
        if config.get("enabled") is False:
            return self._skip(workflow=workflow, node_id=node_id, reason="disabled")
        mode = str(config.get("mode") or "production").strip()
        if mode == "test" and not bool(config.get("allow_test_dispatch")):
            return self._skip(workflow=workflow, node_id=node_id, reason="test_ineligible")

        window = self._window_calculator.due_window(workflow=workflow, node=node, config=config, now=now)
        if window is None:
            return self._skip(workflow=workflow, node_id=node_id, reason="not_due", status="not_due")

        existing_schedule = self._data_movement_repository.get_schedule_run_by_idempotency(
            workspace_id=workspace_id,
            idempotency_key=window.idempotency_key,
        )
        if existing_schedule and existing_schedule.get("run_id"):
            return self._skip(
                workflow=workflow,
                node_id=node_id,
                reason="duplicate_window",
                status="duplicate",
                run_id=existing_schedule.get("run_id"),
            )

        schedule_run_id = int(existing_schedule["id"]) if existing_schedule else self._data_movement_repository.create_schedule_run(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
            workflow_version_id=workflow_version_id,
            trigger_node_id=node_id,
            schedule_key=window.schedule_key,
            scheduled_for=self._window_calculator.storage_datetime(window.scheduled_for),
            window_start=self._window_calculator.storage_datetime(window.window_start),
            window_end=self._window_calculator.storage_datetime(window.window_end) if window.window_end is not None else None,
            status="pending",
            run_id=None,
            idempotency_key=window.idempotency_key,
            trigger_payload=window.run_context.get("schedule") if isinstance(window.run_context.get("schedule"), dict) else {},
        )
        run_id = self._create_or_reuse_run(
            workspace_id=workspace_id,
            workflow=workflow,
            node_id=node_id,
            window=window,
            schedule_run_id=schedule_run_id,
        )
        self._data_movement_repository.update_schedule_run_status(
            workspace_id=workspace_id,
            schedule_run_id=schedule_run_id,
            status="completed",
            run_id=run_id,
        )
        self._enqueue_dispatch(workspace_id=workspace_id, run_id=int(run_id))
        return {
            "status": "created",
            "workflow_definition_id": workflow_definition_id,
            "workflow_version_id": workflow_version_id,
            "trigger_node_id": node_id,
            "run_id": run_id,
            "schedule_run_id": schedule_run_id,
        }

    def _create_or_reuse_run(
        self,
        *,
        workspace_id: str,
        workflow: dict[str, Any],
        node_id: str,
        window: ScheduleWindow,
        schedule_run_id: int,
    ) -> int:
        existing = self._runtime_repository.get_run_by_idempotency(
            workspace_id=workspace_id,
            idempotency_key=window.idempotency_key,
        )
        if existing is not None:
            return int(existing["id"])
        run_id = self._runtime_repository.create_run(
            workspace_id=workspace_id,
            workflow_definition_id=int(workflow["workflow_definition_id"]),
            workflow_version_id=int(workflow["workflow_version_id"]),
            intake_event_id=None,
            mode=window.mode,
            status="waiting",
            current_node_id=node_id,
            idempotency_key=window.idempotency_key,
            run_context={**window.run_context, "schedule_run_id": int(schedule_run_id)},
        )
        self._runtime_repository.append_run_event(
            workspace_id=workspace_id,
            run_id=run_id,
            event_type="workflow.run.created",
            node_id=node_id,
            message="Workflow run created from schedule trigger.",
            event_payload={
                "trigger_type": "schedule_trigger",
                "trigger_node_id": node_id,
                "schedule_run_id": int(schedule_run_id),
                "schedule_key": window.schedule_key,
                "scheduled_for": self._window_calculator.storage_datetime(window.scheduled_for).isoformat(),
                "window_start": self._window_calculator.storage_datetime(window.window_start).isoformat(),
                "window_end": (
                    self._window_calculator.storage_datetime(window.window_end).isoformat()
                    if window.window_end is not None
                    else None
                ),
                "workflow_definition_id": int(workflow["workflow_definition_id"]),
                "workflow_version_id": int(workflow["workflow_version_id"]),
                "mode": window.mode,
            },
            actor_type="system",
            actor_id="flowforge",
            idempotency_key=f"{window.idempotency_key}:event:created",
        )
        return int(run_id)

    @staticmethod
    def _schedule_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
        nodes = graph.get("nodes") if isinstance(graph, dict) else []
        return [
            dict(node)
            for node in nodes
            if isinstance(node, dict) and str(node.get("type") or "").strip() == "schedule_trigger"
        ]

    @staticmethod
    def _node_config(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        schedule = data.get("schedule") if isinstance(data.get("schedule"), dict) else {}
        return {**schedule, **data, **config}

    @staticmethod
    def _skip(
        *,
        workflow: dict[str, Any],
        node_id: str,
        reason: str,
        status: str = "skipped",
        run_id: Any = None,
    ) -> dict[str, Any]:
        payload = {
            "status": status,
            "reason": reason,
            "workflow_definition_id": workflow.get("workflow_definition_id"),
            "workflow_version_id": workflow.get("workflow_version_id"),
            "trigger_node_id": node_id,
        }
        if run_id is not None:
            payload["run_id"] = run_id
        return payload

    @staticmethod
    def _enqueue_run_dispatch(*, workspace_id: str, run_id: int) -> None:
        try:
            from app.tasks.flowforge_tasks import enqueue_flowforge_run_dispatch

            enqueue_flowforge_run_dispatch(workspace_id=workspace_id, run_id=int(run_id))
        except Exception:  # noqa: BLE001
            logger.exception("FlowForge schedule run dispatch enqueue failed workspace_id=%s run_id=%s", workspace_id, run_id)
