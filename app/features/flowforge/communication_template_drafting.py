from __future__ import annotations

import re
from typing import Any

from app.features.flowforge.runtime.communication_templates import ALLOWED_ACTIONS, ALLOWED_ACTIONS_BY_PURPOSE, ALLOWED_PURPOSES, RUNTIME_FIELDS


STANDARD_INTAKE_FIELDS = {
    "intake.requested_date",
    "intake.client_initials",
    "intake.requested_service",
    "intake.preferred_location",
    "intake.preferred_days",
    "intake.insurance",
    "intake.age_range",
    "intake.clinical_summary",
}
STANDARD_CONTEXT_FIELDS = {"context.priority"}
MERGE_FIELD_PATTERN = re.compile(r"{{\s*([A-Za-z0-9_.-]+)\s*}}")
SINGLE_BRACE_FIELD_PATTERN = re.compile(r"(?<!{){\s*([A-Za-z0-9_.-]+)\s*}(?!})")


def _clean_string(value: Any) -> str:
    return str(value or "").strip()


def _normalize_action(value: Any) -> str | None:
    action = _clean_string(value).lower()
    return action if action in ALLOWED_ACTIONS else None


def communication_template_draft_fields(resource_fields: list[str] | set[str] | None = None) -> list[str]:
    return sorted(set(resource_fields or []) | RUNTIME_FIELDS | STANDARD_INTAKE_FIELDS | STANDARD_CONTEXT_FIELDS)


