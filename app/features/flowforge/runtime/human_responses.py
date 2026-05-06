from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import FRONTEND_BASE_URL
from app.features.flowforge.repositories import FlowForgeResourceRepository, FlowForgeRuntimeRepository, FlowForgeWorkflowRepository

DispatchEnqueuer = Callable[[str, int], Any]


class FlowForgeHumanResponseRuntime:
    def __init__(
        self,
        *,
        runtime_repository: FlowForgeRuntimeRepository | None = None,
        workflow_repository: FlowForgeWorkflowRepository | None = None,
        resource_repository: FlowForgeResourceRepository | None = None,
        enqueue_dispatch: DispatchEnqueuer | None = None,
    ) -> None:
        self._runtime_repository = runtime_repository or FlowForgeRuntimeRepository()
        self._workflow_repository = workflow_repository or FlowForgeWorkflowRepository()
        self._resource_repository = resource_repository or FlowForgeResourceRepository()
        self._enqueue_dispatch = enqueue_dispatch or self._enqueue_run_dispatch

    def advance_after_human_action(
        self,
        *,
        workspace_id: str,
        run_id: int,
        action: str,
        human_task_id: int | None = None,
        resource_set_id: int | None = None,
        source_record_key: str | None = None,
    ) -> dict[str, Any]:
        run = self._runtime_repository.get_run(workspace_id=workspace_id, run_id=run_id)
        if run is None:
            return {"status": "not_found", "run_id": int(run_id)}
        current_node_id = str(run.get("current_node_id") or "").strip()
        if not current_node_id:
            return {"status": "no_current_node", "run_id": int(run_id)}
        normalized_action = self._normalize_action(action)
        if normalized_action == "accept":
            self._mark_assignment(
                workspace_id=workspace_id,
                resource_set_id=resource_set_id,
                source_record_key=source_record_key,
            )
            assignment_id = self._create_assignment_record(
                workspace_id=workspace_id,
                run_id=int(run_id),
                human_task_id=human_task_id,
                resource_set_id=resource_set_id,
                source_record_key=source_record_key,
            )
        else:
            assignment_id = None
        if normalized_action in {"decline", "timeout"}:
            self._mark_decline(
                workspace_id=workspace_id,
                resource_set_id=resource_set_id,
                source_record_key=source_record_key,
            )
            next_offer = self._offer_next_candidate(
                workspace_id=workspace_id,
                run_id=int(run_id),
                run=run,
                previous_source_record_key=source_record_key,
                action=normalized_action,
            )
            if next_offer is not None:
                if next_offer.get("status") == "candidate_pool_exhausted":
                    normalized_action = "no_match"
                else:
                    return next_offer

        graph = self._load_graph(workspace_id=workspace_id, run=run)
        target_node_id = self._target_for_action(
            edges=self._outgoing_edges(graph=graph, node_id=current_node_id),
            action=normalized_action,
        )
        if target_node_id is None:
            return {
                "status": "candidate_pool_exhausted" if normalized_action == "no_match" else "no_target",
                "run_id": int(run_id),
                "from_node_id": current_node_id,
                "action": normalized_action,
            }

        self._runtime_repository.update_run_status(
            workspace_id=workspace_id,
            run_id=int(run_id),
            status="waiting",
            current_node_id=target_node_id,
        )
        self._runtime_repository.append_run_event(
            workspace_id=workspace_id,
            run_id=int(run_id),
            event_type="workflow.human_response.advance",
            node_id=current_node_id,
            message="Human response advanced workflow run.",
            event_payload={
                "human_task_id": int(human_task_id) if human_task_id is not None else None,
                "action": normalized_action,
                "source_record_key": source_record_key,
                "from_node_id": current_node_id,
                "to_node_id": target_node_id,
                "assignment_id": assignment_id,
            },
            actor_type="system",
            actor_id="flowforge",
            idempotency_key=(
                f"run:{int(run_id)}:human-response:{human_task_id or 'unknown'}:"
                f"{normalized_action}:advance"
            ),
        )
        self._enqueue_dispatch(workspace_id, int(run_id))
        return {
            "status": "advanced",
            "run_id": int(run_id),
            "from_node_id": current_node_id,
            "to_node_id": target_node_id,
            "action": normalized_action,
            "assignment_id": assignment_id,
        }

    def dispatch_due_timeouts(self, *, limit: int = 50) -> dict[str, Any]:
        tasks = self._runtime_repository.list_due_human_tasks(limit=max(1, min(int(limit or 50), 200)))
        advanced = 0
        for task in tasks:
            workspace_id = str(task.get("workspace_id") or "").strip()
            run_id = int(task["run_id"])
            human_task_id = int(task["id"])
            response = {"action": "timeout", "timeout": True}
            self._runtime_repository.update_human_task_response(
                workspace_id=workspace_id,
                human_task_id=human_task_id,
                status="timed_out",
                response=response,
            )
            self._runtime_repository.append_run_event(
                workspace_id=workspace_id,
                run_id=run_id,
                event_type="workflow.human_task.timed_out",
                node_id=None,
                message="Human task timed out.",
                event_payload={
                    "human_task_id": human_task_id,
                    "source_record_key": task.get("source_record_key"),
                },
                actor_type="system",
                actor_id="flowforge",
                idempotency_key=f"human-task:{human_task_id}:timeout",
            )
            result = self.advance_after_human_action(
                workspace_id=workspace_id,
                run_id=run_id,
                action="timeout",
                human_task_id=human_task_id,
                resource_set_id=task.get("resource_set_id"),
                source_record_key=task.get("source_record_key"),
            )
            if result.get("status") == "advanced":
                advanced += 1
        return {"status": "completed", "processed": len(tasks), "advanced": advanced}

    def _load_graph(self, *, workspace_id: str, run: dict[str, Any]) -> dict[str, Any]:
        version = self._workflow_repository.get_workflow_version(
            workspace_id=workspace_id,
            workflow_definition_id=int(run["workflow_definition_id"]),
            version_id=int(run["workflow_version_id"]),
        )
        if version is None:
            return {}
        graph = version.get("graph") or version.get("graph_json") or {}
        return graph if isinstance(graph, dict) else {}

    def _target_for_action(self, *, edges: list[dict[str, Any]], action: str) -> str | None:
        action_key = self._normalize_action(action)
        aliases = self._action_aliases(action_key)
        for edge in sorted(edges, key=lambda row: str(row.get("id") or "")):
            branch = self._edge_branch(edge)
            if branch in aliases:
                target = str(edge.get("target") or "").strip()
                return target or None
        if action_key in {"accept", "approve"}:
            for edge in sorted(edges, key=lambda row: str(row.get("id") or "")):
                if self._edge_branch(edge):
                    continue
                target = str(edge.get("target") or "").strip()
                return target or None
        return None

    @staticmethod
    def _action_aliases(action_key: str) -> set[str]:
        aliases_by_action = {
            "accept": {"accept", "accepted", "approve", "approved"},
            "approve": {"approve", "approved", "accept", "accepted"},
            "decline": {"decline", "declined", "reject", "rejected", "deny", "denied"},
            "reject": {"reject", "rejected", "decline", "declined", "deny", "denied"},
            "timeout": {"timeout", "timed_out", "expired"},
            "no_match": {"no_match", "no-match", "no match"},
        }
        return aliases_by_action.get(action_key, {action_key})

    @staticmethod
    def _outgoing_edges(*, graph: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
        edges = graph.get("edges") if isinstance(graph, dict) else []
        return [
            dict(edge)
            for edge in edges
            if isinstance(edge, dict) and str(edge.get("source") or "").strip() == node_id
        ]

    @staticmethod
    def _edge_branch(edge: dict[str, Any]) -> str:
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        return str(edge.get("branch") or edge.get("condition") or data.get("branch") or "").strip().lower()

    @staticmethod
    def _normalize_action(action: str) -> str:
        return str(action or "").strip().lower()

    def _offer_next_candidate(
        self,
        *,
        workspace_id: str,
        run_id: int,
        run: dict[str, Any],
        previous_source_record_key: str | None,
        action: str,
    ) -> dict[str, Any] | None:
        context = dict(run.get("run_context") or run.get("run_context_json") or {})
        matching_context = dict(context.get("flowforge_matching") or {})
        candidate_keys = [str(value or "").strip() for value in matching_context.get("candidate_keys") or []]
        if not matching_context:
            return None
        if not candidate_keys:
            return {"status": "candidate_pool_exhausted", "run_id": run_id, "action": action}
        current_index = int(matching_context.get("current_candidate_index") or 0)
        exhausted = [str(value or "").strip() for value in matching_context.get("exhausted_candidate_keys") or []]
        if previous_source_record_key and previous_source_record_key not in exhausted:
            exhausted.append(previous_source_record_key)
        next_index = current_index + 1
        if next_index >= len(candidate_keys):
            matching_context["current_candidate_index"] = next_index
            matching_context["exhausted_candidate_keys"] = exhausted
            matching_context["selected_source_record_key"] = None
            context["flowforge_matching"] = matching_context
            self._runtime_repository.update_run_context(
                workspace_id=workspace_id,
                run_id=run_id,
                run_context=context,
            )
            return {"status": "candidate_pool_exhausted", "run_id": run_id, "action": action}

        resource_set_id = int(matching_context.get("resource_set_id") or 0)
        snapshot_batch_id = int(matching_context.get("snapshot_batch_id") or 0)
        source_record_key = candidate_keys[next_index]
        resource = self._resource_repository.get_snapshot_record(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            snapshot_batch_id=snapshot_batch_id,
            source_record_key=source_record_key,
        )
        if resource is None:
            return None
        matching_context["current_candidate_index"] = next_index
        matching_context["exhausted_candidate_keys"] = exhausted
        matching_context["selected_source_record_key"] = source_record_key
        context["flowforge_matching"] = matching_context
        self._runtime_repository.update_run_context(
            workspace_id=workspace_id,
            run_id=run_id,
            run_context=context,
        )
        offer = self._create_offer(
            workspace_id=workspace_id,
            run_id=run_id,
            resource_set_id=resource_set_id,
            source_record_key=source_record_key,
            resource=resource,
            matching_context=matching_context,
        )
        self._runtime_repository.append_run_event(
            workspace_id=workspace_id,
            run_id=run_id,
            event_type="workflow.offer.next_candidate",
            node_id=str(run.get("current_node_id") or "").strip() or None,
            message="FlowForge offered the next candidate.",
            event_payload={
                "action": action,
                "previous_source_record_key": previous_source_record_key,
                "source_record_key": source_record_key,
                "human_task_id": offer["human_task_id"],
            },
            actor_type="system",
            actor_id="flowforge",
            idempotency_key=f"run:{run_id}:offer:{source_record_key}:next",
        )
        return {
            "status": "next_candidate_offered",
            "run_id": run_id,
            "source_record_key": source_record_key,
            "human_task_id": offer["human_task_id"],
            "action": action,
        }

    def _create_offer(
        self,
        *,
        workspace_id: str,
        run_id: int,
        resource_set_id: int,
        source_record_key: str,
        resource: dict[str, Any],
        matching_context: dict[str, Any],
    ) -> dict[str, Any]:
        timeout_minutes = max(1, int(matching_context.get("offer_timeout_minutes") or 1440))
        template_key = str(matching_context.get("communication_template_key") or "flowforge.human_task").strip()
        due_at = datetime.now(UTC) + timedelta(minutes=timeout_minutes)
        task_idempotency_key = f"run:{run_id}:offer:{source_record_key}:task"
        task_id = self._runtime_repository.create_human_task(
            workspace_id=workspace_id,
            run_id=run_id,
            task_type="offer",
            resource_set_id=resource_set_id,
            source_record_key=source_record_key,
            status="pending",
            assigned_to_principal_type="resource",
            assigned_to_principal_id=source_record_key,
            due_at=due_at,
            response={"allowed_actions": ["accept", "decline"], "matching_context": matching_context},
            idempotency_key=task_idempotency_key,
        )
        token = f"ffact_{secrets.token_urlsafe(32)}"
        self._runtime_repository.create_signed_action_token(
            workspace_id=workspace_id,
            human_task_id=task_id,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            allowed_actions=["accept", "decline"],
            expires_at=due_at,
        )
        self._resource_repository.mark_resource_offered(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            source_record_key=source_record_key,
        )
        recipient = self._recipient_for_resource(resource)
        notification_id = None
        if recipient:
            notification_id = self._runtime_repository.create_notification(
                workspace_id=workspace_id,
                run_id=run_id,
                human_task_id=task_id,
                channel="email",
                recipient=recipient,
                template_key=template_key,
                status="pending",
                idempotency_key=f"run:{run_id}:offer:{task_id}:notification",
                payload_summary={
                    "resource_display_name": resource.get("display_name"),
                    "source_record_key": source_record_key,
                    "action_url": self._action_url(token),
                    "expires_at": due_at.isoformat(),
                },
            )
        return {"human_task_id": int(task_id), "notification_id": notification_id}

    def _mark_assignment(
        self,
        *,
        workspace_id: str,
        resource_set_id: int | None,
        source_record_key: str | None,
    ) -> None:
        if resource_set_id and source_record_key:
            self._resource_repository.mark_resource_assigned(
                workspace_id=workspace_id,
                resource_set_id=int(resource_set_id),
                source_record_key=source_record_key,
            )

    def _create_assignment_record(
        self,
        *,
        workspace_id: str,
        run_id: int,
        human_task_id: int | None,
        resource_set_id: int | None,
        source_record_key: str | None,
    ) -> int | None:
        if not resource_set_id or not source_record_key:
            return None
        return self._runtime_repository.create_assignment(
            workspace_id=workspace_id,
            run_id=run_id,
            human_task_id=human_task_id,
            resource_set_id=int(resource_set_id),
            source_record_key=source_record_key,
            status="assigned",
            assignment={"source": "signed_action"},
            idempotency_key=f"run:{run_id}:assignment:{source_record_key}",
        )

    def _mark_decline(
        self,
        *,
        workspace_id: str,
        resource_set_id: int | None,
        source_record_key: str | None,
    ) -> None:
        if resource_set_id and source_record_key:
            self._resource_repository.mark_resource_declined(
                workspace_id=workspace_id,
                resource_set_id=int(resource_set_id),
                source_record_key=source_record_key,
            )

    @staticmethod
    def _recipient_for_resource(resource: dict[str, Any]) -> str | None:
        for key in ("primary_email", "email"):
            value = str(resource.get(key) or "").strip()
            if value:
                return value
        profile = resource.get("normalized_profile_json") or resource.get("normalized_profile") or {}
        if isinstance(profile, dict):
            value = str(profile.get("primary_email") or profile.get("email") or "").strip()
            if value:
                return value
        return None

    @staticmethod
    def _action_url(token: str) -> str:
        return f"{str(FRONTEND_BASE_URL or '').rstrip('/')}/flowforge/actions/{token}"

    @staticmethod
    def _enqueue_run_dispatch(workspace_id: str, run_id: int) -> None:
        from app.tasks.flowforge_tasks import enqueue_flowforge_run_dispatch

        enqueue_flowforge_run_dispatch(workspace_id=workspace_id, run_id=int(run_id))
