from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories import FlowForgeRuntimeRepository
from app.features.flowforge.runtime.node_executor import NodeExecutionResult


class FlowForgeNotificationNodeExecutor:
    def __init__(self, *, runtime_repository: FlowForgeRuntimeRepository | None = None) -> None:
        self._runtime_repository = runtime_repository or FlowForgeRuntimeRepository()

    def execute(
        self,
        *,
        workspace_id: str,
        run_id: int,
        node: dict[str, Any],
        outgoing_edges: list[dict[str, Any]],
        run_context: dict[str, Any],
    ) -> NodeExecutionResult:
        node_id = str(node.get("id") or "").strip()
        config = self._node_config(node)
        recipients = self._notification_recipients(config=config, run_context=run_context)
        template_key = str(config.get("communication_template_key") or config.get("template_key") or "flowforge.notification").strip()
        payload_summary = self._notification_payload_summary(config=config, run_context=run_context)
        notification_ids: list[int] = []
        for recipient in recipients:
            notification_ids.append(
                int(
                    self._runtime_repository.create_notification(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        human_task_id=None,
                        channel="email",
                        recipient=recipient,
                        template_key=template_key,
                        status="pending",
                        idempotency_key=f"run:{run_id}:notification:{node_id}:{recipient}",
                        payload_summary=payload_summary,
                    )
                )
            )
        next_node_id = self._first_target(outgoing_edges)
        if next_node_id is None:
            return NodeExecutionResult(
                status="completed",
                event_payload={
                    "node_type": "notification",
                    "template_key": template_key,
                    "notification_ids": notification_ids,
                    "recipient_count": len(recipients),
                    "reason": "no_outgoing_edge",
                },
            )
        return NodeExecutionResult(
            status="advance",
            next_node_id=next_node_id,
            event_payload={
                "node_type": "notification",
                "template_key": template_key,
                "notification_ids": notification_ids,
                "recipient_count": len(recipients),
                "next_node_id": next_node_id,
            },
        )

    @classmethod
    def _notification_recipients(cls, *, config: dict[str, Any], run_context: dict[str, Any]) -> list[str]:
        dynamic_recipient = cls._dynamic_recipient(config=config, run_context=run_context)
        raw_values = [
            dynamic_recipient,
            config.get("recipients"),
            config.get("recipient"),
            config.get("recipient_email"),
            config.get("to"),
            run_context.get("notification_recipients"),
        ]
        recipients: list[str] = []
        for raw in raw_values:
            for recipient in cls._string_list(raw):
                if recipient not in recipients:
                    recipients.append(recipient)
        return recipients

    @classmethod
    def _dynamic_recipient(cls, *, config: dict[str, Any], run_context: dict[str, Any]) -> Any:
        source = str(config.get("recipient_source") or config.get("recipient_mode") or "").strip()
        if source not in {"workflow_value", "mapped_value", "context_field"}:
            return None
        field = str(
            config.get("recipient_field")
            or config.get("recipient_value")
            or config.get("recipient_path")
            or ""
        ).strip()
        if not field:
            return None
        return cls._path_value(run_context, field)

    @staticmethod
    def _notification_payload_summary(*, config: dict[str, Any], run_context: dict[str, Any]) -> dict[str, Any]:
        configured_context = config.get("payload_summary") if isinstance(config.get("payload_summary"), dict) else {}
        communication_context = run_context.get("communication_context") if isinstance(run_context.get("communication_context"), dict) else {}
        intake = communication_context.get("intake") if isinstance(communication_context.get("intake"), dict) else {}
        return {
            **configured_context,
            "reason": str(config.get("reason") or configured_context.get("reason") or "Workflow notification.").strip(),
            "intake": dict(intake),
            "context": communication_context,
        }

    @staticmethod
    def _node_config(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        return {**data, **config}

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if isinstance(value, list):
            raw_items = value
        elif isinstance(value, str):
            raw_items = value.split(",")
        else:
            raw_items = []
        return [str(item or "").strip() for item in raw_items if str(item or "").strip()]

    @staticmethod
    def _path_value(context: dict[str, Any], path: str) -> Any:
        current: Any = context
        for piece in str(path or "").split("."):
            if not piece:
                continue
            if not isinstance(current, dict) or piece not in current:
                return None
            current = current[piece]
        return current

    @staticmethod
    def _first_target(outgoing_edges: list[dict[str, Any]]) -> str | None:
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            target = str(edge.get("target") or "").strip()
            if target:
                return target
        return None
