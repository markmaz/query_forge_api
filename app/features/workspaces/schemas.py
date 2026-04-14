from __future__ import annotations

from flask_restx import Namespace, fields


def register_workspace_models(namespace: Namespace, user_model):
    workspace_model = namespace.model(
        "Workspace",
        {
            "workspace_id": fields.String(required=True, description="Unique identifier for the workspace"),
            "name": fields.String(required=True, description="Name of the workspace"),
            "server": fields.String(required=True, description="The URL of the customer instance"),
        },
    )
    namespace.add_model("User", user_model)
    return workspace_model


def register_workspace_llm_models(namespace: Namespace):
    return namespace.model(
        "WorkspaceLLMCreate",
        {
            "name": fields.String(required=True, description="Friendly name"),
            "provider": fields.String(required=True, description="LLM provider"),
            "model_name": fields.String(required=True, description="Model identifier"),
            "role": fields.String(required=True, description="Pipeline role"),
            "api_key": fields.String(description="API key (write-only, never returned)"),
            "endpoint_url": fields.String(description="Base URL for azure_openai or ollama"),
            "is_active": fields.Boolean(default=True),
            "config_json": fields.Raw(description="Optional extra provider config"),
        },
    )
