from __future__ import annotations

from typing import Any

from app.features.flowforge.runtime.communication_templates import ALLOWED_ACTIONS, ALLOWED_ACTIONS_BY_PURPOSE, ALLOWED_PURPOSES


def _clean_string(value: Any) -> str:
    return str(value or "").strip()


def _normalize_action(value: Any) -> str | None:
    action = _clean_string(value).lower()
    return action if action in ALLOWED_ACTIONS else None


def normalize_generated_communication_template(payload: dict[str, Any], *, purpose: str, required_actions: list[str]) -> dict[str, Any]:
    subject = _clean_string(payload.get("subject")) or _default_subject(purpose=purpose)
    blocks = payload.get("body_blocks")
    if not isinstance(blocks, list):
        blocks = []
    normalized_blocks = [_normalize_block(block, required_actions=required_actions) for block in blocks if isinstance(block, dict)]
    normalized_blocks = [block for block in normalized_blocks if block is not None]
    if not normalized_blocks:
        normalized_blocks = _heuristic_blocks(purpose=purpose, required_actions=required_actions)
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
        allowed_for_purpose = ALLOWED_ACTIONS_BY_PURPOSE.get(clean_purpose, set())
        actions = [_normalize_action(action) for action in required_actions]
        actions = [action for action in actions if action and action in allowed_for_purpose]
        if use_llm and self._llm_client is not None:
            return self._generate_with_llm(
                prompt=clean_prompt,
                purpose=clean_purpose,
                channel=channel,
                resource_set_id=resource_set_id,
                resource_fields=resource_fields,
                required_actions=actions,
                tone=tone,
            )
        return self._generate_heuristic(prompt=clean_prompt, purpose=clean_purpose, required_actions=actions, tone=tone)

    def _generate_with_llm(
        self,
        *,
        prompt: str,
        purpose: str,
        channel: str,
        resource_set_id: int | None,
        resource_fields: list[str],
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
                f"actions: {required_actions}. Merge fields must be written as {{field.path}} inside text."
            ),
            user_prompt=(
                f"Purpose: {purpose}\n"
                f"Channel: {channel}\n"
                f"Resource set id: {resource_set_id or ''}\n"
                f"Allowed resource/runtime fields: {resource_fields}\n"
                f"Tone: {_clean_string(tone) or 'clear and professional'}\n"
                f"Required actions: {required_actions}\n"
                f"Instructions: {prompt}"
            ),
            response_format=True,
            retry_invalid_schema=True,
            max_tokens=1400,
        )
        normalized = normalize_generated_communication_template(payload if isinstance(payload, dict) else {}, purpose=purpose, required_actions=required_actions)
        return {
            **normalized,
            "plain_language_summary": _clean_string((payload or {}).get("plain_language_summary")),
            "model_provider": "configured_llm",
            "model_name": _clean_string(getattr(self._llm_client, "_model", "")) or None,
            "draft_source": "llm",
        }

    def _generate_heuristic(self, *, prompt: str, purpose: str, required_actions: list[str], tone: str | None) -> dict[str, Any]:
        del tone
        subject = _default_subject(purpose=purpose)
        blocks = _heuristic_blocks(purpose=purpose, required_actions=required_actions)
        if "due" in prompt.lower() and purpose in {"human_task", "approval"}:
            blocks.insert(2, {"type": "text", "content": "Please complete this before {{task.due_at}}."})
        return {
            "subject": subject,
            "body_blocks": blocks,
            "plain_language_summary": "Drafted a structured Workflow Studio communication template using governed blocks and system actions.",
            "model_provider": "heuristic",
            "model_name": "workflow-studio-local-communication-template-draft-generator",
            "draft_source": "heuristic",
        }


def _normalize_block(block: dict[str, Any], *, required_actions: list[str]) -> dict[str, Any] | None:
    block_type = _clean_string(block.get("type"))
    if block_type in {"heading", "text"}:
        content = _clean_string(block.get("content"))
        return {"type": block_type, "content": content} if content else None
    if block_type == "field_value":
        field = _clean_string(block.get("field"))
        if not field:
            return None
        label = _clean_string(block.get("label"))
        return {"type": "field_value", "field": field, **({"label": label} if label else {})}
    if block_type == "field_list":
        fields = block.get("fields")
        clean_fields = [_clean_string(field) for field in fields] if isinstance(fields, list) else []
        clean_fields = [field for field in clean_fields if field]
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


def _heuristic_blocks(*, purpose: str, required_actions: list[str]) -> list[dict[str, Any]]:
    if purpose in {"human_task", "approval"}:
        actions = required_actions or (["open_task"] if purpose == "approval" else ["accept", "decline", "open_task"])
        return [
            {"type": "heading", "content": "{{workflow.name}}"},
            {"type": "text", "content": "Please review this Workflow Studio item for {{resource.display_name}}."},
            {"type": "field_list", "fields": ["resource.display_name", "task.due_at", "run.id"]},
            {"type": "action_buttons", "actions": actions},
        ]
    return [
        {"type": "heading", "content": "{{workflow.name}}"},
        {"type": "text", "content": "A Workflow Studio update is available for run {{run.id}}."},
        {"type": "field_list", "fields": ["workflow.name", "run.status"]},
    ]
