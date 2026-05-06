from __future__ import annotations

from flask_restx import fields


def register_settings_models(namespace):
    settings = namespace.model(
        "FlowForgeWorkspaceSettings",
        {
            "workspace_id": fields.String(required=True, description="Workspace that owns these FlowForge settings."),
            "enabled": fields.Boolean(required=True, description="Whether FlowForge runtime is enabled for the workspace."),
            "allow_designer_publish": fields.Boolean(
                required=True,
                description="Whether designers may publish workflow versions without FlowForge admin approval.",
            ),
            "block_sensitive_reporting_mcp": fields.Boolean(
                required=True,
                description=(
                    "When true, future MCP/reporting read paths must block domains flagged sensitive for this workspace. "
                    "Defaults false so UI-visible data remains MCP-visible until a workspace admin opts in."
                ),
            ),
            "raw_payload_retention_days": fields.Integer(required=True, description="Configured raw webhook payload retention days."),
            "raw_payload_retention_max_days": fields.Integer(required=True, description="Product maximum retention days."),
            "default_offer_timeout_minutes": fields.Integer(required=True, description="Default timeout for offer human tasks."),
            "default_no_match_recipients": fields.List(
                fields.String,
                required=True,
                description="Default email recipients notified when a run cannot match a resource.",
            ),
            "default_test_recipients": fields.List(
                fields.String,
                required=True,
                description="Default email recipients used for test-mode notification substitution.",
            ),
            "settings": fields.Raw(required=True, description="Reserved workspace-level FlowForge settings JSON."),
        },
    )
    settings_update = namespace.model(
        "FlowForgeWorkspaceSettingsUpdateRequest",
        {
            "enabled": fields.Boolean(required=False),
            "allow_designer_publish": fields.Boolean(required=False),
            "block_sensitive_reporting_mcp": fields.Boolean(required=False),
            "raw_payload_retention_days": fields.Integer(required=False),
            "default_offer_timeout_minutes": fields.Integer(required=False),
            "default_no_match_recipients": fields.List(fields.String, required=False),
            "default_test_recipients": fields.List(fields.String, required=False),
            "settings": fields.Raw(required=False),
        },
    )
    return {
        "workspace_settings": settings,
        "workspace_settings_update": settings_update,
    }
