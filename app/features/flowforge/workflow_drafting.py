from __future__ import annotations

from typing import Any

SUPPORTED_NODE_TYPES = {
    "schedule_trigger",
    "webhook_trigger",
    "file_watch_trigger",
    "intake",
    "scoring",
    "filter",
    "ranking",
    "human_task",
    "matching",
    "notification",
    "wait",
    "end",
    "decision",
    "assignment",
    "event_capture",
    "iterator",
    "query_extract",
    "export",
    "import",
    "map_transform",
    "approval",
}

DEFAULT_NODE_DATA: dict[str, dict[str, Any]] = {
    "schedule_trigger": {"rrule": "FREQ=DAILY;INTERVAL=1", "mode": "test"},
    "intake": {"source": "", "event": ""},
    "matching": {"matching_policy_id": ""},
    "human_task": {"timeout_minutes": 120, "task_mode": "sequential", "communication_template_key": "flowforge.human_task"},
    "notification": {"recipients": [], "reason": "", "communication_template_key": "flowforge.notification"},
    "decision": {"outcomes": ["accepted", "declined"]},
    "approval": {"approver_role": "flowforge:operator", "timeout_minutes": 1440},
    "query_extract": {"saved_query_id": "", "limit": 1000},
    "export": {"destination_key": "", "format": "csv", "include_header": True},
    "import": {"source_key": "", "resource_set_id": "", "activate": False},
    "map_transform": {"field_mapping": [], "template_fields": []},
}

NODE_LABELS = {
    "schedule_trigger": "Schedule Trigger",
    "webhook_trigger": "Webhook Trigger",
    "file_watch_trigger": "File Watch Trigger",
    "intake": "Patient Intake",
    "matching": "Find Match",
    "human_task": "Request Response",
    "notification": "Send Notification",
    "decision": "Decision",
    "approval": "Approval Gate",
    "query_extract": "Query Extract",
    "export": "Export Data",
    "import": "Import Data",
    "map_transform": "Map Transform",
    "assignment": "Assignment",
    "event_capture": "Capture Event",
    "iterator": "Next Item",
    "wait": "Wait",
    "end": "End",
}


def _clean_string(value: Any) -> str:
    return str(value or "").strip()


def _safe_node_type(value: Any) -> str:
    candidate = _clean_string(value)
    return candidate if candidate in SUPPORTED_NODE_TYPES else "intake"


def _dedupe_id(base: str, existing_ids: set[str]) -> str:
    slug = "".join(char if char.isalnum() else "-" for char in base.lower()).strip("-") or "node"
    candidate = slug[:40]
    index = 2
    while candidate in existing_ids:
        candidate = f"{slug[:34]}-{index}"
        index += 1
    existing_ids.add(candidate)
    return candidate


