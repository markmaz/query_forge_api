from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from app.config import FRONTEND_BASE_URL
from app.features.flowforge.matching import MatchingPolicyEngine
from app.features.flowforge.repositories import (
    FlowForgeMatchingRepository,
    FlowForgeResourceRepository,
    FlowForgeRuntimeRepository,
)
from app.features.flowforge.runtime.node_executor import FlowForgeNodeExecutionError, NodeExecutionResult


class FlowForgeRuntimeMatchingExecutor:
    def __init__(
        self,
        *,
        runtime_repository: FlowForgeRuntimeRepository | None = None,
        matching_repository: FlowForgeMatchingRepository | None = None,
        resource_repository: FlowForgeResourceRepository | None = None,
        matching_engine: MatchingPolicyEngine | None = None,
    ) -> None:
        self._runtime_repository = runtime_repository or FlowForgeRuntimeRepository()
        self._matching_repository = matching_repository or FlowForgeMatchingRepository()
        self._resource_repository = resource_repository or FlowForgeResourceRepository()
        self._matching_engine = matching_engine or MatchingPolicyEngine()

    def execute(
        self,
        *,
        workspace_id: str,
        run_id: int,
        run_mode: str,
        node: dict[str, Any],
        outgoing_edges: list[dict[str, Any]],
        run_context: dict[str, Any],
        offer_config: dict[str, Any] | None = None,
    ) -> NodeExecutionResult:
        config = self._node_config(node)
        policy_version = self._resolve_policy_version(workspace_id=workspace_id, config=config)
        if str(policy_version.get("version_status") or "") != "published":
            raise FlowForgeNodeExecutionError("Matching policy version must be published before runtime execution.")

        resource_set_id = int(policy_version.get("resource_set_id") or config.get("resource_set_id") or 0)
        if resource_set_id < 1:
            raise FlowForgeNodeExecutionError("Matching node did not resolve a resource set.")
        resource_set = self._resource_repository.get_resource_set(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
        )
        if resource_set is None:
            raise FlowForgeNodeExecutionError("Matching node resource set was not found.")

        snapshot_batch_id = int(config.get("snapshot_batch_id") or resource_set.get("active_snapshot_batch_id") or 0)
        if snapshot_batch_id < 1:
            raise FlowForgeNodeExecutionError("Matching node resource set has no active snapshot batch.")

        resources = self._resource_repository.list_snapshot_records_for_batch(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            snapshot_batch_id=snapshot_batch_id,
            limit=5000,
        )
        policy = policy_version.get("policy") or policy_version.get("policy_json") or {}
        result = self._matching_engine.simulate(policy=policy, resources=resources, context=run_context)
        selected = result.get("selected_candidate") or None
        evaluation_id = self._runtime_repository.create_matching_evaluation(
            workspace_id=workspace_id,
            run_id=run_id,
            matching_policy_version_id=int(policy_version["id"]),
            resource_set_id=resource_set_id,
            snapshot_batch_id=snapshot_batch_id,
            input_context=run_context,
            summary=self._summary(result=result, run_mode=run_mode),
            selected_source_record_key=selected.get("source_record_key") if isinstance(selected, dict) else None,
            no_match_reason=result.get("no_match_reason"),
            status="completed" if result.get("valid") else "failed",
        )
        for candidate in (result.get("ranked_candidates") or []) + (result.get("excluded_candidates") or []):
            if isinstance(candidate, dict):
                self._runtime_repository.create_matching_evaluation_candidate(
                    workspace_id=workspace_id,
                    matching_evaluation_id=evaluation_id,
                    resource_set_id=resource_set_id,
                    candidate=candidate,
                    selected=bool(
                        isinstance(selected, dict)
                        and candidate.get("source_record_key") == selected.get("source_record_key")
                    ),
                )

        branch = "matched" if selected else "no_match"
        runtime_context = self._persist_matching_context(
            workspace_id=workspace_id,
            run_id=run_id,
            run_context=run_context,
            node=node,
            offer_config=offer_config,
            result=result,
            evaluation_id=evaluation_id,
            resource_set_id=resource_set_id,
            snapshot_batch_id=snapshot_batch_id,
        )
        offer_summary = None
        if isinstance(selected, dict):
            selected_resource = self._resource_by_key(
                resources=resources,
                source_record_key=str(selected.get("source_record_key") or ""),
            )
            offer_summary = self._create_offer_for_candidate(
                workspace_id=workspace_id,
                run_id=run_id,
                node=node,
                run_context=runtime_context,
                offer_config=offer_config,
                resource_set_id=resource_set_id,
                selected_candidate=selected,
                selected_resource=selected_resource,
            )
        next_node_id = self._target_for_branch(outgoing_edges=outgoing_edges, branch=branch)
        return NodeExecutionResult(
            status="advance" if next_node_id else "completed",
            next_node_id=next_node_id,
            event_payload={
                "node_type": "matching",
                "matching_evaluation_id": evaluation_id,
                "matching_policy_version_id": int(policy_version["id"]),
                "resource_set_id": resource_set_id,
                "snapshot_batch_id": snapshot_batch_id,
                "selected_source_record_key": selected.get("source_record_key") if isinstance(selected, dict) else None,
                "no_match_reason": result.get("no_match_reason"),
                "branch": branch,
                "next_node_id": next_node_id,
                "offer": offer_summary,
            },
            run_context_update=runtime_context,
        )

    def _resolve_policy_version(self, *, workspace_id: str, config: dict[str, Any]) -> dict[str, Any]:
        version_id = int(config.get("matching_policy_version_id") or 0)
        if version_id > 0:
            version = self._matching_repository.get_policy_version(workspace_id=workspace_id, version_id=version_id)
            if version is None:
                raise FlowForgeNodeExecutionError("Matching policy version was not found.")
            return version

        policy_id = int(config.get("matching_policy_id") or 0)
        if policy_id < 1:
            raise FlowForgeNodeExecutionError("Matching node requires matching_policy_version_id or matching_policy_id.")
        policy = self._matching_repository.get_policy(workspace_id=workspace_id, matching_policy_id=policy_id)
        if policy is None or not policy.get("latest_published_version_id"):
            raise FlowForgeNodeExecutionError("Matching policy does not have a published version.")
        version = self._matching_repository.get_policy_version(
            workspace_id=workspace_id,
            version_id=int(policy["latest_published_version_id"]),
        )
        if version is None:
            raise FlowForgeNodeExecutionError("Published matching policy version was not found.")
        return version

    @staticmethod
    def _node_config(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        return {**data, **config}

    @staticmethod
    def _target_for_branch(*, outgoing_edges: list[dict[str, Any]], branch: str) -> str | None:
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            if branch in FlowForgeRuntimeMatchingExecutor._edge_branches(edge):
                target = str(edge.get("target") or "").strip()
                return target or None
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            if not FlowForgeRuntimeMatchingExecutor._edge_branches(edge):
                target = str(edge.get("target") or "").strip()
                return target or None
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
    def _summary(*, result: dict[str, Any], run_mode: str) -> dict[str, Any]:
        return {
            "mode": run_mode,
            "eligible_count": len(result.get("eligible_candidates") or []),
            "excluded_count": len(result.get("excluded_candidates") or []),
            "ranked_count": len(result.get("ranked_candidates") or []),
            "no_match_reason": result.get("no_match_reason"),
            "valid": bool(result.get("valid")),
        }

    def _persist_matching_context(
        self,
        *,
        workspace_id: str,
        run_id: int,
        run_context: dict[str, Any],
        node: dict[str, Any],
        offer_config: dict[str, Any] | None,
        result: dict[str, Any],
        evaluation_id: int,
        resource_set_id: int,
        snapshot_batch_id: int,
    ) -> dict[str, Any]:
        ranked = [row for row in result.get("ranked_candidates") or [] if isinstance(row, dict)]
        config = self._offer_config(node=node, offer_config=offer_config)
        context = dict(run_context)
        context["flowforge_matching"] = {
            "node_id": str(node.get("id") or "").strip(),
            "matching_evaluation_id": int(evaluation_id),
            "resource_set_id": int(resource_set_id),
            "snapshot_batch_id": int(snapshot_batch_id),
            "candidate_keys": [str(row.get("source_record_key") or "").strip() for row in ranked],
            "current_candidate_index": 0,
            "exhausted_candidate_keys": [],
            "selected_source_record_key": (
                str(ranked[0].get("source_record_key") or "").strip() if ranked else None
            ),
            "offer_timeout_minutes": max(1, int(config.get("timeout_minutes") or config.get("offer_timeout_minutes") or 1440)),
            "communication_template_key": str(config.get("communication_template_key") or "flowforge.human_task").strip(),
            "communication_context": run_context.get("communication_context")
            if isinstance(run_context.get("communication_context"), dict)
            else {},
            "communication_fields": run_context.get("communication_fields")
            if isinstance(run_context.get("communication_fields"), list)
            else [],
        }
        self._runtime_repository.update_run_context(
            workspace_id=workspace_id,
            run_id=run_id,
            run_context=context,
        )
        return context

    def _create_offer_for_candidate(
        self,
        *,
        workspace_id: str,
        run_id: int,
        node: dict[str, Any],
        run_context: dict[str, Any],
        offer_config: dict[str, Any] | None,
        resource_set_id: int,
        selected_candidate: dict[str, Any],
        selected_resource: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        source_record_key = str(selected_candidate.get("source_record_key") or "").strip()
        if not source_record_key:
            return None
        config = self._offer_config(node=node, offer_config=offer_config)
        timeout_minutes = max(1, int(config.get("timeout_minutes") or config.get("offer_timeout_minutes") or 1440))
        template_key = str(config.get("communication_template_key") or "flowforge.human_task").strip()
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
            response={
                "allowed_actions": ["accept", "decline"],
                "matching_context": run_context.get("flowforge_matching") or {},
            },
            idempotency_key=task_idempotency_key,
        )
        token = f"ffact_{secrets.token_urlsafe(32)}"
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self._runtime_repository.create_signed_action_token(
            workspace_id=workspace_id,
            human_task_id=task_id,
            token_hash=token_hash,
            allowed_actions=["accept", "decline"],
            expires_at=due_at,
        )
        self._resource_repository.mark_resource_offered(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            source_record_key=source_record_key,
        )
        recipient = self._recipient_for_resource(selected_resource)
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
                    "intake": self._communication_intake_context(run_context),
                    "selected_resource": self._notification_resource_context(
                        selected_resource=selected_resource,
                        selected_candidate=selected_candidate,
                    ),
                    "resource_display_name": selected_candidate.get("display_name"),
                    "source_record_key": source_record_key,
                    "action_url": self._action_url(token),
                    "action_urls": self._action_urls(token, allowed_actions=["accept", "decline"]),
                    "expires_at": due_at.isoformat(),
                },
            )
        self._runtime_repository.append_run_event(
            workspace_id=workspace_id,
            run_id=run_id,
            event_type="workflow.offer.created",
            node_id=str(node.get("id") or "").strip() or None,
            message="FlowForge offer human task created.",
            event_payload={
                "human_task_id": int(task_id),
                "notification_id": notification_id,
                "source_record_key": source_record_key,
                "timeout_minutes": timeout_minutes,
            },
            actor_type="system",
            actor_id="flowforge",
            idempotency_key=f"run:{run_id}:offer:{source_record_key}:created",
        )
        return {
            "human_task_id": int(task_id),
            "notification_id": notification_id,
            "source_record_key": source_record_key,
            "expires_at": due_at.isoformat(),
        }

    @classmethod
    def _offer_config(cls, *, node: dict[str, Any], offer_config: dict[str, Any] | None) -> dict[str, Any]:
        node_config = cls._node_config(node)
        return {**node_config, **(offer_config or {})}

    @staticmethod
    def _resource_by_key(*, resources: list[dict[str, Any]], source_record_key: str) -> dict[str, Any] | None:
        for resource in resources:
            if str(resource.get("source_record_key") or "").strip() == source_record_key:
                return resource
        return None

    @staticmethod
    def _communication_intake_context(run_context: dict[str, Any]) -> dict[str, Any]:
        communication_context = run_context.get("communication_context")
        if not isinstance(communication_context, dict):
            return {}
        intake = communication_context.get("intake")
        return dict(intake) if isinstance(intake, dict) else {}

    @staticmethod
    def _notification_resource_context(
        *,
        selected_resource: dict[str, Any] | None,
        selected_candidate: dict[str, Any],
    ) -> dict[str, Any]:
        source = selected_resource if isinstance(selected_resource, dict) else selected_candidate
        allowed_keys = {
            "source_record_key",
            "display_name",
            "primary_email",
            "primary_phone",
            "availability_status",
            "capacity_available",
            "service_area",
            "timezone",
            "attributes",
            "normalized_profile",
        }
        return {key: source.get(key) for key in allowed_keys if source.get(key) is not None}

    @staticmethod
    def _recipient_for_resource(resource: dict[str, Any] | None) -> str | None:
        if not isinstance(resource, dict):
            return None
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

    @classmethod
    def _action_urls(cls, token: str, *, allowed_actions: list[str]) -> dict[str, str]:
        base_url = cls._action_url(token)
        action_urls = {"open_task": base_url}
        for action in allowed_actions:
            action_key = str(action or "").strip().lower()
            if action_key:
                action_urls[action_key] = f"{base_url}?{urlencode({'action': action_key})}"
        return action_urls
