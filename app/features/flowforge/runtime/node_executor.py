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
        "manual_start",
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
            if node_type == "event_capture":
                payload = self._event_capture_payload(node=node, run_context=run_context, next_node_id=None)
                payload["terminal_reason"] = "no_outgoing_edge"
                return NodeExecutionResult(status="completed", event_payload=payload)
            return NodeExecutionResult(
                status="completed",
                event_payload={"node_type": node_type, "reason": "no_outgoing_edge"},
            )

        payload = {"node_type": node_type, "next_node_id": next_node_id}
        if node_type == "manual_start":
            payload["manual_start"] = True
        if node_type in self.TRIGGER_NODE_TYPES:
            payload["trigger"] = self._trigger_payload(node=node)
        if node_type in self.DATA_MOVEMENT_NODE_TYPES:
            payload["data_movement"] = self._data_movement_payload(node=node)
        if node_type == "notification":
            payload["notification_dispatch"] = "queued_later"
        if node_type == "event_capture":
            payload = self._event_capture_payload(node=node, run_context=run_context, next_node_id=next_node_id)
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

        context_candidates: list[dict[str, Any]] = []
        for context_key in ("workflow_decision", "last_decision", "human_response"):
            context_value = run_context.get(context_key) if isinstance(run_context, dict) else None
            if isinstance(context_value, dict):
                context_candidates.append(context_value)
        last_output_data = self._path_value(run_context, "last_node_output.data") if isinstance(run_context, dict) else None
        if isinstance(last_output_data, dict):
            context_candidates.append(last_output_data)

        for context_value in context_candidates:
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
            if self._edge_branches(edge) & aliases:
                target = str(edge.get("target") or "").strip()
                return target or None
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            if self._edge_branches(edge):
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
    def _edge_branches(cls, edge: dict[str, Any]) -> set[str]:
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        values: list[Any] = [edge.get("branch"), edge.get("condition"), data.get("branch"), data.get("condition")]
        for raw_list in (edge.get("branches"), data.get("branches")):
            if isinstance(raw_list, list):
                values.extend(raw_list)
        return {normalized for value in values if (normalized := cls._normalize_branch(value))}

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

    def _event_capture_payload(
        self,
        *,
        node: dict[str, Any],
        run_context: dict[str, Any],
        next_node_id: str | None,
    ) -> dict[str, Any]:
        config = self._node_config(node)
        requested = self._capture_fields(config.get("captures") or config.get("capture_fields"))
        captured: dict[str, Any] = {}
        sources: dict[str, str] = {}
        context = run_context if isinstance(run_context, dict) else {}

        for field in requested:
            value, source = self._capture_value(field=field, config=config, run_context=context)
            if not self._has_capture_value(value):
                continue
            captured[field] = value
            if source:
                sources[field] = source

        event_key = self._optional_string(config.get("event_key") or config.get("event_name") or config.get("event"))
        payload: dict[str, Any] = {
            "node_type": "event_capture",
            "event_capture": "recorded",
            "captures_requested": requested,
            "captured": captured,
        }
        if sources:
            payload["capture_sources"] = sources
        if event_key:
            payload["event_key"] = event_key
        if next_node_id:
            payload["next_node_id"] = next_node_id
        return payload

    def _capture_value(
        self,
        *,
        field: str,
        config: dict[str, Any],
        run_context: dict[str, Any],
    ) -> tuple[Any, str | None]:
        normalized = self._normalize_capture_field(field)
        if "." in field:
            return self._first_capture_value(run_context, [(field, field)])

        candidates_by_field: dict[str, list[tuple[str, str]]] = {
            "reason": [
                ("workflow_decision.reason", "workflow_decision.reason"),
                ("workflow_decision.decline_reason", "workflow_decision.decline_reason"),
                ("workflow_decision.decision_note", "workflow_decision.decision_note"),
                ("workflow_decision.response_note", "workflow_decision.response_note"),
                ("human_response.reason", "human_response.reason"),
                ("human_response.decline_reason", "human_response.decline_reason"),
                ("human_response.decision_note", "human_response.decision_note"),
                ("human_response.response_note", "human_response.response_note"),
                ("flowforge_matching.no_match_reason", "flowforge_matching.no_match_reason"),
                ("notification.reason", "notification.reason"),
                ("last_notification.reason", "last_notification.reason"),
                ("communication_context.reason", "communication_context.reason"),
                ("last_node_output.data.reason", "last_node_output.data.reason"),
                ("last_node_output.data.no_match_reason", "last_node_output.data.no_match_reason"),
                ("last_node_output.data.captured.reason", "last_node_output.data.captured.reason"),
            ],
            "decline_reason": [
                ("workflow_decision.decline_reason", "workflow_decision.decline_reason"),
                ("human_response.decline_reason", "human_response.decline_reason"),
                ("approval.decline_reason", "approval.decline_reason"),
                ("decline_reason", "decline_reason"),
                ("last_node_output.data.decline_reason", "last_node_output.data.decline_reason"),
                ("last_node_output.data.captured.decline_reason", "last_node_output.data.captured.decline_reason"),
            ],
            "response_time": [
                ("workflow_decision.response_time_seconds", "workflow_decision.response_time_seconds"),
                ("workflow_decision.response_time_ms", "workflow_decision.response_time_ms"),
                ("human_response.response_time_seconds", "human_response.response_time_seconds"),
                ("human_response.response_time_ms", "human_response.response_time_ms"),
                ("response_time_seconds", "response_time_seconds"),
                ("response_time_ms", "response_time_ms"),
                ("response_time", "response_time"),
                ("last_node_output.data.response_time", "last_node_output.data.response_time"),
                ("last_node_output.data.response_time_seconds", "last_node_output.data.response_time_seconds"),
                ("last_node_output.data.response_time_ms", "last_node_output.data.response_time_ms"),
                ("last_node_output.data.captured.response_time", "last_node_output.data.captured.response_time"),
            ],
            "selected_resource": [
                ("flowforge_matching.selected_source_record_key", "flowforge_matching.selected_source_record_key"),
                ("flowforge_matching.selected_candidate", "flowforge_matching.selected_candidate"),
                ("flowforge_matching.selected_resource", "flowforge_matching.selected_resource"),
                ("workflow_decision.source_record_key", "workflow_decision.source_record_key"),
                ("selected_resource", "selected_resource"),
                ("last_node_output.data.selected_source_record_key", "last_node_output.data.selected_source_record_key"),
                ("last_node_output.data.selected_resource", "last_node_output.data.selected_resource"),
                ("last_node_output.data.captured.selected_resource", "last_node_output.data.captured.selected_resource"),
            ],
            "notification_status": [
                ("notification.status", "notification.status"),
                ("notification.delivery_status", "notification.delivery_status"),
                ("last_notification.status", "last_notification.status"),
                ("last_notification.delivery_status", "last_notification.delivery_status"),
                ("notification_status", "notification_status"),
                ("last_node_output.data.notification_status", "last_node_output.data.notification_status"),
                ("last_node_output.data.status", "last_node_output.data.status"),
                ("last_node_output.data.captured.notification_status", "last_node_output.data.captured.notification_status"),
            ],
            "operator_note": [
                ("operator_note.note", "operator_note.note"),
                ("last_operator_note.note", "last_operator_note.note"),
                ("operator_note", "operator_note"),
                ("last_node_output.data.note", "last_node_output.data.note"),
                ("last_node_output.data.captured.operator_note", "last_node_output.data.captured.operator_note"),
            ],
            "timeout": [
                ("workflow_decision.timeout", "workflow_decision.timeout"),
                ("human_response.timeout", "human_response.timeout"),
                ("timeout", "timeout"),
                ("last_node_output.data.timeout", "last_node_output.data.timeout"),
                ("last_node_output.data.captured.timeout", "last_node_output.data.captured.timeout"),
            ],
        }

        value, source = self._first_capture_value(run_context, candidates_by_field.get(normalized, []))
        if self._has_capture_value(value):
            return value, source

        if normalized == "reason":
            config_reason = self._optional_string(config.get("reason"))
            if config_reason:
                return config_reason, "node.reason"
            outcome = self._optional_string(self._path_value(run_context, "workflow_decision.outcome"))
            if outcome:
                return outcome.replace("_", " "), "workflow_decision.outcome"
        if normalized == "timeout":
            outcome = self._optional_string(self._path_value(run_context, "workflow_decision.outcome"))
            action = self._optional_string(self._path_value(run_context, "workflow_decision.action"))
            if outcome == "timed_out" or action == "timeout":
                return True, "workflow_decision.outcome"

        return self._first_capture_value(
            run_context,
            [
                (field, field),
                (normalized, normalized),
                (f"workflow_decision.{normalized}", f"workflow_decision.{normalized}"),
                (f"human_response.{normalized}", f"human_response.{normalized}"),
            ],
        )

    @classmethod
    def _capture_fields(cls, raw: Any) -> list[str]:
        if isinstance(raw, list):
            values = raw
        elif isinstance(raw, str):
            values = raw.split(",")
        else:
            values = ["reason", "response_time"]

        fields: list[str] = []
        for value in values:
            field = str(value or "").strip()
            if field and field not in fields:
                fields.append(field)
        return fields or ["reason", "response_time"]

    @staticmethod
    def _normalize_capture_field(value: str) -> str:
        return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    @classmethod
    def _first_capture_value(cls, source: dict[str, Any], candidates: list[tuple[str, str]]) -> tuple[Any, str | None]:
        for path, source_label in candidates:
            value = cls._path_value(source, path)
            if cls._has_capture_value(value):
                return value, source_label
        return None, None

    @staticmethod
    def _path_value(source: dict[str, Any], path: str) -> Any:
        current: Any = source
        for piece in str(path or "").split("."):
            if not piece:
                continue
            if not isinstance(current, dict) or piece not in current:
                return None
            current = current[piece]
        return current

    @staticmethod
    def _has_capture_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, dict)):
            return bool(value)
        return True

    @staticmethod
    def _first_target(outgoing_edges: list[dict[str, Any]]) -> str | None:
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            target = str(edge.get("target") or "").strip()
            if target:
                return target
        return None