def normalize_generated_communication_template(
    payload: dict[str, Any],
    *,
    purpose: str,
    required_actions: list[str],
    available_fields: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    allowed_fields = set(communication_template_draft_fields(available_fields))
    subject = _sanitize_subject(payload.get("subject"), allowed_fields=allowed_fields) or _default_subject(purpose=purpose)
    blocks = payload.get("body_blocks")
    if not isinstance(blocks, list):
        blocks = []
    normalized_blocks = [_normalize_block(block, required_actions=required_actions, allowed_fields=allowed_fields) for block in blocks if isinstance(block, dict)]
    normalized_blocks = [block for block in normalized_blocks if block is not None]
    if not normalized_blocks:
        normalized_blocks = _heuristic_blocks(purpose=purpose, required_actions=required_actions, available_fields=allowed_fields)
    return {"subject": subject, "body_blocks": normalized_blocks}


class CommunicationTemplateDraftGenerator:
    """Generates structured Workflow Studio communication template drafts."""

    def __init__(self, *, llm_client: Any | None = None) -> None:
        self._llm_client = llm_client

    def generate(
        self,
        *,
        prompt: str,
        purpose: str,
        channel: str,
        resource_set_id: int | None,
        resource_fields: list[str],
        required_actions: list[str],
        tone: str | None = None,
        use_llm: bool = False,
    ) -> dict[str, Any]:
        clean_prompt = _clean_string(prompt)
        clean_purpose = purpose if purpose in ALLOWED_PURPOSES else "notification"
        available_fields = communication_template_draft_fields(resource_fields)
        allowed_for_purpose = ALLOWED_ACTIONS_BY_PURPOSE.get(clean_purpose, set())
        actions = [_normalize_action(action) for action in required_actions]
        actions = [action for action in actions if action and action in allowed_for_purpose]
        if use_llm and self._llm_client is not None:
            return self._generate_with_llm(
                prompt=clean_prompt,
                purpose=clean_purpose,
                channel=channel,
                resource_set_id=resource_set_id,
                available_fields=available_fields,
                required_actions=actions,
                tone=tone,
            )
        return self._generate_heuristic(prompt=clean_prompt, purpose=clean_purpose, required_actions=actions, tone=tone, available_fields=available_fields)

    def _generate_with_llm(
        self,
        *,
        prompt: str,
        purpose: str,
        channel: str,
        resource_set_id: int | None,
        available_fields: list[str],
        required_actions: list[str],
        tone: str | None,
    ) -> dict[str, Any]:
        payload = self._llm_client.chat_json(
            system_prompt=(
                "You generate Workflow Studio communication template JSON. Return JSON only with keys subject, "
                "body_blocks, and plain_language_summary. Do not return HTML, markdown, scripts, URLs, or "
                "custom actions. body_blocks may only use these types: heading, text, field_value, "
                "field_list, image, divider, action_buttons. Image blocks must use keys src, alt, width, and optional href. "
                "action_buttons may only include the required system "
                f"actions: {required_actions}. Merge fields must be written exactly as {{{{field.path}}}} inside text. "
                "Use only the allowed merge fields supplied by the user. Never invent intake fields. "
                "Never place JSON, dictionaries, label/value objects, or triple-brace expressions inside text content. "
                "When asked to include incoming form or intake information, use a field_list block with available intake fields."
            ),
            user_prompt=(
                f"Purpose: {purpose}\n"
                f"Channel: {channel}\n"
                f"Resource set id: {resource_set_id or ''}\n"
                f"Allowed merge fields: {available_fields}\n"
                f"Tone: {_clean_string(tone) or 'clear and professional'}\n"
                f"Required actions: {required_actions}\n"
                f"Instructions: {prompt}"
            ),
            response_format=True,
            retry_invalid_schema=True,
            max_tokens=1400,
        )
        normalized = normalize_generated_communication_template(
            payload if isinstance(payload, dict) else {},
            purpose=purpose,
            required_actions=required_actions,
            available_fields=available_fields,
        )
        default_subject = _default_subject(purpose=purpose)
        heuristic_subject = _heuristic_subject(prompt=prompt, purpose=purpose)
        if normalized["subject"] == default_subject and heuristic_subject != default_subject:
            normalized["subject"] = heuristic_subject
        normalized["body_blocks"] = _polish_prompt_blocks(
            blocks=normalized["body_blocks"],
            prompt=prompt,
            purpose=purpose,
        )
        return {
            **normalized,
            "plain_language_summary": _clean_string((payload or {}).get("plain_language_summary")),
            "model_provider": "configured_llm",
            "model_name": _clean_string(getattr(self._llm_client, "_model", "")) or None,
            "draft_source": "llm",
        }

    def _generate_heuristic(
        self,
        *,
        prompt: str,
        purpose: str,
        required_actions: list[str],
        tone: str | None,
        available_fields: list[str],
    ) -> dict[str, Any]:
        del tone
        subject = _heuristic_subject(prompt=prompt, purpose=purpose)
        blocks = _heuristic_blocks(purpose=purpose, required_actions=required_actions, available_fields=available_fields)
        if "due" in prompt.lower() and purpose in {"human_task", "approval"}:
            blocks.insert(2, {"type": "text", "content": "Please complete this before {{task.due_at}}."})
        closing = _requested_closing(prompt)
        if closing:
            insert_at = -1 if blocks and blocks[-1].get("type") == "action_buttons" else len(blocks)
            blocks.insert(insert_at, {"type": "text", "content": closing})
        return {
            "subject": subject,
            "body_blocks": blocks,
            "plain_language_summary": "Drafted a structured Workflow Studio communication template using governed blocks and system actions.",
            "model_provider": "heuristic",
            "model_name": "workflow-studio-local-communication-template-draft-generator",
            "draft_source": "heuristic",
        }


def _normalize_block(block: dict[str, Any], *, required_actions: list[str], allowed_fields: set[str]) -> dict[str, Any] | None:
    block_type = _clean_string(block.get("type"))
    if block_type in {"heading", "text"}:
        content = _sanitize_text_content(block.get("content"), allowed_fields=allowed_fields)
        return {"type": block_type, "content": content} if content else None
    if block_type == "field_value":
        field = _clean_string(block.get("field"))
        if not field or field not in allowed_fields:
            return None
        label = _clean_string(block.get("label"))
        return {"type": "field_value", "field": field, **({"label": label} if label else {})}
    if block_type == "field_list":
        fields = block.get("fields")
        clean_fields = [_clean_string(field) for field in fields] if isinstance(fields, list) else []
        clean_fields = _dedupe([field for field in clean_fields if field in allowed_fields])
        return {"type": "field_list", "fields": clean_fields} if clean_fields else None
    if block_type == "image":
        src = _clean_string(block.get("src"))
        if not src:
            return None
        alt = _clean_string(block.get("alt"))
        href = _clean_string(block.get("href"))
        width = _clean_string(block.get("width"))
        return {
            "type": "image",
            "src": src,
            **({"alt": alt} if alt else {}),
            **({"href": href} if href else {}),
            **({"width": width} if width else {}),
        }
    if block_type == "divider":
        return {"type": "divider"}
    if block_type == "action_buttons":
        actions = block.get("actions")
        clean_actions = [_normalize_action(action) for action in actions] if isinstance(actions, list) else []
        allowed_required = set(required_actions or ALLOWED_ACTIONS)
        clean_actions = [action for action in clean_actions if action and action in allowed_required]
        return {"type": "action_buttons", "actions": clean_actions} if clean_actions else None
    return None


def _default_subject(*, purpose: str) -> str:
    if purpose == "human_task":
        return "Action requested for {{resource.display_name}}"
    if purpose == "approval":
        return "Approval requested for {{workflow.name}}"
    if purpose == "alert":
        return "Workflow Studio alert for {{workflow.name}}"
    if purpose == "report":
        return "Workflow Studio report for {{workflow.name}}"
    return "Workflow Studio update for {{workflow.name}}"


def _heuristic_subject(*, prompt: str, purpose: str) -> str:
    if purpose == "human_task" and any(word in prompt.lower() for word in ("patient", "intake", "therapist")):
        return "New patient intake review requested"
    return _default_subject(purpose=purpose)


def _heuristic_blocks(*, purpose: str, required_actions: list[str], available_fields: list[str] | set[str]) -> list[dict[str, Any]]:
    allowed_fields = set(available_fields)
    intake_fields = [field for field in communication_template_draft_fields(allowed_fields) if field.startswith("intake.")]
    runtime_fields = [field for field in ["resource.display_name", "selected_resource.display_name", "task.due_at", "run.id"] if field in allowed_fields]
    if purpose in {"human_task", "approval"}:
        actions = required_actions or (["open_task"] if purpose == "approval" else ["accept", "decline", "open_task"])
        field_list = intake_fields or runtime_fields or ["workflow.name", "run.id"]
        return [
            {"type": "heading", "content": "{{workflow.name}}"},
            {"type": "text", "content": "Please review this Workflow Studio item and respond using the actions below."},
            {"type": "field_list", "fields": field_list},
            {"type": "action_buttons", "actions": actions},
        ]
    return [
        {"type": "heading", "content": "{{workflow.name}}"},
        {"type": "text", "content": "A Workflow Studio update is available for run {{run.id}}."},
        {"type": "field_list", "fields": ["workflow.name", "run.status"]},
    ]


def _sanitize_text_content(value: Any, *, allowed_fields: set[str]) -> str:
    content = _clean_string(value)
    if not content or _looks_like_serialized_label_value(content):
        return ""

    content = MERGE_FIELD_PATTERN.sub(
        lambda match: "{{" + match.group(1).strip() + "}}" if match.group(1).strip() in allowed_fields else "",
        content,
    )
    content = SINGLE_BRACE_FIELD_PATTERN.sub(
        lambda match: "{{" + match.group(1).strip() + "}}" if match.group(1).strip() in allowed_fields else "",
        content,
    )
    return re.sub(r"\s{2,}", " ", content).strip()


def _sanitize_subject(value: Any, *, allowed_fields: set[str]) -> str:
    content = _clean_string(value)
    if not content or _looks_like_serialized_label_value(content):
        return ""
    referenced_fields = MERGE_FIELD_PATTERN.findall(content) + SINGLE_BRACE_FIELD_PATTERN.findall(content)
    if any(field.strip() not in allowed_fields for field in referenced_fields):
        return ""
    return _sanitize_text_content(content, allowed_fields=allowed_fields)


def _looks_like_serialized_label_value(content: str) -> bool:
    lowered = content.lower()
    return "{{{" in content or (
        ("'label'" in lowered or '"label"' in lowered)
        and ("'value'" in lowered or '"value"' in lowered)
        and (content.startswith("{") or content.startswith("["))
    )


def _requested_closing(prompt: str) -> str | None:
    match = re.search(r"thank you from the\s+([A-Za-z0-9 '&.-]+?team)", prompt, flags=re.IGNORECASE)
    if not match:
        return None
    team_name = match.group(1).strip()
    if team_name.lower().startswith("the "):
        team_name = team_name[4:].strip()
    return f"Thank you,\nThe {team_name}"


def _polish_prompt_blocks(*, blocks: list[dict[str, Any]], prompt: str, purpose: str) -> list[dict[str, Any]]:
    polished = list(blocks)
    has_text = any(block.get("type") == "text" and _clean_string(block.get("content")) for block in polished)
    if not has_text:
        insert_at = 1 if polished and polished[0].get("type") == "heading" else 0
        content = (
            "Please review the intake details below and respond using the available actions."
            if purpose == "human_task"
            else "Please review the details below."
        )
        polished.insert(insert_at, {"type": "text", "content": content})

    closing = _requested_closing(prompt)
    if closing and not any(closing.lower() in _clean_string(block.get("content")).lower() for block in polished):
        insert_at = -1 if polished and polished[-1].get("type") == "action_buttons" else len(polished)
        polished.insert(insert_at, {"type": "text", "content": closing})
    return polished


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
