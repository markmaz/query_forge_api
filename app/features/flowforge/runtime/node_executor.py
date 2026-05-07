from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


NodeExecutionStatus = Literal["advance", "waiting", "completed"]


class FlowForgeNodeExecutionError(Exception):
    pass


@dataclass(frozen=True)
class NodeExecutionResult:
    status: NodeExecutionStatus
    next_node_id: str | None = None
    event_payload: dict[str, Any] | None = None
    run_context_update: dict[str, Any] | None = None


class FlowForgeNodeExecutor:
    TRIGGER_NODE_TYPES = {"schedule_trigger", "webhook_trigger", "file_watch_trigger"}
    DATA_MOVEMENT_NODE_TYPES = {"query_extract", "export", "import", "map_transform"}
    SUPPORTED_NODE_TYPES = {
        *TRIGGER_NODE_TYPES,
        "intake",
        "scoring",
        "filter",
        "ranking",
        "human_task",
        "decision",
        "notification",
        "matching",
        "event_capture",
        "iterator",
        *DATA_MOVEMENT_NODE_TYPES,
        "approval",
        "wait",
        "end",
    }

    def execute(
        self,
        *,
        node: dict[str, Any],
        outgoing_edges: list[dict[str, Any]],
        run_context: dict[str, Any],
    ) -> NodeExecutionResult:
        node_id = str(node.get("id") or "").strip()
        node_type = str(node.get("type") or "").strip()
        if node_type not in self.SUPPORTED_NODE_TYPES:
            raise FlowForgeNodeExecutionError(f"Unsupported FlowForge node type '{node_type}' for node '{node_id}'.")

        if node_type == "end":
            return NodeExecutionResult(status="completed", event_payload=self._end_payload(node=node))

        if node_type in {"wait", "human_task", "approval"}:
            return NodeExecutionResult(
                status="waiting",
                next_node_id=node_id,
                event_payload={
                    "node_type": node_type,
                    "reason": "approval_required" if node_type == "approval" else "wait_node_reached",
                },
            )

        if node_type == "decision":
            return self._decision_result(node=node, outgoing_edges=outgoing_edges, run_context=run_context)

        next_node_id = self._first_target(outgoing_edges)
        if next_node_id is None:
            return NodeExecutionResult(
                status="completed",
                event_payload={"node_type": node_type, "reason": "no_outgoing_edge"},
            )

        payload = {"node_type": node_type, "next_node_id": next_node_id}
        if node_type in self.TRIGGER_NODE_TYPES:
            payload["trigger"] = self._trigger_payload(node=node)
        if node_type in self.DATA_MOVEMENT_NODE_TYPES:
            payload["data_movement"] = self._data_movement_payload(node=node)
        if node_type == "notification":
            payload["notification_dispatch"] = "queued_later"
        if node_type == "event_capture":
            payload["event_capture"] = "recorded"
        if node_type == "iterator":
            payload["iterator"] = "advanced"
        return NodeExecutionResult(status="advance", next_node_id=next_node_id, event_payload=payload)

    def _decision_result(
        self,
        *,
        node: dict[str, Any],
        outgoing_edges: list[dict[str, Any]],
        run_context: dict[str, Any],
    ) -> NodeExecutionResult:
        outcome = self._decision_outcome(node=node, run_context=run_context)
        next_node_id = self._target_for_decision(outgoing_edges=outgoing_edges, outcome=outcome)
        if next_node_id is None:
            return NodeExecutionResult(
                status="completed",
                event_payload={
                    "node_type": "decision",
                    "outcome": outcome,
                    "reason": "no_matching_decision_edge" if outcome else "no_outgoing_edge",
                },
            )
        return NodeExecutionResult(
            status="advance",
            next_node_id=next_node_id,
            event_payload={"node_type": "decision", "outcome": outcome, "next_node_id": next_node_id},
        )

    def _decision_outcome(self, *, node: dict[str, Any], run_context: dict[str, Any]) -> str | None:
        config = self._node_config(node)
        for key in ("outcome", "selected_outcome", "default_outcome"):
            value = self._optional_string(config.get(key))
            if value:
                return self._decision_outcome_alias(value)

        for context_key in ("workflow_decision", "last_decision", "human_response"):
            context_value = run_context.get(context_key) if isinstance(run_context, dict) else None
            if isinstance(context_value, dict):
                for value_key in ("outcome", "action", "branch"):
                    value = self._optional_string(context_value.get(value_key))
                    if value:
                        return self._decision_outcome_alias(value)

        for key in ("decision_outcome", "last_decision_outcome", "last_action"):
            value = self._optional_string(run_context.get(key)) if isinstance(run_context, dict) else None
            if value:
                return self._decision_outcome_alias(value)
        return None

    def _target_for_decision(self, *, outgoing_edges: list[dict[str, Any]], outcome: str | None) -> str | None:
        aliases = self._decision_aliases(outcome) if outcome else set()
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            branch = self._edge_branch(edge)
            if branch and branch in aliases:
                target = str(edge.get("target") or "").strip()
                return target or None
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            if self._edge_branch(edge):
                continue
            target = str(edge.get("target") or "").strip()
            return target or None
        return None

    @classmethod
    def _decision_aliases(cls, outcome: str | None) -> set[str]:
        if not outcome:
            return set()
        outcome_key = cls._normalize_branch(outcome)
        aliases_by_outcome = {
            "accepted": {"accept", "accepted", "approve", "approved"},
            "approved": {"accept", "accepted", "approve", "approved"},
            "declined": {"decline", "declined", "reject", "rejected", "deny", "denied"},
            "rejected": {"decline", "declined", "reject", "rejected", "deny", "denied"},
            "timed_out": {"timeout", "timed_out", "timed-out", "expired"},
            "no_match": {"no_match", "no-match", "no match"},
        }
        return aliases_by_outcome.get(outcome_key, {outcome_key})

    @classmethod
    def _decision_outcome_alias(cls, value: str) -> str:
        normalized = cls._normalize_branch(value)
        if normalized in {"accept", "approve", "approved"}:
            return "accepted"
        if normalized in {"decline", "reject", "rejected", "deny", "denied"}:
            return "declined"
        if normalized in {"timeout", "timed-out", "expired"}:
            return "timed_out"
        return normalized

    @classmethod
    def _edge_branch(cls, edge: dict[str, Any]) -> str:
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        return cls._normalize_branch(edge.get("branch") or edge.get("condition") or data.get("branch") or "")

    @staticmethod
    def _normalize_branch(value: Any) -> str:
        return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _node_config(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        return {**data, **config}

    def _trigger_payload(self, *, node: dict[str, Any]) -> dict[str, Any]:
        config = self._node_config(node)
        node_type = str(node.get("type") or "").strip()
        return {
            "trigger_type": node_type,
            "schedule": config.get("schedule") or config.get("rrule") or config.get("interval_minutes"),
            "source_key": config.get("source_key"),
        }

    def _data_movement_payload(self, *, node: dict[str, Any]) -> dict[str, Any]:
        config = self._node_config(node)
        node_type = str(node.get("type") or "").strip()
        return {
            "node_type": node_type,
            "execution_status": "side_effect_deferred",
            "source": {
                "saved_query_id": config.get("saved_query_id"),
                "semantic_plan_id": config.get("semantic_plan_id"),
                "query_builder_artifact_id": config.get("query_builder_artifact_id"),
                "source_key": config.get("source_key"),
            },
            "destination": {
                "destination_key": config.get("destination_key"),
                "destination_id": config.get("destination_id"),
            },
        }

    def _end_payload(self, *, node: dict[str, Any]) -> dict[str, Any]:
        config = self._node_config(node)
        event_key = str(config.get("event_key") or config.get("event") or "workflow_completed").strip()
        return {
            "node_type": "end",
            "event_key": event_key or "workflow_completed",
        }

    @staticmethod
    def _first_target(outgoing_edges: list[dict[str, Any]]) -> str | None:
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            target = str(edge.get("target") or "").strip()
            if target:
                return target
        return None