def _position_for(index: int) -> dict[str, int]:
    return {"x": 120 + (index % 4) * 240, "y": 140 + (index // 4) * 170}


def normalize_generated_workflow_graph(graph: dict[str, Any], *, fallback_graph: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = fallback_graph if isinstance(fallback_graph, dict) else {"nodes": [], "edges": []}
    source_nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else fallback.get("nodes", [])
    source_edges = graph.get("edges") if isinstance(graph.get("edges"), list) else fallback.get("edges", [])
    existing_ids: set[str] = set()
    nodes: list[dict[str, Any]] = []
    for index, raw_node in enumerate(source_nodes if isinstance(source_nodes, list) else []):
        if not isinstance(raw_node, dict):
            continue
        node_type = _safe_node_type(raw_node.get("type"))
        node_id = _clean_string(raw_node.get("id"))
        if not node_id or node_id in existing_ids:
            node_id = _dedupe_id(raw_node.get("label") or node_type, existing_ids)
        else:
            existing_ids.add(node_id)
        position = raw_node.get("position") if isinstance(raw_node.get("position"), dict) else _position_for(index)
        data = raw_node.get("data") if isinstance(raw_node.get("data"), dict) else {}
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": _clean_string(raw_node.get("label")) or NODE_LABELS.get(node_type, node_type.replace("_", " ").title()),
                "position": {
                    "x": int(position.get("x") or _position_for(index)["x"]),
                    "y": int(position.get("y") or _position_for(index)["y"]),
                },
                "data": {**DEFAULT_NODE_DATA.get(node_type, {}), **data},
            }
        )
    if not nodes:
        nodes.append({"id": "start", "type": "intake", "label": "Start", "position": _position_for(0), "data": {}})
        existing_ids.add("start")

    edge_ids: set[str] = set()
    edges: list[dict[str, Any]] = []
    for raw_edge in source_edges if isinstance(source_edges, list) else []:
        if not isinstance(raw_edge, dict):
            continue
        source = _clean_string(raw_edge.get("source"))
        target = _clean_string(raw_edge.get("target"))
        if source not in existing_ids or target not in existing_ids or source == target:
            continue
        edge_id = _clean_string(raw_edge.get("id")) or f"{source}-{target}"
        if edge_id in edge_ids:
            edge_id = _dedupe_id(edge_id, edge_ids)
        else:
            edge_ids.add(edge_id)
        edge: dict[str, Any] = {"id": edge_id, "source": source, "target": target}
        for key in ("label", "branch", "condition"):
            if _clean_string(raw_edge.get(key)):
                edge[key] = _clean_string(raw_edge.get(key))
        edges.append(edge)
    return {"nodes": nodes, "edges": edges}


class WorkflowGraphDraftGenerator:
    def __init__(self, *, llm_client: Any | None = None) -> None:
        self._llm_client = llm_client

    def generate(self, *, prompt: str, current_graph: dict[str, Any], use_llm: bool = False) -> dict[str, Any]:
        clean_prompt = _clean_string(prompt)
        graph = normalize_generated_workflow_graph(current_graph)
        if use_llm and self._llm_client is not None:
            return self._generate_with_llm(prompt=clean_prompt, current_graph=graph)
        return self._generate_heuristic(prompt=clean_prompt, current_graph=graph)

    def _generate_with_llm(self, *, prompt: str, current_graph: dict[str, Any]) -> dict[str, Any]:
        payload = self._llm_client.chat_json(
            system_prompt=(
                "You generate FlowForge workflow graph JSON. Return JSON only with keys graph and plain_language_summary. "
                "The graph must contain nodes and edges arrays. Every node must include id, type, label, position, and data. "
                f"Supported node types: {sorted(SUPPORTED_NODE_TYPES)}. Keep existing node ids stable unless the user asks to replace them. "
                "Do not include code, scripts, SQL, secrets, credentials, or markdown."
            ),
            user_prompt=f"Current graph: {current_graph}\nDesigner request: {prompt}",
            response_format=True,
            retry_invalid_schema=True,
            max_tokens=2200,
        )
        generated_graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else payload
        graph = normalize_generated_workflow_graph(generated_graph if isinstance(generated_graph, dict) else {}, fallback_graph=current_graph)
        return {
            "graph": graph,
            "plain_language_summary": _clean_string(payload.get("plain_language_summary")) or "Workflow graph drafted.",
            "model_provider": "configured_llm",
            "model_name": _clean_string(getattr(self._llm_client, "_model", "")) or None,
            "draft_source": "llm",
        }

    def _generate_heuristic(self, *, prompt: str, current_graph: dict[str, Any]) -> dict[str, Any]:
        lower_prompt = prompt.lower()
        node_type = "intake"
        if any(term in lower_prompt for term in ("schedule", "daily", "weekly")):
            node_type = "schedule_trigger"
        elif any(term in lower_prompt for term in ("saved query", "query extract", "report")):
            node_type = "query_extract"
        elif any(term in lower_prompt for term in ("export", "sftp", "s3", "email")):
            node_type = "export"
        elif any(term in lower_prompt for term in ("import", "upload", "inbound file")):
            node_type = "import"
        elif any(term in lower_prompt for term in ("map", "transform", "validate")):
            node_type = "map_transform"
        elif any(term in lower_prompt for term in ("approve", "approval", "accept", "human")):
            node_type = "approval"
        elif any(term in lower_prompt for term in ("match", "rank", "filter", "eligible")):
            node_type = "matching"
        elif any(term in lower_prompt for term in ("decision", "branch")):
            node_type = "decision"
        nodes = list(current_graph.get("nodes") or [])
        edges = list(current_graph.get("edges") or [])
        existing_ids = {str(node.get("id")) for node in nodes if isinstance(node, dict)}
        label = NODE_LABELS.get(node_type, node_type.replace("_", " ").title())
        node_id = _dedupe_id(label, existing_ids)
        new_node = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "position": _position_for(len(nodes)),
            "data": dict(DEFAULT_NODE_DATA.get(node_type, {})),
        }
        if nodes:
            previous = _clean_string(nodes[-1].get("id")) if isinstance(nodes[-1], dict) else ""
            if previous:
                edges.append({"id": _dedupe_id(f"{previous}-{node_id}", {str(edge.get("id")) for edge in edges if isinstance(edge, dict)}), "source": previous, "target": node_id})
        nodes.append(new_node)
        graph = normalize_generated_workflow_graph({"nodes": nodes, "edges": edges})
        return {
            "graph": graph,
            "plain_language_summary": f"Added {label} to the workflow draft.",
            "model_provider": "heuristic",
            "model_name": "flowforge-local-workflow-draft-generator",
            "draft_source": "heuristic",
        }
