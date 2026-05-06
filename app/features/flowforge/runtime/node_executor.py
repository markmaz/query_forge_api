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
        "assignment",
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
        del run_context
        node_id = str(node.get("id") or "").strip()
        node_type = str(node.get("type") or "").strip()
        if node_type not in self.SUPPORTED_NODE_TYPES:
            raise FlowForgeNodeExecutionError(f"Unsupported FlowForge node type '{node_type}' for node '{node_id}'.")

        if node_type in {"end", "assignment"}:
            return NodeExecutionResult(status="completed", event_payload={"node_type": node_type})

        if node_type in {"wait", "human_task", "approval"}:
            return NodeExecutionResult(
                status="waiting",
                next_node_id=node_id,
                event_payload={
                    "node_type": node_type,
                    "reason": "approval_required" if node_type == "approval" else "wait_node_reached",
                },
            )

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

    @staticmethod
    def _first_target(outgoing_edges: list[dict[str, Any]]) -> str | None:
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            target = str(edge.get("target") or "").strip()
            if target:
                return target
        return None
