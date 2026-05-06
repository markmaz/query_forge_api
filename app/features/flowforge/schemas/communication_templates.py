from __future__ import annotations

from flask_restx import fields


def register_communication_template_models(namespace):
    communication_template = namespace.model(
        "FlowForgeCommunicationTemplate",
        {
            "id": fields.Integer(required=True),
            "workspace_id": fields.String(required=True),
            "template_key": fields.String(required=True),
            "display_name": fields.String(required=True),
            "description": fields.String(required=False),
            "channel": fields.String(required=True),
            "purpose": fields.String(required=True),
            "resource_set_id": fields.Integer(required=False),
            "subject": fields.String(required=True),
            "body_blocks": fields.Raw(required=True),
            "status": fields.String(required=True),
            "validation_status": fields.String(required=True),
            "validation_result": fields.Raw(required=True),
            "metadata": fields.Raw(required=True),
            "created_at": fields.Raw(required=False),
            "updated_at": fields.Raw(required=False),
            "activated_at": fields.Raw(required=False),
        },
    )
    communication_template_upsert = namespace.model(
        "FlowForgeCommunicationTemplateUpsert",
        {
            "template_key": fields.String(required=False),
            "display_name": fields.String(required=True),
            "description": fields.String(required=False),
            "channel": fields.String(required=False),
            "purpose": fields.String(required=False),
            "resource_set_id": fields.Integer(required=False),
            "subject": fields.String(required=True),
            "body_blocks": fields.Raw(required=True),
            "status": fields.String(required=False),
            "metadata": fields.Raw(required=False),
        },
    )
    communication_template_validation = namespace.model(
        "FlowForgeCommunicationTemplateValidation",
        {
            "valid": fields.Boolean(required=True),
            "errors": fields.List(fields.String, required=True),
            "warnings": fields.List(fields.String, required=True),
            "referenced_fields": fields.List(fields.String, required=True),
            "referenced_actions": fields.List(fields.String, required=True),
            "preview": fields.Raw(required=False),
        },
    )
    return {
        "communication_template": communication_template,
        "communication_template_upsert": communication_template_upsert,
        "communication_template_validation": communication_template_validation,
    }
