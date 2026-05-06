from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.features.flowforge.runtime.communication_templates import CommunicationTemplateRenderer
from app.features.flowforge.service import FlowForgeService


def _template(**overrides):
    template = {
        "template_key": "therapist-task",
        "display_name": "Therapist Task",
        "channel": "email",
        "purpose": "human_task",
        "resource_set_id": 30,
        "subject": "New task for {{resource.display_name}}",
        "body_blocks": [
            {"type": "heading", "content": "Task for {{resource.display_name}}"},
            {"type": "text", "content": "Please respond by {{task.due_at}}."},
            {"type": "field_list", "fields": ["resource.attributes.specialty", "intake.requested_date"]},
            {"type": "action_buttons", "actions": ["accept", "decline"]},
        ],
        "status": "draft",
        "metadata": {},
    }
    template.update(overrides)
    return template


def test_communication_template_renderer_validates_and_renders_preview():
    renderer = CommunicationTemplateRenderer()
    validation = renderer.validate(
        template=_template(),
        resource_fields={"resource.display_name", "resource.attributes.specialty"},
    )

    preview = renderer.render_preview(
        template=_template(),
        context={
            "resource": {"display_name": "Dr. Lane", "attributes": {"specialty": "Anxiety"}},
            "task": {"due_at": "2026-05-06T18:00:00Z"},
            "intake": {"requested_date": "Friday"},
        },
    )

    assert validation.valid is True
    assert validation.errors == []
    assert validation.referenced_actions == ["accept", "decline"]
    assert preview["subject"] == "New task for Dr. Lane"
    assert "Anxiety" in preview["html"]


def test_communication_template_renderer_rejects_unknown_fields_and_actions():
    renderer = CommunicationTemplateRenderer()

    validation = renderer.validate(
        template=_template(
            body_blocks=[
                {"type": "text", "content": "{{resource.unknown}}"},
                {"type": "action_buttons", "actions": ["accept", "custom_link"]},
            ]
        ),
        resource_fields={"resource.display_name"},
    )

    assert validation.valid is False
    assert "Merge field 'resource.unknown' is not available for this template." in validation.errors
    assert "unsupported action 'custom_link'" in " ".join(validation.errors)


class _TemplateRepo:
    def __init__(self) -> None:
        self.created = None
        self.templates = {
            501: {
                "id": 501,
                "workspace_id": "ws-1",
                **_template(resource_set_id=None),
                "body_blocks_json": _template()["body_blocks"],
                "validation_status": "valid",
                "validation_result_json": {"valid": True, "errors": [], "warnings": []},
                "metadata_json": {},
            }
        }

    def list_templates(self, **kwargs):
        return list(self.templates.values())

    def get_template(self, *, template_id: int, **kwargs):
        return self.templates.get(template_id)

    def create_template(self, **payload):
        self.created = payload
        return {
            "id": 502,
            "workspace_id": payload["workspace_id"],
            **payload,
            "body_blocks_json": payload["body_blocks"],
            "validation_result_json": payload["validation_result"],
            "metadata_json": payload["metadata"],
        }

    def update_template(self, **kwargs):
        return True

    def activate_template(self, **kwargs):
        self.templates[501]["status"] = "active"
        self.templates[501]["validation_status"] = "valid"
        return True


class _ResourceRepo:
    def get_resource_set(self, *, resource_set_id: int, **kwargs):
        return {"id": resource_set_id, "workspace_id": "ws-1", "active_snapshot_batch_id": 301}

    def list_snapshot_records(self, **kwargs):
        return [
            {
                "source_record_key": "therapist-1",
                "display_name": "Dr. Lane",
                "attributes_json": {"specialty": "Anxiety"},
                "normalized_profile_json": {},
            }
        ]


def test_flowforge_service_creates_and_activates_communication_template():
    repo = _TemplateRepo()
    service = FlowForgeService(communication_template_repository=repo, resource_repository=_ResourceRepo())

    created = service.create_communication_template(workspace_id="ws-1", payload=_template(), actor_user_id="user-1")
    activated = service.activate_communication_template(workspace_id="ws-1", template_id=501, actor_user_id="user-1")

    assert created["id"] == 502
    assert repo.created["validation_status"] == "valid"
    assert activated["status"] == "active"


def test_flowforge_service_rejects_invalid_communication_template_activation():
    repo = _TemplateRepo()
    repo.templates[501]["body_blocks"] = [{"type": "action_buttons", "actions": ["custom_link"]}]
    repo.templates[501]["body_blocks_json"] = [{"type": "action_buttons", "actions": ["custom_link"]}]
    service = FlowForgeService(communication_template_repository=repo, resource_repository=_ResourceRepo())

    with pytest.raises(ForgeError) as exc:
        service.activate_communication_template(workspace_id="ws-1", template_id=501, actor_user_id="user-1")

    assert exc.value.status_code == 400
