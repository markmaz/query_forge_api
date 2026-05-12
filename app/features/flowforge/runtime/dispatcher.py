from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories import (
    FlowForgeDataMovementRepository,
    FlowForgeMatchingRepository,
    FlowForgeResourceRepository,
    FlowForgeRuntimeRepository,
    FlowForgeWorkflowRepository,
)
from app.features.flowforge.runtime.idempotency import (
    dispatch_event_key,
    node_event_key,
)
from app.features.flowforge.runtime.locks import FlowForgeRuntimeLock
from app.features.flowforge.runtime.approval import FlowForgeApprovalGateExecutor
from app.features.flowforge.runtime.data_import import FlowForgeImportExecutor
from app.features.flowforge.runtime.export import FlowForgeExportExecutor
from app.features.flowforge.runtime.map_transform import FlowForgeMapTransformExecutor
from app.features.flowforge.runtime.matching import FlowForgeRuntimeMatchingExecutor
from app.features.flowforge.runtime.notification_node import FlowForgeNotificationNodeExecutor
from app.features.flowforge.runtime.node_executor import (
    FlowForgeNodeExecutionError,
    FlowForgeNodeExecutor,
)
from app.features.flowforge.runtime.query_extract import FlowForgeQueryExtractExecutor

TERMINAL_STATUSES = {"completed", "failed", "canceled"}


