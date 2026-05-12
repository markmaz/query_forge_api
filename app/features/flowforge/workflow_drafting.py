from __future__ import annotations

import re
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
    "end": {"event_key": "workflow_completed"},
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
    "event_capture": "Capture Event",
    "iterator": "Next Item",
    "wait": "Wait",
    "end": "End Event",
}


def _clean_string(value: Any) -> str:
    return str(value or "").strip()


def _normalize_branch(value: Any) -> str:
    return _clean_string(value).lower().replace(" ", "_").replace("-", "_")


def _normalize_branch_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    for entry in value:
        text = _normalize_branch(entry)
        if text and text not in values:
            values.append(text)
    return values


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


def _normalize_viewport(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = round(float(value.get("x") or 0))
        y = round(float(value.get("y") or 0))
        zoom = round(float(value.get("zoom") or 1), 3)
    except (TypeError, ValueError):
        return None
    return {"x": x, "y": y, "zoom": max(0.35, min(1.65, zoom))}


def _normalized_outcomes(value: Any) -> list[str]:
    return _normalize_branch_list(value) or list(DEFAULT_NODE_DATA["decision"]["outcomes"])


def _normalize_decision_outcomes(*, label: str, data: dict[str, Any]) -> list[str]:
    outcomes = _normalized_outcomes(data.get("outcomes"))
    text = _normalize_branch(
        " ".join(
            str(value)
            for value in (
                label,
                data.get("notes"),
                data.get("condition_ref"),
                data.get("true_label"),
                data.get("false_label"),
                data.get("default_outcome"),
            )
            if value is not None
        )
    )
    if "match" in text and ("any" in text or "has" in text):
        return ["matched", "no_match"]
    if "more" in text and any(term in text for term in ("candidate", "therapist", "resource", "remaining")):
        return ["has_more", "exhausted"]
    if "accept" in text and any(term in text for term in ("decline", "timeout", "timed_out")):
        for outcome in ("accepted", "declined", "timed_out"):
            if outcome not in outcomes:
                outcomes.append(outcome)
    return outcomes


def _normalize_node_data(*, node_type: str, label: str, data: dict[str, Any]) -> dict[str, Any]:
    normalized = {**DEFAULT_NODE_DATA.get(node_type, {}), **data}
    if node_type == "intake":
        normalized["source"] = _clean_string(normalized.get("source")) or _clean_string(normalized.get("integration_key"))
        normalized["event"] = _clean_string(normalized.get("event")) or _clean_string(normalized.get("event_key"))
        normalized.pop("integration_key", None)
        normalized.pop("event_key", None)
    if node_type == "map_transform":
        normalized = _normalize_map_transform_data(normalized)
    if node_type == "decision":
        normalized["outcomes"] = _normalize_decision_outcomes(label=label, data=normalized)
    return normalized


def _normalize_map_transform_data(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    field_mapping = normalized.get("field_mapping")
    if isinstance(field_mapping, list) and field_mapping:
        return normalized
    mappings = normalized.get("mappings")
    if not isinstance(mappings, list):
        return normalized
    converted: list[dict[str, Any]] = []
    for entry in mappings:
        if not isinstance(entry, dict):
            continue
        target = _clean_string(entry.get("target") or entry.get("to"))
        source = _clean_string(entry.get("source") or entry.get("from"))
        if not target and not source:
            continue
        converted.append(
            {
                "target": target,
                "source": source,
                "expose_to_templates": bool(entry.get("expose_to_templates")),
            }
        )
    if converted:
        normalized["field_mapping"] = converted
        normalized.pop("mappings", None)
    return normalized


def _text_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def _edge_text(*, raw_edge: dict[str, Any], target_node: dict[str, Any] | None) -> str:
    target_text = ""
    if isinstance(target_node, dict):
        target_text = " ".join(
            _clean_string(target_node.get(key))
            for key in ("id", "label", "type")
            if _clean_string(target_node.get(key))
        )
    return " ".join(
        _clean_string(value)
        for value in (
            raw_edge.get("id"),
            raw_edge.get("label"),
            raw_edge.get("branch"),
            raw_edge.get("condition"),
            raw_edge.get("target"),
            target_text,
        )
        if _clean_string(value)
    )


def _has_any_token(tokens: set[str], candidates: set[str]) -> bool:
    return bool(tokens & candidates)


def _infer_matching_branch(*, text: str, edge_index: int, outgoing_count: int) -> str | None:
    normalized = _normalize_branch(text)
    tokens = _text_tokens(text)
    if any(term in normalized for term in ("no_match", "unmatched", "no_therapist", "none")) or _has_any_token(
        tokens,
        {"admin", "none", "unmatched"},
    ):
        return "no_match"
    if any(term in normalized for term in ("matched", "candidate", "therapist", "resource", "iterate")) or _has_any_token(
        tokens,
        {"yes", "true", "next"},
    ):
        return "matched"
    if outgoing_count == 2:
        return "matched" if edge_index == 0 else "no_match"
    return None


def _decision_aliases(outcome: str) -> set[str]:
    aliases = {
        "accepted": {"accept", "accepted", "approve", "approved", "yes", "true"},
        "approved": {"accept", "accepted", "approve", "approved", "yes", "true"},
        "declined": {"decline", "declined", "reject", "rejected", "deny", "denied", "no", "false"},
        "rejected": {"decline", "declined", "reject", "rejected", "deny", "denied", "no", "false"},
        "timed_out": {"timeout", "timedout", "expired"},
        "matched": {"match", "matched", "matches", "yes", "true"},
        "no_match": {"nomatch", "unmatched", "none", "admin", "no", "false"},
        "has_more": {"more", "remaining", "next", "yes", "true"},
        "exhausted": {"exhausted", "none", "admin", "no", "false"},
    }
    return aliases.get(outcome, {outcome})


def _infer_decision_branches(
    *,
    source_node: dict[str, Any],
    text: str,
    edge_index: int,
    outgoing_count: int,
) -> list[str]:
    data = source_node.get("data") if isinstance(source_node.get("data"), dict) else {}
    outcomes = _normalize_branch_list(data.get("outcomes"))
    if not outcomes:
        return []
    normalized = _normalize_branch(text)
    tokens = _text_tokens(text)
    inferred: list[str] = []
    has_negative_match_context = any(term in normalized for term in ("no_match", "no_matches", "unmatched")) or _has_any_token(
        tokens,
        {"admin", "none", "unmatched"},
    )
    for outcome in outcomes:
        if outcome == "matched" and has_negative_match_context:
            continue
        outcome_match = outcome in normalized or _has_any_token(tokens, _decision_aliases(outcome))
        if outcome == "timed_out" and any(term in normalized for term in ("timeout", "timed_out", "time_out")):
            outcome_match = True
        if outcome == "no_match" and any(term in normalized for term in ("no_match", "no_matches")):
            outcome_match = True
        if outcome_match and outcome not in inferred:
            inferred.append(outcome)
    if {"declined", "timed_out"}.issubset(set(outcomes)) and any(
        term in normalized for term in ("decline_timeout", "declined_timeout", "decline_or_timeout")
    ):
        return ["declined", "timed_out"]
    if inferred:
        return inferred
    if outgoing_count == len(outcomes):
        return [outcomes[edge_index]]
    return []


def _prompt_requests_offer_acceptance_flow(prompt: str) -> bool:
    normalized = _normalize_branch(prompt)
    tokens = _text_tokens(prompt)
    has_match = any(term in normalized for term in ("match", "matching", "matched", "candidate"))
    has_acceptance = any(term in normalized for term in ("accept", "accepted", "acceptance"))
    has_negative_response = any(term in normalized for term in ("decline", "declined", "timeout", "timed_out", "time_out"))
    has_retry_or_no_accept = any(term in normalized for term in ("next", "remaining", "no_match", "not_accepted", "none_accepted")) or bool(
        tokens & {"next", "admin"}
    )
    return has_match and has_acceptance and has_negative_response and has_retry_or_no_accept


def _node_type_counts(nodes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        node_type = _clean_string(node.get("type"))
        if node_type:
            counts[node_type] = counts.get(node_type, 0) + 1
    return counts


def _graph_has_offer_acceptance_flow(graph: dict[str, Any]) -> bool:
    nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    counts = _node_type_counts(nodes)
    if not counts.get("matching") or not counts.get("human_task") or not counts.get("event_capture"):
        return False
    has_accept_event = any(
        node.get("type") == "event_capture"
        and any(term in _normalize_branch(f"{node.get('id')} {node.get('label')} {node.get('data')}") for term in ("accept", "accepted", "acceptance"))
        for node in nodes
    )
    has_negative_event = any(
        node.get("type") == "event_capture"
        and any(term in _normalize_branch(f"{node.get('id')} {node.get('label')} {node.get('data')}") for term in ("decline", "timeout", "not_accepted", "no_match"))
        for node in nodes
    )
    has_admin_notification = any(
        node.get("type") == "notification" and "admin" in _normalize_branch(f"{node.get('id')} {node.get('label')} {node.get('data')}")
        for node in nodes
    )
    return has_accept_event and has_negative_event and has_admin_notification


def _first_node_by_type(graph: dict[str, Any], node_type: str) -> dict[str, Any] | None:
    for node in graph.get("nodes", []):
        if isinstance(node, dict) and node.get("type") == node_type:
            return node
    return None


def _context_matching_defaults(draft_context: dict[str, Any]) -> dict[str, Any]:
    matching_policies = draft_context.get("matching_policies") if isinstance(draft_context, dict) else []
    resource_sets = draft_context.get("resource_sets") if isinstance(draft_context, dict) else []
    policies = [policy for policy in matching_policies if isinstance(policy, dict)] if isinstance(matching_policies, list) else []
    resources = [resource for resource in resource_sets if isinstance(resource, dict)] if isinstance(resource_sets, list) else []
    preferred_policies = [policy for policy in policies if bool(policy.get("published"))] or policies
    defaults: dict[str, Any] = {}
    selected_policy = preferred_policies[0] if len(preferred_policies) == 1 else None
    if selected_policy:
        if selected_policy.get("id") is not None:
            defaults["matching_policy_id"] = selected_policy.get("id")
        if _clean_string(selected_policy.get("policy_key")):
            defaults["policy_key"] = _clean_string(selected_policy.get("policy_key"))
        if selected_policy.get("resource_set_id") is not None:
            defaults["resource_set_id"] = selected_policy.get("resource_set_id")
    if defaults.get("resource_set_id") is None and len(resources) == 1:
        defaults["resource_set_id"] = resources[0].get("id")
        if _clean_string(resources[0].get("resource_set_key")):
            defaults["resource_set_key"] = _clean_string(resources[0].get("resource_set_key"))
    if defaults.get("resource_set_id") is not None and "resource_set_key" not in defaults:
        for resource in resources:
            if str(resource.get("id")) == str(defaults["resource_set_id"]) and _clean_string(resource.get("resource_set_key")):
                defaults["resource_set_key"] = _clean_string(resource.get("resource_set_key"))
                break
    return defaults


def _template_key_for_purpose(draft_context: dict[str, Any], purpose: str) -> str:
    templates = draft_context.get("communication_templates") if isinstance(draft_context, dict) else []
    if not isinstance(templates, list):
        return ""
    matching = [
        template
        for template in templates
        if isinstance(template, dict)
        and _normalize_branch(template.get("purpose")) == purpose
        and _clean_string(template.get("template_key"))
    ]
    return _clean_string(matching[0].get("template_key")) if len(matching) == 1 else ""


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if _clean_string(value):
            return value
    return ""


def _merge_non_empty(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        merged[key] = value
    return merged


def _canonical_offer_acceptance_graph(
    graph: dict[str, Any],
    *,
    draft_context: dict[str, Any],
) -> dict[str, Any]:
    intake = _first_node_by_type(graph, "intake") or {
        "id": "start",
        "type": "intake",
        "label": "Start",
        "position": {"x": 120, "y": 140},
        "data": dict(DEFAULT_NODE_DATA["intake"]),
    }
    mapper = _first_node_by_type(graph, "map_transform") or {
        "id": "map_intake_to_schema",
        "type": "map_transform",
        "label": "Map Intake To Workflow Schema",
        "position": {"x": 420, "y": 140},
        "data": dict(DEFAULT_NODE_DATA["map_transform"]),
    }
    matching = _first_node_by_type(graph, "matching") or {
        "id": "match_resource",
        "type": "matching",
        "label": "Match Resource",
        "position": {"x": 740, "y": 140},
        "data": dict(DEFAULT_NODE_DATA["matching"]),
    }
    intake_id = _clean_string(intake.get("id")) or "start"
    mapper_id = _clean_string(mapper.get("id")) or "map_intake_to_schema"
    matching_id = _clean_string(matching.get("id")) or "match_resource"
    matching_defaults = _context_matching_defaults(draft_context)
    matching_data = _merge_non_empty(
        matching_defaults,
        matching.get("data") if isinstance(matching.get("data"), dict) else {},
    )
    if not _clean_string(matching_data.get("match_input_ref")):
        matching_data["match_input_ref"] = mapper_id
    human_template_key = _template_key_for_purpose(draft_context, "human_task")
    notification_template_key = _template_key_for_purpose(draft_context, "notification")
    nodes = [
        {
            **intake,
            "id": intake_id,
            "type": "intake",
            "position": intake.get("position") if isinstance(intake.get("position"), dict) else {"x": 120, "y": 140},
            "data": _normalize_node_data(
                node_type="intake",
                label=_clean_string(intake.get("label")) or "Start",
                data=intake.get("data") if isinstance(intake.get("data"), dict) else {},
            ),
        },
        {
            **mapper,
            "id": mapper_id,
            "type": "map_transform",
            "position": mapper.get("position") if isinstance(mapper.get("position"), dict) else {"x": 420, "y": 140},
            "data": _normalize_node_data(
                node_type="map_transform",
                label=_clean_string(mapper.get("label")) or "Map Intake To Workflow Schema",
                data=mapper.get("data") if isinstance(mapper.get("data"), dict) else {},
            ),
        },
        {
            **matching,
            "id": matching_id,
            "type": "matching",
            "position": matching.get("position") if isinstance(matching.get("position"), dict) else {"x": 740, "y": 140},
            "data": matching_data,
        },
        {
            "id": "therapist_response_task",
            "type": "human_task",
            "label": "Therapist Accept/Decline (2h)",
            "position": {"x": 1040, "y": 140},
            "data": {
                "timeout_minutes": 120,
                "task_mode": "sequential",
                "communication_template_key": _first_non_empty(human_template_key, "flowforge.human_task"),
                "assignee_ref": "flowforge_matching.selected_source_record_key",
                "due_in_minutes": 120,
                "task_outcomes": ["accept", "decline"],
            },
        },
        {
            "id": "therapist_response",
            "type": "decision",
            "label": "Therapist Response",
            "position": {"x": 1320, "y": 140},
            "data": {"outcomes": ["accepted", "declined", "timed_out", "no_match"], "default_outcome": "timed_out"},
        },
        {
            "id": "create_acceptance_event",
            "type": "event_capture",
            "label": "Create Acceptance Event",
            "position": {"x": 1600, "y": 40},
            "data": {"event_key": "", "event_name": "client_accepted", "payload_ref": "workflow_values"},
        },
        {
            "id": "notify_client_accepted",
            "type": "notification",
            "label": "Notify Client - Accepted",
            "position": {"x": 1880, "y": 40},
            "data": {
                "recipients": [],
                "reason": "",
                "communication_template_key": "flowforge.notification",
                "template_key": notification_template_key,
                "recipient_ref": "workflow_values.patient.email",
            },
        },
        {
            "id": "end_success",
            "type": "end",
            "label": "End (Client Accepted)",
            "position": {"x": 2160, "y": 40},
            "data": dict(DEFAULT_NODE_DATA["end"]),
        },
        {
            "id": "create_decline_timeout_event",
            "type": "event_capture",
            "label": "Create Decline/Timeout Event",
            "position": {"x": 1600, "y": 240},
            "data": {"event_key": "", "event_name": "therapist_declined_or_timed_out", "payload_ref": "workflow_values"},
        },
        {
            "id": "next_candidate",
            "type": "iterator",
            "label": "Next Matching Therapist",
            "position": {"x": 1880, "y": 240},
            "data": {"collection_ref": f"{matching_id}.candidates", "mode": "sequential"},
        },
        {
            "id": "no_match_admin_event",
            "type": "event_capture",
            "label": "Create No-Match/No-Accept Event",
            "position": {"x": 1040, "y": 360},
            "data": {"event_key": "", "event_name": "no_therapist_available_or_accepted", "payload_ref": "workflow_values"},
        },
        {
            "id": "notify_admin",
            "type": "notification",
            "label": "Notify Admin",
            "position": {"x": 1320, "y": 360},
            "data": {
                "recipients": [],
                "reason": "",
                "communication_template_key": "flowforge.notification",
                "template_key": notification_template_key,
                "recipient_ref": "",
            },
        },
        {
            "id": "end_admin",
            "type": "end",
            "label": "End (Admin Notified)",
            "position": {"x": 1600, "y": 360},
            "data": dict(DEFAULT_NODE_DATA["end"]),
        },
    ]
    edges = [
        {"id": "e_start_map", "source": intake_id, "target": mapper_id, "branch": "default"},
        {"id": "e_map_match", "source": mapper_id, "target": matching_id, "branch": "default"},
        {"id": "e_match_matched_task", "source": matching_id, "target": "therapist_response_task", "branch": "matched"},
        {"id": "e_match_no_match_admin_event", "source": matching_id, "target": "no_match_admin_event", "branch": "no_match"},
        {"id": "e_task_decision", "source": "therapist_response_task", "target": "therapist_response", "branch": "default"},
        {"id": "e_decision_accepted", "source": "therapist_response", "target": "create_acceptance_event", "branch": "accepted"},
        {"id": "e_accepted_notify", "source": "create_acceptance_event", "target": "notify_client_accepted", "branch": "default"},
        {"id": "e_notify_end_success", "source": "notify_client_accepted", "target": "end_success", "branch": "default"},
        {"id": "e_decision_declined", "source": "therapist_response", "target": "create_decline_timeout_event", "branch": "declined"},
        {"id": "e_decision_timed_out", "source": "therapist_response", "target": "create_decline_timeout_event", "branch": "timed_out"},
        {"id": "e_decline_iterate", "source": "create_decline_timeout_event", "target": "next_candidate", "branch": "default"},
        {"id": "e_iterate_retry", "source": "next_candidate", "target": matching_id, "branch": "default"},
        {"id": "e_decision_no_match", "source": "therapist_response", "target": "no_match_admin_event", "branch": "no_match"},
        {"id": "e_admin_event_notify", "source": "no_match_admin_event", "target": "notify_admin", "branch": "default"},
        {"id": "e_notify_admin_end", "source": "notify_admin", "target": "end_admin", "branch": "default"},
    ]
    return normalize_generated_workflow_graph({"nodes": nodes, "edges": edges, "viewport": {"x": -47, "y": 324, "zoom": 0.522}})


def ensure_offer_acceptance_flow_if_requested(
    graph: dict[str, Any],
    *,
    prompt: str,
    draft_context: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    if not _prompt_requests_offer_acceptance_flow(prompt) or _graph_has_offer_acceptance_flow(graph):
        return graph, False
    return _canonical_offer_acceptance_graph(graph, draft_context=draft_context), True


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
        label = _clean_string(raw_node.get("label")) or NODE_LABELS.get(node_type, node_type.replace("_", " ").title())
        data = raw_node.get("data") if isinstance(raw_node.get("data"), dict) else {}
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": label,
                "position": {
                    "x": int(position.get("x") or _position_for(index)["x"]),
                    "y": int(position.get("y") or _position_for(index)["y"]),
                },
                "data": _normalize_node_data(node_type=node_type, label=label, data=data),
            }
        )
    if not nodes:
        nodes.append({"id": "start", "type": "intake", "label": "Start", "position": _position_for(0), "data": {}})
        existing_ids.add("start")

    edge_ids: set[str] = set()
    edges: list[dict[str, Any]] = []
    nodes_by_id = {str(node.get("id")): node for node in nodes if isinstance(node, dict)}
    valid_outgoing_counts: dict[str, int] = {}
    for raw_edge in source_edges if isinstance(source_edges, list) else []:
        if not isinstance(raw_edge, dict):
            continue
        source = _clean_string(raw_edge.get("source"))
        target = _clean_string(raw_edge.get("target"))
        if source in existing_ids and target in existing_ids and source != target:
            valid_outgoing_counts[source] = valid_outgoing_counts.get(source, 0) + 1
    outgoing_indexes: dict[str, int] = {}
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
        for key in ("label", "condition"):
            if _clean_string(raw_edge.get(key)):
                edge[key] = _clean_string(raw_edge.get(key))
        if _normalize_branch(raw_edge.get("branch")):
            edge["branch"] = _normalize_branch(raw_edge.get("branch"))
        branches = _normalize_branch_list(raw_edge.get("branches"))
        if branches:
            edge["branches"] = branches
        edge_index = outgoing_indexes.get(source, 0)
        outgoing_indexes[source] = edge_index + 1
        if "branch" not in edge and "branches" not in edge and "condition" not in edge:
            source_node = nodes_by_id.get(source)
            target_node = nodes_by_id.get(target)
            source_type = _clean_string(source_node.get("type")) if isinstance(source_node, dict) else ""
            text = _edge_text(raw_edge=raw_edge, target_node=target_node)
            inferred_branches: list[str] = []
            if source_type == "matching":
                branch = _infer_matching_branch(
                    text=text,
                    edge_index=edge_index,
                    outgoing_count=valid_outgoing_counts.get(source, 0),
                )
                inferred_branches = [branch] if branch else []
            elif source_type == "decision" and isinstance(source_node, dict):
                inferred_branches = _infer_decision_branches(
                    source_node=source_node,
                    text=text,
                    edge_index=edge_index,
                    outgoing_count=valid_outgoing_counts.get(source, 0),
                )
            if len(inferred_branches) == 1:
                edge["branch"] = inferred_branches[0]
            elif len(inferred_branches) > 1:
                edge["branches"] = inferred_branches
        edges.append(edge)
    normalized_graph: dict[str, Any] = {"nodes": nodes, "edges": edges}
    viewport = _normalize_viewport(graph.get("viewport")) or _normalize_viewport(fallback.get("viewport"))
    if viewport:
        normalized_graph["viewport"] = viewport
    return normalized_graph


class WorkflowGraphDraftGenerator:
    def __init__(self, *, llm_client: Any | None = None) -> None:
        self._llm_client = llm_client

    def generate(
        self,
        *,
        prompt: str,
        current_graph: dict[str, Any],
        draft_context: dict[str, Any] | None = None,
        use_llm: bool = False,
    ) -> dict[str, Any]:
        clean_prompt = _clean_string(prompt)
        graph = normalize_generated_workflow_graph(current_graph)
        if use_llm and self._llm_client is not None:
            return self._generate_with_llm(prompt=clean_prompt, current_graph=graph, draft_context=draft_context or {})
        return self._generate_heuristic(prompt=clean_prompt, current_graph=graph)

    def _generate_with_llm(
        self,
        *,
        prompt: str,
        current_graph: dict[str, Any],
        draft_context: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self._llm_client.chat_json(
            system_prompt=(
                "You generate Workflow Studio workflow graph JSON. Return JSON only with keys graph and plain_language_summary. "
                "The graph must contain nodes and edges arrays. Every node must include id, type, label, position, and data. "
                f"Supported node types: {sorted(SUPPORTED_NODE_TYPES)}. Keep existing node ids stable unless the user asks to replace them. "
                "Configure nodes only with identifiers present in the governed designer context when available: integration keys, "
                "source event keys, matching policy ids, resource set ids, communication template keys, and saved query ids. "
                "For intake nodes, write the integration key to data.source and the source event key to data.event; do not use "
                "data.integration_key or data.event_key on intake nodes. Matching nodes branch directly with edge branch values "
                "'matched' and 'no_match'; do not add a separate decision only to check whether matching returned candidates. "
                "Decision node data.outcomes must exactly match outgoing edge branch/branches values. Human response decisions "
                "should use outcomes such as 'accepted', 'declined', and 'timed_out' when timeout is part of the workflow. "
                "When the request describes matching resources who must accept, decline, or time out, preserve that offer flow: "
                "match to a human_task, branch accepted to an acceptance event and client notification, branch declined/timed_out "
                "to a decline/timeout reporting event and the next candidate, and branch no_match/no_accept to an admin event and "
                "admin notification. Do not shortcut this by notifying the requester with ranked options. "
                "Leave required config values blank when the needed catalog value is unavailable. Do not include code, scripts, SQL, "
                "secrets, credentials, or markdown."
            ),
            user_prompt=(
                f"Current graph: {current_graph}\n"
                f"Governed designer context: {draft_context}\n"
                f"Designer request: {prompt}"
            ),
            response_format=True,
            retry_invalid_schema=True,
            max_tokens=2200,
        )
        generated_graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else payload
        graph = normalize_generated_workflow_graph(generated_graph if isinstance(generated_graph, dict) else {}, fallback_graph=current_graph)
        graph, repaired_offer_flow = ensure_offer_acceptance_flow_if_requested(
            graph,
            prompt=prompt,
            draft_context=draft_context,
        )
        summary = _clean_string(payload.get("plain_language_summary")) or "Workflow graph drafted."
        if repaired_offer_flow:
            summary = (
                "Workflow starts from the intake event, maps intake values into workflow context, runs the matching policy, "
                "offers the matched resource a 2-hour accept/decline task, records acceptance or decline/timeout events, "
                "retries the next candidate after decline/timeout, and notifies an admin if no match or no acceptance remains."
            )
        return {
            "graph": graph,
            "plain_language_summary": summary,
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
