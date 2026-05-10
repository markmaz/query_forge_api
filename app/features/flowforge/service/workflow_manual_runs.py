from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from app.exceptions.forge_error import ForgeError

logger = logging.getLogger(__name__)


class FlowForgeWorkflowManualRunServiceMixin:
    def start_workflow_run(
        self,
        *,
        workspace_id: str,
        workflow_definition_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
        effective_roles: set[str] | None = None,
    ) -> dict[str, Any]:
        definition = self._workflow_definition_or_404(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
        )
        self._ensure_workflow_permission(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            effective_roles=effective_roles,
            workflow_definition=definition,
            required_permission="run",
        )
        version_id = self._positive_int(definition.get("latest_published_version_id"), field_name="latest_published_version_id")
        version = self._workflow_repository.get_workflow_version(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
            version_id=version_id,
        )
        if version is None or str(version.get("version_status") or "") != "published":
            raise ForgeError("Workflow must have a published version before it can run.", status_code=400)
        graph = version.get("graph") or version.get("graph_json") or {}
        mode = str(payload.get("mode") or "test").strip().lower()
        if mode not in {"test", "production"}:
            raise ForgeError("mode must be test or production.", status_code=400)
        start_node_id = str(payload.get("start_node_id") or "").strip() or self._first_workflow_node_id(graph=graph)
        if not start_node_id:
            raise ForgeError("Workflow graph must contain a start node.", status_code=400)
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not idempotency_key:
            idempotency_key = f"manual:{workflow_definition_id}:{version_id}:{uuid4()}"
        existing = self._runtime_repository.get_run_by_idempotency(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return {
                "run_id": int(existing["id"]),
                "workflow_definition_id": workflow_definition_id,
                "workflow_version_id": version_id,
                "status": existing.get("status") or "waiting",
                "mode": existing.get("mode") or mode,
                "current_node_id": existing.get("current_node_id"),
                "idempotency_key": idempotency_key,
                "created": False,
            }
        run_context = {
            "source": "manual",
            "manual": True,
            "input": payload.get("input") if isinstance(payload.get("input"), dict) else {},
            "started_by_user_id": actor_user_id,
        }
        run_id = self._runtime_repository.create_run(
            workspace_id=workspace_id,
            workflow_definition_id=workflow_definition_id,
            workflow_version_id=version_id,
            intake_event_id=None,
            mode=mode,
            status="waiting",
            current_node_id=start_node_id,
            idempotency_key=idempotency_key,
            run_context=run_context,
            run_as_principal_type=str(definition.get("run_as_principal_type") or "").strip() or None,
            run_as_principal_id=str(definition.get("run_as_principal_id") or "").strip() or None,
            triggered_by_user_id=self._optional_string(actor_user_id),
        )
        self._runtime_repository.append_run_event(
            workspace_id=workspace_id,
            run_id=run_id,
            event_type="workflow.run.created",
            node_id=start_node_id,
            message="Workflow run created manually.",
            event_payload={
                "workflow_definition_id": workflow_definition_id,
                "workflow_version_id": version_id,
                "mode": mode,
                "run_as_principal_type": str(definition.get("run_as_principal_type") or "").strip() or None,
                "run_as_principal_id": str(definition.get("run_as_principal_id") or "").strip() or None,
                "triggered_by_user_id": actor_user_id,
            },
            actor_type="user",
            actor_id=actor_user_id,
            idempotency_key=f"{idempotency_key}:event:created",
        )
        self._enqueue_manual_run_dispatch(workspace_id=workspace_id, run_id=int(run_id), idempotency_key=idempotency_key)
        return {
            "run_id": int(run_id),
            "workflow_definition_id": workflow_definition_id,
            "workflow_version_id": version_id,
            "status": "waiting",
            "mode": mode,
            "current_node_id": start_node_id,
            "idempotency_key": idempotency_key,
            "created": True,
        }

    @staticmethod
    def _first_workflow_node_id(*, graph: dict[str, Any]) -> str | None:
        nodes = graph.get("nodes") if isinstance(graph, dict) else []
        if not isinstance(nodes, list):
            return None
        for node in nodes:
            if isinstance(node, dict):
                node_id = str(node.get("id") or "").strip()
                if node_id:
                    return node_id
        return None

    def _enqueue_manual_run_dispatch(self, *, workspace_id: str, run_id: int, idempotency_key: str) -> None:
        try:
            from app.tasks.flowforge_tasks import enqueue_flowforge_run_dispatch

            enqueue_flowforge_run_dispatch(workspace_id=workspace_id, run_id=int(run_id))
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "FlowForge manual run dispatch enqueue failed workspace_id=%s run_id=%s",
                workspace_id,
                run_id,
            )
            self._runtime_repository.append_run_event(
                workspace_id=workspace_id,
                run_id=run_id,
                event_type="workflow.dispatch.enqueue_failed",
                node_id=None,
                message="Workflow run dispatch enqueue failed.",
                event_payload={"error": str(exc)},
                actor_type="system",
                actor_id="flowforge",
                idempotency_key=f"{idempotency_key}:event:dispatch_enqueue_failed",
            )
