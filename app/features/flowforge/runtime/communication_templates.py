from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any


ALLOWED_CHANNELS = {"email"}
ALLOWED_PURPOSES = {"human_task", "notification", "approval", "alert", "report"}
ALLOWED_BLOCK_TYPES = {"heading", "text", "field_value", "field_list", "divider", "action_buttons"}
ALLOWED_ACTIONS = {"accept", "decline", "approve", "reject", "open_task"}
MERGE_FIELD_PATTERN = re.compile(r"{{\s*([A-Za-z0-9_.-]+)\s*}}")
RUNTIME_FIELD_PREFIXES = {"intake", "context"}
RUNTIME_FIELDS = {
    "task.due_at",
    "task.id",
    "task.type",
    "run.id",
    "run.mode",
    "run.status",
    "workflow.name",
    "workflow.version_number",
    "selected_resource.source_record_key",
    "selected_resource.display_name",
}


@dataclass(frozen=True)
class CommunicationTemplateValidation:
    valid: bool
    errors: list[str]
    warnings: list[str]
    referenced_fields: list[str]
    referenced_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "referenced_fields": self.referenced_fields,
            "referenced_actions": self.referenced_actions,
        }


class CommunicationTemplateRenderer:
    def validate(
        self,
        *,
        template: dict[str, Any],
        resource_fields: set[str] | None = None,
    ) -> CommunicationTemplateValidation:
        errors: list[str] = []
        warnings: list[str] = []
        referenced_fields: set[str] = set()
        referenced_actions: set[str] = set()
        channel = str(template.get("channel") or "email").strip()
        purpose = str(template.get("purpose") or "notification").strip()
        subject = str(template.get("subject") or "").strip()
        blocks = template.get("body_blocks")

        if channel not in ALLOWED_CHANNELS:
            errors.append(f"Unsupported channel '{channel}'.")
        if purpose not in ALLOWED_PURPOSES:
            errors.append(f"Unsupported purpose '{purpose}'.")
        if not subject:
            errors.append("subject is required.")
        if not isinstance(blocks, list) or not blocks:
            errors.append("body_blocks must contain at least one block.")
            blocks = []

        referenced_fields.update(self._fields_in_text(subject))
        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                errors.append(f"body_blocks[{index}] must be an object.")
                continue
            block_type = str(block.get("type") or "").strip()
            if block_type not in ALLOWED_BLOCK_TYPES:
                errors.append(f"body_blocks[{index}].type '{block_type}' is not supported.")
                continue
            if block_type in {"heading", "text"}:
                content = str(block.get("content") or "").strip()
                if not content:
                    errors.append(f"body_blocks[{index}].content is required.")
                referenced_fields.update(self._fields_in_text(content))
            elif block_type == "field_value":
                field = str(block.get("field") or "").strip()
                if not field:
                    errors.append(f"body_blocks[{index}].field is required.")
                else:
                    referenced_fields.add(field)
            elif block_type == "field_list":
                fields = block.get("fields")
                if not isinstance(fields, list) or not fields:
                    errors.append(f"body_blocks[{index}].fields must contain at least one field.")
                else:
                    referenced_fields.update(str(field or "").strip() for field in fields if str(field or "").strip())
            elif block_type == "action_buttons":
                actions = block.get("actions")
                if not isinstance(actions, list) or not actions:
                    errors.append(f"body_blocks[{index}].actions must contain at least one action.")
                else:
                    for action in actions:
                        action_key = str(action or "").strip()
                        if action_key not in ALLOWED_ACTIONS:
                            errors.append(f"body_blocks[{index}].actions contains unsupported action '{action_key}'.")
                        else:
                            referenced_actions.add(action_key)

        for field in sorted(referenced_fields):
            if not self._field_allowed(field=field, resource_fields=resource_fields):
                errors.append(f"Merge field '{field}' is not available for this template.")
        if purpose == "human_task" and not referenced_actions:
            warnings.append("Human task templates should include an action button block.")

        return CommunicationTemplateValidation(
            valid=not errors,
            errors=errors,
            warnings=warnings,
            referenced_fields=sorted(referenced_fields),
            referenced_actions=sorted(referenced_actions),
        )

    def render_preview(self, *, template: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, str]:
        render_context = context if isinstance(context, dict) else {}
        subject = self._render_text(str(template.get("subject") or ""), context=render_context)
        html_parts: list[str] = []
        for block in template.get("body_blocks") or []:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "").strip()
            if block_type == "heading":
                html_parts.append(f"<h2>{self._escape_rendered(block.get('content'), render_context)}</h2>")
            elif block_type == "text":
                html_parts.append(f"<p>{self._escape_rendered(block.get('content'), render_context)}</p>")
            elif block_type == "field_value":
                label = str(block.get("label") or block.get("field") or "Value").strip()
                value = self._value_at_path(render_context, str(block.get("field") or ""))
                html_parts.append(f"<p><strong>{html.escape(label)}:</strong> {html.escape(self._string_value(value))}</p>")
            elif block_type == "field_list":
                items = []
                for field in block.get("fields") or []:
                    field_key = str(field or "").strip()
                    value = self._value_at_path(render_context, field_key)
                    items.append(f"<li><strong>{html.escape(field_key)}:</strong> {html.escape(self._string_value(value))}</li>")
                html_parts.append("<ul>" + "".join(items) + "</ul>")
            elif block_type == "divider":
                html_parts.append("<hr>")
            elif block_type == "action_buttons":
                actions = [str(action or "").strip() for action in block.get("actions") or [] if str(action or "").strip()]
                html_parts.append("<p>" + " ".join(f"<button>{html.escape(action.replace('_', ' ').title())}</button>" for action in actions) + "</p>")
        return {"subject": subject, "html": "".join(html_parts)}

    @staticmethod
    def _fields_in_text(value: str) -> set[str]:
        return {match.group(1).strip() for match in MERGE_FIELD_PATTERN.finditer(str(value or ""))}

    @staticmethod
    def _field_allowed(*, field: str, resource_fields: set[str] | None) -> bool:
        if field in RUNTIME_FIELDS:
            return True
        root = field.split(".", 1)[0]
        if root in RUNTIME_FIELD_PREFIXES:
            return True
        if field.startswith("resource.") or field.startswith("selected_resource."):
            return resource_fields is None or field in resource_fields
        return False

    def _escape_rendered(self, value: Any, context: dict[str, Any]) -> str:
        return html.escape(self._render_text(str(value or ""), context=context))

    def _render_text(self, value: str, *, context: dict[str, Any]) -> str:
        def replace(match: re.Match[str]) -> str:
            return self._string_value(self._value_at_path(context, match.group(1).strip()))

        return MERGE_FIELD_PATTERN.sub(replace, str(value or ""))

    @staticmethod
    def _value_at_path(context: dict[str, Any], path: str) -> Any:
        current: Any = context
        for part in str(path or "").split("."):
            if not part:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    @staticmethod
    def _string_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        if isinstance(value, dict):
            return ""
        return str(value)
