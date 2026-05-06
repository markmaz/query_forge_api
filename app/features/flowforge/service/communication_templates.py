from __future__ import annotations

import re
from typing import Any

from app.exceptions.forge_error import ForgeError
from app.features.flowforge.runtime.communication_templates import ALLOWED_CHANNELS, ALLOWED_PURPOSES


TEMPLATE_STATUSES = {"draft", "active", "archived"}
SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
COMMON_RESOURCE_FIELDS = {
    "resource.source_record_key",
    "resource.display_name",
    "resource.primary_email",
    "resource.primary_phone",
    "resource.status",
    "resource.effective_status",
    "resource.availability_status",
    "resource.capacity_total",
    "resource.capacity_used",
    "resource.capacity_available",
    "resource.current_load",
    "resource.service_area",
    "resource.timezone",
    "selected_resource.source_record_key",
    "selected_resource.display_name",
}


class FlowForgeCommunicationTemplateServiceMixin:
    def list_communication_templates(
        self,
        *,
        workspace_id: str,
        status: str | None = None,
        purpose: str | None = None,
        channel: str | None = None,
        resource_set_id: int | None = None,
    ) -> list[dict[str, Any]]:
        return [
            self._serialize_communication_template(row)
            for row in self._communication_template_repository.list_templates(
                workspace_id=workspace_id,
                status=self._normalized_optional_choice(status, allowed=TEMPLATE_STATUSES, field_name="status"),
                purpose=self._normalized_optional_choice(purpose, allowed=ALLOWED_PURPOSES, field_name="purpose"),
                channel=self._normalized_optional_choice(channel, allowed=ALLOWED_CHANNELS, field_name="channel"),
                resource_set_id=resource_set_id,
            )
        ]

    def get_communication_template(self, *, workspace_id: str, template_id: int) -> dict[str, Any] | None:
        row = self._communication_template_repository.get_template(workspace_id=workspace_id, template_id=template_id)
        if row is None:
            return None
        return self._serialize_communication_template(row)

    def create_communication_template(
        self,
        *,
        workspace_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        normalized = self._normalize_template_payload(workspace_id=workspace_id, payload=payload)
        validation = self._validate_template_payload(workspace_id=workspace_id, template=normalized)
        normalized["validation_status"] = "valid" if validation["valid"] else "invalid"
        normalized["validation_result"] = validation
        created = self._communication_template_repository.create_template(
            workspace_id=workspace_id,
            created_by=str(actor_user_id or "").strip() or None,
            **normalized,
        )
        return self._serialize_communication_template(created)

    def update_communication_template(
        self,
        *,
        workspace_id: str,
        template_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        current = self._communication_template_repository.get_template(workspace_id=workspace_id, template_id=template_id)
        if current is None:
            raise ForgeError(f"Communication template '{template_id}' was not found.", status_code=404)
        merged = {
            **self._serialize_communication_template(current),
            **{key: value for key, value in payload.items() if value is not None},
        }
        normalized = self._normalize_template_payload(workspace_id=workspace_id, payload=merged, existing_template_key=current["template_key"])
        validation = self._validate_template_payload(workspace_id=workspace_id, template=normalized)
        normalized["validation_status"] = "valid" if validation["valid"] else "invalid"
        normalized["validation_result"] = validation
        updated = self._communication_template_repository.update_template(
            workspace_id=workspace_id,
            template_id=template_id,
            payload=normalized,
            updated_by=str(actor_user_id or "").strip() or None,
        )
        if not updated:
            raise ForgeError(f"Communication template '{template_id}' was not found.", status_code=404)
        refreshed = self._communication_template_repository.get_template(workspace_id=workspace_id, template_id=template_id)
        return self._serialize_communication_template(refreshed or {**normalized, "id": template_id, "workspace_id": workspace_id})

    def validate_communication_template(
        self,
        *,
        workspace_id: str,
        template_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        row = self._communication_template_repository.get_template(workspace_id=workspace_id, template_id=template_id)
        if row is None:
            raise ForgeError(f"Communication template '{template_id}' was not found.", status_code=404)
        template = self._serialize_communication_template(row)
        preview_context = payload.get("preview_context") if isinstance(payload.get("preview_context"), dict) else {}
        validation = self._validate_template_payload(workspace_id=workspace_id, template=template)
        preview = self._communication_template_renderer.render_preview(template=template, context=preview_context)
        return {**validation, "preview": preview}

    def activate_communication_template(
        self,
        *,
        workspace_id: str,
        template_id: int,
        actor_user_id: str,
    ) -> dict[str, Any]:
        row = self._communication_template_repository.get_template(workspace_id=workspace_id, template_id=template_id)
        if row is None:
            raise ForgeError(f"Communication template '{template_id}' was not found.", status_code=404)
        template = self._serialize_communication_template(row)
        validation = self._validate_template_payload(workspace_id=workspace_id, template=template)
        if not validation["valid"]:
            raise ForgeError("Communication template is invalid.", status_code=400, details=validation)
        activated = self._communication_template_repository.activate_template(
            workspace_id=workspace_id,
            template_id=template_id,
            validation_result=validation,
            activated_by=str(actor_user_id or "").strip() or None,
        )
        if not activated:
            raise ForgeError(f"Communication template '{template_id}' was not found.", status_code=404)
        refreshed = self._communication_template_repository.get_template(workspace_id=workspace_id, template_id=template_id)
        return self._serialize_communication_template(refreshed or {**template, "status": "active", "validation_status": "valid"})

    def _normalize_template_payload(
        self,
        *,
        workspace_id: str,
        payload: dict[str, Any],
        existing_template_key: str | None = None,
    ) -> dict[str, Any]:
        display_name = str(payload.get("display_name") or "").strip()
        if not display_name:
            raise ForgeError("display_name is required.", status_code=400)
        template_key = str(payload.get("template_key") or existing_template_key or self._template_key(display_name)).strip()
        if not template_key:
            raise ForgeError("template_key is required.", status_code=400)
        channel = str(payload.get("channel") or "email").strip()
        purpose = str(payload.get("purpose") or "notification").strip()
        status = str(payload.get("status") or "draft").strip()
        if channel not in ALLOWED_CHANNELS:
            raise ForgeError(f"Unsupported channel '{channel}'.", status_code=400)
        if purpose not in ALLOWED_PURPOSES:
            raise ForgeError(f"Unsupported purpose '{purpose}'.", status_code=400)
        if status not in TEMPLATE_STATUSES:
            raise ForgeError(f"Unsupported template status '{status}'.", status_code=400)
        subject = str(payload.get("subject") or "").strip()
        body_blocks = payload.get("body_blocks")
        if not isinstance(body_blocks, list):
            raise ForgeError("body_blocks must be an array.", status_code=400)
        resource_set_id = self._optional_positive_int(payload.get("resource_set_id"), field_name="resource_set_id")
        if resource_set_id is not None and self._resource_repository.get_resource_set(workspace_id=workspace_id, resource_set_id=resource_set_id) is None:
            raise ForgeError(f"Resource set '{resource_set_id}' was not found.", status_code=404)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        return {
            "template_key": template_key,
            "display_name": display_name,
            "description": str(payload.get("description")).strip() if payload.get("description") is not None else None,
            "channel": channel,
            "purpose": purpose,
            "resource_set_id": resource_set_id,
            "subject": subject,
            "body_blocks": [block for block in body_blocks if isinstance(block, dict)],
            "status": status,
            "validation_status": str(payload.get("validation_status") or "pending").strip(),
            "validation_result": payload.get("validation_result") if isinstance(payload.get("validation_result"), dict) else {},
            "metadata": metadata,
        }

    def _validate_template_payload(self, *, workspace_id: str, template: dict[str, Any]) -> dict[str, Any]:
        resource_fields = self._resource_field_keys(workspace_id=workspace_id, resource_set_id=template.get("resource_set_id"))
        return self._communication_template_renderer.validate(template=template, resource_fields=resource_fields).to_dict()

    def _resource_field_keys(self, *, workspace_id: str, resource_set_id: Any) -> set[str] | None:
        resource_id = self._optional_positive_int(resource_set_id, field_name="resource_set_id")
        if resource_id is None:
            return None
        fields = set(COMMON_RESOURCE_FIELDS)
        for row in self._resource_repository.list_snapshot_records(workspace_id=workspace_id, resource_set_id=resource_id, limit=100, offset=0):
            for key, value in row.items():
                if key.endswith("_json") or key in {"sensitive_profile_json", "validation_errors_json"}:
                    continue
                if value is not None:
                    fields.add(f"resource.{key}")
                    fields.add(f"selected_resource.{key}")
            for prefix_key in ("attributes_json", "normalized_profile_json"):
                nested = row.get(prefix_key)
                if isinstance(nested, dict):
                    prefix = "attributes" if prefix_key == "attributes_json" else "normalized_profile"
                    for nested_key in nested:
                        fields.add(f"resource.{prefix}.{nested_key}")
                        fields.add(f"selected_resource.{prefix}.{nested_key}")
        return fields

    @staticmethod
    def _template_key(display_name: str) -> str:
        return SLUG_PATTERN.sub("-", str(display_name or "").lower()).strip("-")[:96] or "communication-template"

    @staticmethod
    def _normalized_optional_choice(value: str | None, *, allowed: set[str], field_name: str) -> str | None:
        if value is None or value == "":
            return None
        normalized = str(value).strip()
        if normalized not in allowed:
            raise ForgeError(f"Unsupported {field_name} '{normalized}'.", status_code=400)
        return normalized

    @staticmethod
    def _serialize_communication_template(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row.get("id") or 0),
            "workspace_id": str(row.get("workspace_id") or ""),
            "template_key": str(row.get("template_key") or ""),
            "display_name": str(row.get("display_name") or ""),
            "description": row.get("description"),
            "channel": str(row.get("channel") or "email"),
            "purpose": str(row.get("purpose") or "notification"),
            "resource_set_id": row.get("resource_set_id"),
            "subject": str(row.get("subject") or ""),
            "body_blocks": row.get("body_blocks") or row.get("body_blocks_json") or [],
            "status": str(row.get("status") or "draft"),
            "validation_status": str(row.get("validation_status") or "pending"),
            "validation_result": row.get("validation_result") or row.get("validation_result_json") or {},
            "metadata": row.get("metadata") or row.get("metadata_json") or {},
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "activated_at": row.get("activated_at"),
        }
