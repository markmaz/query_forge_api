from __future__ import annotations

from flask_restx import fields


def register_integration_models(namespace, *, run_event):
    webhook_accepted = namespace.model(
        "FlowForgeWebhookAcceptedResponse",
        {
            "accepted": fields.Boolean(required=True, description="True when the webhook payload was accepted."),
            "duplicate": fields.Boolean(required=True, description="True when this delivery reused an existing intake event."),
            "workspace_id": fields.String(required=True, description="Workspace id addressed by the webhook URL."),
            "integration_id": fields.Integer(required=True, description="Persisted integration config id addressed by the public webhook id."),
            "integration_key": fields.String(required=True, description="Workspace-local integration key."),
            "intake_event_id": fields.Integer(required=True, description="Persisted intake event id."),
            "mode": fields.String(required=True, description="production or test mode copied from the integration config."),
            "source": fields.String(required=True, description="External integration source name."),
            "trigger_evaluation": fields.Raw(
                required=True,
                description="Persisted trigger evaluation summary. Workflow run creation remains deferred in this phase.",
            ),
            "workflow_runs": fields.Raw(
                required=True,
                description="Workflow run creation summary for selected triggers.",
            ),
            "event": fields.Nested(run_event, required=True, description="Normalized inbound event payload."),
            "notes": fields.List(
                fields.String,
                required=True,
                description="Implementation notes for the current FlowForge runtime phase.",
            ),
        },
    )
    integration_source_field = namespace.model(
        "FlowForgeIntegrationSourceField",
        {
            "path": fields.String(required=True, description="Provider payload field path relative to the normalized intake fields object."),
            "label": fields.String(required=True, description="Human-readable field label for designer mapping."),
            "type": fields.String(required=True, description="Field type: text, number, boolean, date, datetime, email, phone, json, or unknown."),
            "required": fields.Boolean(required=True, description="Whether this provider field is expected for this integration."),
            "sensitive": fields.Boolean(required=True, description="Whether this field may contain sensitive data."),
        },
    )
    integration_source_event = namespace.model(
        "FlowForgeIntegrationSourceEvent",
        {
            "event_key": fields.String(required=True, description="Stable event key this integration can emit."),
            "display_name": fields.String(required=True, description="Human-readable event name for workflow intake nodes."),
            "description": fields.String(required=False, description="Optional event description."),
        },
    )
    workflow_value_schema_field = namespace.model(
        "FlowForgeWorkflowValueSchemaField",
        {
            "key": fields.String(required=True, description="Workflow value key, such as values.patient.email."),
            "label": fields.String(required=True, description="Human-readable field label."),
            "type": fields.String(required=True, description="Field type: text, number, boolean, date, datetime, email, phone, json, or unknown."),
            "required": fields.Boolean(required=True, description="Whether this workflow value should be populated."),
            "sensitive": fields.Boolean(required=True, description="Whether this workflow value may contain sensitive data."),
            "source_paths": fields.List(fields.String, required=True, description="Suggested source field paths for this value."),
            "transform": fields.String(required=True, description="Mapping transform: copy, concat, or template."),
            "separator": fields.String(required=True, description="Separator used by concat transforms."),
            "template": fields.String(required=True, description="Safe template expression used by template transforms."),
            "expose_to_templates": fields.Boolean(required=True, description="Whether this field can be exposed to communications."),
        },
    )
    workflow_value_schema = namespace.model(
        "FlowForgeWorkflowValueSchema",
        {
            "fields": fields.List(fields.Nested(workflow_value_schema_field), required=True),
        },
    )
    integration_config = namespace.model(
        "FlowForgeIntegrationConfig",
        {
            "id": fields.Integer(required=True, description="Internal integration config id."),
            "workspace_id": fields.String(required=True, description="Workspace that owns the integration."),
            "provider": fields.String(required=True, description="External provider, such as webhook or jotform."),
            "integration_key": fields.String(required=True, description="Stable workspace-local integration key."),
            "display_name": fields.String(required=True, description="Human-readable integration name."),
            "external_form_id": fields.String(required=False, description="Provider form id when known."),
            "enabled": fields.Boolean(required=True, description="Whether this integration can accept provider webhooks."),
            "mode": fields.String(required=True, description="production or test. Test mode is excluded from production reporting."),
            "webhook_public_id": fields.String(required=True, description="Opaque public id used in the provider webhook URL."),
            "webhook_path": fields.String(required=True, description="Relative webhook path for provider configuration."),
            "webhook_url": fields.String(required=True, description="Absolute webhook URL when a base URL is configured, otherwise path."),
            "field_mapping": fields.Raw(required=True, description="Provider-to-normalized-field mapping configuration."),
            "source_events": fields.List(
                fields.Nested(integration_source_event),
                required=True,
                description="Known provider events available to intake nodes.",
            ),
            "source_fields": fields.List(
                fields.Nested(integration_source_field),
                required=True,
                description="Known provider fields available to intake map/transform nodes.",
            ),
            "workflow_value_schema": fields.Nested(
                workflow_value_schema,
                required=True,
                description="Workspace-governed workflow values available as clean Map/Transform targets.",
            ),
            "test_recipient_overrides": fields.Raw(required=True, description="Optional test-mode notification recipient overrides."),
            "settings": fields.Raw(required=True, description="Provider-specific settings."),
        },
    )
    integration_config_create_response = namespace.model(
        "FlowForgeIntegrationConfigCreateResponse",
        {
            **integration_config,
            "webhook_secret": fields.String(
                required=True,
                description="Plaintext webhook secret returned only once at creation time. Store this in the provider.",
            ),
        },
    )
    integration_trigger = namespace.model(
        "FlowForgeIntegrationTrigger",
        {
            "id": fields.Integer(required=True, description="Internal integration trigger id."),
            "workspace_id": fields.String(required=True, description="Workspace that owns the trigger."),
            "integration_config_id": fields.Integer(required=True, description="Parent integration config id."),
            "trigger_key": fields.String(required=True, description="Stable key unique within the integration."),
            "display_name": fields.String(required=True, description="Human-readable trigger name."),
            "enabled": fields.Boolean(required=True, description="Whether this trigger participates in webhook evaluation."),
            "priority": fields.Integer(
                required=True,
                description="Lower numbers evaluate first. Used with first_matching trigger policy.",
            ),
            "trigger_mode": fields.String(required=True, description="always or conditional."),
            "trigger_policy": fields.String(required=True, description="all_matching or first_matching."),
            "version_strategy": fields.String(required=True, description="pinned or latest_published."),
            "workflow_definition_id": fields.Integer(required=True, description="Workflow definition this trigger starts."),
            "workflow_version_id": fields.Integer(
                required=False,
                description="Pinned workflow version id. Required when version_strategy is pinned.",
            ),
            "condition": fields.Raw(
                required=True,
                description="Conditional trigger expression object. Empty for always-on triggers.",
            ),
            "field_mapping": fields.Raw(
                required=True,
                description="Integration payload to workflow intake field mapping.",
            ),
            "no_match_config": fields.Raw(
                required=True,
                description="No-match notification and escalation configuration for this trigger.",
            ),
        },
    )
    return {
        "webhook_accepted": webhook_accepted,
        "integration_config": integration_config,
        "integration_config_create_response": integration_config_create_response,
        "integration_trigger": integration_trigger,
        "workflow_value_schema": workflow_value_schema,
    }