class FlowForgeRuntimeDispatcher:
    def __init__(
        self,
        *,
        runtime_repository: FlowForgeRuntimeRepository | None = None,
        workflow_repository: FlowForgeWorkflowRepository | None = None,
        matching_repository: FlowForgeMatchingRepository | None = None,
        data_movement_repository: FlowForgeDataMovementRepository | None = None,
        resource_repository: FlowForgeResourceRepository | None = None,
        node_executor: FlowForgeNodeExecutor | None = None,
        matching_executor: FlowForgeRuntimeMatchingExecutor | None = None,
        query_extract_executor: FlowForgeQueryExtractExecutor | None = None,
        map_transform_executor: FlowForgeMapTransformExecutor | None = None,
        export_executor: FlowForgeExportExecutor | None = None,
        import_executor: FlowForgeImportExecutor | None = None,
        approval_executor: FlowForgeApprovalGateExecutor | None = None,
        notification_node_executor: FlowForgeNotificationNodeExecutor | None = None,
        max_steps: int = 50,
    ) -> None:
        self._runtime_repository = runtime_repository or FlowForgeRuntimeRepository()
        self._workflow_repository = workflow_repository or FlowForgeWorkflowRepository()
        self._data_movement_repository = data_movement_repository or FlowForgeDataMovementRepository()
        self._node_executor = node_executor or FlowForgeNodeExecutor()
        self._matching_executor = matching_executor or FlowForgeRuntimeMatchingExecutor(
            runtime_repository=self._runtime_repository,
            matching_repository=matching_repository,
            resource_repository=resource_repository,
        )
        self._query_extract_executor = (
            query_extract_executor
            or FlowForgeQueryExtractExecutor(
                data_movement_repository=self._data_movement_repository,
            )
        )
        self._map_transform_executor = (
            map_transform_executor
            or FlowForgeMapTransformExecutor(
                data_movement_repository=self._data_movement_repository,
            )
        )
        self._export_executor = export_executor or FlowForgeExportExecutor(
            data_movement_repository=self._data_movement_repository,
        )
        self._import_executor = import_executor or FlowForgeImportExecutor(
            data_movement_repository=self._data_movement_repository,
            resource_repository=resource_repository,
        )
        self._approval_executor = approval_executor or FlowForgeApprovalGateExecutor(
            runtime_repository=self._runtime_repository,
            data_movement_repository=self._data_movement_repository,
        )
        self._notification_node_executor = notification_node_executor or FlowForgeNotificationNodeExecutor(
            runtime_repository=self._runtime_repository,
        )
        self._max_steps = max(1, int(max_steps or 50))

    def dispatch_run(self, *, workspace_id: str, run_id: int) -> dict[str, Any]:
        run = self._runtime_repository.get_run(workspace_id=workspace_id, run_id=run_id)
        if run is None:
            return {"status": "not_found", "run_id": int(run_id)}
        if str(run.get("status") or "") in TERMINAL_STATUSES:
            return {
                "status": "skipped",
                "reason": "terminal_status",
                "run_id": int(run_id),
            }

        with FlowForgeRuntimeLock(workspace_id=workspace_id, run_id=run_id):
            return self._dispatch_loaded_run(workspace_id=workspace_id, run=dict(run))

    def _dispatch_loaded_run(
        self, *, workspace_id: str, run: dict[str, Any]
    ) -> dict[str, Any]:
        run_id = int(run["id"])
        graph = self._load_graph(workspace_id=workspace_id, run=run)
        if graph is None:
            return self._fail_run(
                workspace_id=workspace_id,
                run_id=run_id,
                current_node_id=self._optional_node_id(run.get("current_node_id")),
                error_code="workflow_version_missing",
                error_message="Workflow version was not found for FlowForge run.",
                visited_node_ids=[],
            )

        nodes = self._nodes_by_id(graph)
        edges = self._edges(graph)
        current_node_id = self._optional_node_id(
            run.get("current_node_id")
        ) or self._first_node_id(graph)
        if not current_node_id:
            return self._fail_run(
                workspace_id=workspace_id,
                run_id=run_id,
                current_node_id=None,
                error_code="workflow_graph_empty",
                error_message="Workflow graph does not contain an executable start node.",
                visited_node_ids=[],
            )

        self._runtime_repository.update_run_status(
            workspace_id=workspace_id,
            run_id=run_id,
            status="running",
            current_node_id=current_node_id,
        )
        self._append_once(
            workspace_id=workspace_id,
            run_id=run_id,
            event_type="workflow.dispatch.started",
            node_id=current_node_id,
            message="FlowForge runtime dispatch started.",
            event_payload={"workflow_version_id": run.get("workflow_version_id")},
            idempotency_key=dispatch_event_key(run_id=run_id, suffix="started"),
        )

        visited_node_ids: list[str] = []
        run_context = run.get("run_context") or run.get("run_context_json") or {}
        for _ in range(self._max_steps):
            node = nodes.get(current_node_id)
            if node is None:
                return self._fail_run(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    current_node_id=current_node_id,
                    error_code="node_missing",
                    error_message=f"Workflow node '{current_node_id}' was not found.",
                    visited_node_ids=visited_node_ids,
                )
            visited_node_ids.append(current_node_id)
            self._append_once(
                workspace_id=workspace_id,
                run_id=run_id,
                event_type="workflow.node.started",
                node_id=current_node_id,
                message=f"FlowForge node '{current_node_id}' started.",
                event_payload={"node_type": node.get("type")},
                idempotency_key=node_event_key(
                    run_id=run_id, node_id=current_node_id, suffix="started"
                ),
            )
            try:
                outgoing_edges = self._outgoing_edges(edges, current_node_id)
                if str(node.get("type") or "").strip() == "matching":
                    result = self._matching_executor.execute(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        run_mode=str(run.get("mode") or "production"),
                        node=node,
                        outgoing_edges=outgoing_edges,
                        run_context=run_context
                        if isinstance(run_context, dict)
                        else {},
                        offer_config=self._matched_human_task_config(
                            nodes=nodes,
                            outgoing_edges=outgoing_edges,
                        ),
                    )
                elif str(node.get("type") or "").strip() == "query_extract":
                    result = self._query_extract_executor.execute(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        node=node,
                        outgoing_edges=outgoing_edges,
                        run_context=run_context
                        if isinstance(run_context, dict)
                        else {},
                    )
                elif str(node.get("type") or "").strip() == "map_transform":
                    result = self._map_transform_executor.execute(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        node=node,
                        outgoing_edges=outgoing_edges,
                        run_context=run_context
                        if isinstance(run_context, dict)
                        else {},
                    )
                elif str(node.get("type") or "").strip() == "export":
                    result = self._export_executor.execute(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        node=node,
                        outgoing_edges=outgoing_edges,
                        run_context=run_context
                        if isinstance(run_context, dict)
                        else {},
                    )
                elif str(node.get("type") or "").strip() == "import":
                    result = self._import_executor.execute(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        node=node,
                        outgoing_edges=outgoing_edges,
                        run_context=run_context
                        if isinstance(run_context, dict)
                        else {},
                    )
                elif str(node.get("type") or "").strip() == "approval":
                    result = self._approval_executor.execute(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        node=node,
                        run_context=run_context
                        if isinstance(run_context, dict)
                        else {},
                    )
                elif str(node.get("type") or "").strip() == "notification":
                    result = self._notification_node_executor.execute(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        node=node,
                        outgoing_edges=outgoing_edges,
                        run_context=run_context
                        if isinstance(run_context, dict)
                        else {},
                    )
                else:
                    result = self._node_executor.execute(
                        node=node,
                        outgoing_edges=outgoing_edges,
                        run_context=run_context
                        if isinstance(run_context, dict)
                        else {},
                    )
            except FlowForgeNodeExecutionError as exc:
                return self._fail_run(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    current_node_id=current_node_id,
                    error_code="node_execution_failed",
                    error_message=str(exc),
                    visited_node_ids=visited_node_ids,
                )

            context_update = self._node_output_context_update(
                node_id=current_node_id,
                node=node,
                result=result,
            )
            if result.run_context_update:
                context_update = self._merge_run_context(context_update, result.run_context_update)
            run_context = self._merge_run_context(
                run_context if isinstance(run_context, dict) else {},
                context_update,
            )
            self._runtime_repository.update_run_context(
                workspace_id=workspace_id,
                run_id=run_id,
                run_context=run_context,
            )

            if result.status == "waiting":
                self._append_once(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    event_type="workflow.node.waiting",
                    node_id=current_node_id,
                    message=f"FlowForge node '{current_node_id}' is waiting.",
                    event_payload=result.event_payload or {},
                    idempotency_key=node_event_key(
                        run_id=run_id, node_id=current_node_id, suffix="waiting"
                    ),
                )
                self._runtime_repository.update_run_status(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    status="waiting",
                    current_node_id=current_node_id,
                )
                return {
                    "status": "waiting",
                    "run_id": run_id,
                    "visited_node_ids": visited_node_ids,
                }

            self._append_once(
                workspace_id=workspace_id,
                run_id=run_id,
                event_type="workflow.node.completed",
                node_id=current_node_id,
                message=f"FlowForge node '{current_node_id}' completed.",
                event_payload=result.event_payload or {},
                idempotency_key=node_event_key(
                    run_id=run_id, node_id=current_node_id, suffix="completed"
                ),
            )

            if result.status == "completed":
                self._runtime_repository.complete_run(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    current_node_id=current_node_id,
                )
                self._append_once(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    event_type="workflow.dispatch.completed",
                    node_id=current_node_id,
                    message="FlowForge runtime dispatch completed.",
                    event_payload={"visited_node_ids": visited_node_ids},
                    idempotency_key=dispatch_event_key(
                        run_id=run_id, suffix="completed"
                    ),
                )
                return {
                    "status": "completed",
                    "run_id": run_id,
                    "visited_node_ids": visited_node_ids,
                }

            current_node_id = str(result.next_node_id or "").strip()
            self._runtime_repository.update_run_status(
                workspace_id=workspace_id,
                run_id=run_id,
                status="running",
                current_node_id=current_node_id,
            )

        return self._fail_run(
            workspace_id=workspace_id,
            run_id=run_id,
            current_node_id=current_node_id,
            error_code="max_steps_exceeded",
            error_message=f"FlowForge dispatch exceeded the max step count of {self._max_steps}.",
            visited_node_ids=visited_node_ids,
        )

    def _load_graph(
        self, *, workspace_id: str, run: dict[str, Any]
    ) -> dict[str, Any] | None:
        version = self._workflow_repository.get_workflow_version(
            workspace_id=workspace_id,
            workflow_definition_id=int(run["workflow_definition_id"]),
            version_id=int(run["workflow_version_id"]),
        )
        if version is None:
            return None
        graph = version.get("graph") or version.get("graph_json") or {}
        return graph if isinstance(graph, dict) else {}

    def _fail_run(
        self,
        *,
        workspace_id: str,
        run_id: int,
        current_node_id: str | None,
        error_code: str,
        error_message: str,
        visited_node_ids: list[str],
    ) -> dict[str, Any]:
        self._runtime_repository.fail_run(
            workspace_id=workspace_id,
            run_id=run_id,
            current_node_id=current_node_id,
            error_code=error_code,
            error_message=error_message,
        )
        self._append_once(
            workspace_id=workspace_id,
            run_id=run_id,
            event_type="workflow.dispatch.failed",
            node_id=current_node_id,
            message="FlowForge runtime dispatch failed.",
            event_payload={
                "error_code": error_code,
                "error_message": error_message,
                "visited_node_ids": visited_node_ids,
            },
            idempotency_key=dispatch_event_key(
                run_id=run_id, suffix=f"failed:{error_code}"
            ),
        )
        return {
            "status": "failed",
            "run_id": run_id,
            "error_code": error_code,
            "visited_node_ids": visited_node_ids,
        }

    def _append_once(
        self,
        *,
        workspace_id: str,
        run_id: int,
        event_type: str,
        node_id: str | None,
        message: str,
        event_payload: dict[str, Any],
        idempotency_key: str,
    ) -> int | None:
        existing = self._runtime_repository.get_run_event_by_idempotency(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return None
        return self._runtime_repository.append_run_event(
            workspace_id=workspace_id,
            run_id=run_id,
            event_type=event_type,
            node_id=node_id,
            message=message,
            event_payload=event_payload,
            actor_type="system",
            actor_id="flowforge",
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _merge_run_context(
        current: dict[str, Any], update: dict[str, Any]
    ) -> dict[str, Any]:
        merged = dict(current)
        for key, value in update.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _node_output_context_update(
        *,
        node_id: str,
        node: dict[str, Any],
        result: Any,
    ) -> dict[str, Any]:
        output = {
            "node_id": node_id,
            "node_type": str(node.get("type") or "").strip(),
            "status": result.status,
            "next_node_id": result.next_node_id,
            "data": result.event_payload or {},
        }
        return {
            "node_outputs": {node_id: output},
            "last_node_output": output,
        }

    @staticmethod
    def _nodes_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
        nodes = graph.get("nodes") if isinstance(graph, dict) else []
        return {
            str(node.get("id") or "").strip(): dict(node)
            for node in nodes
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }

    @staticmethod
    def _edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
        edges = graph.get("edges") if isinstance(graph, dict) else []
        return [dict(edge) for edge in edges if isinstance(edge, dict)]

    @staticmethod
    def _outgoing_edges(
        edges: list[dict[str, Any]], node_id: str
    ) -> list[dict[str, Any]]:
        return [
            edge for edge in edges if str(edge.get("source") or "").strip() == node_id
        ]

    @classmethod
    def _matched_human_task_config(
        cls, *, nodes: dict[str, dict[str, Any]], outgoing_edges: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        target_node = cls._target_node_for_branch(
            nodes=nodes,
            outgoing_edges=outgoing_edges,
            branch="matched",
        )
        if target_node is None or str(target_node.get("type") or "").strip() != "human_task":
            return None
        data = target_node.get("data") if isinstance(target_node.get("data"), dict) else {}
        config = target_node.get("config") if isinstance(target_node.get("config"), dict) else {}
        return {**data, **config, "node_id": str(target_node.get("id") or "").strip()}

    @staticmethod
    def _target_node_for_branch(
        *,
        nodes: dict[str, dict[str, Any]],
        outgoing_edges: list[dict[str, Any]],
        branch: str,
    ) -> dict[str, Any] | None:
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            if branch in FlowForgeRuntimeDispatcher._edge_branches(edge):
                target = str(edge.get("target") or "").strip()
                return nodes.get(target) if target else None
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            if not FlowForgeRuntimeDispatcher._edge_branches(edge):
                target = str(edge.get("target") or "").strip()
                return nodes.get(target) if target else None
        return None

    @staticmethod
    def _edge_branches(edge: dict[str, Any]) -> set[str]:
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        values: list[Any] = [edge.get("branch"), edge.get("condition"), data.get("branch"), data.get("condition")]
        for raw_list in (edge.get("branches"), data.get("branches")):
            if isinstance(raw_list, list):
                values.extend(raw_list)
        return {str(value or "").strip() for value in values if str(value or "").strip()}

    @staticmethod
    def _first_node_id(graph: dict[str, Any]) -> str | None:
        nodes = graph.get("nodes") if isinstance(graph, dict) else []
        for node in nodes:
            if isinstance(node, dict) and str(node.get("id") or "").strip():
                return str(node["id"]).strip()
        return None

    @staticmethod
    def _optional_node_id(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None
