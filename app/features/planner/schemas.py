from __future__ import annotations

from flask_restx import Namespace, fields


def _register_model(namespace: Namespace, name: str, model_spec: dict):
    existing = namespace.models.get(name)
    if existing is not None:
        return existing
    return namespace.model(name, model_spec)


def register_planner_models(namespace: Namespace) -> dict[str, object]:
    return {
        "extract_model": _register_model(namespace, "PlannerExtractRequest", {"prompt": fields.String(required=True)}),
        "plan_domain_request_model": _register_model(
            namespace,
            "PlannerDomainRequest",
            {
                "workspace_id": fields.String(required=False),
                "prompt": fields.String(required=True),
                "conversation_id": fields.String(required=False),
                "context_seed_plan_json_v2": fields.Raw(required=False),
                "context_seed_last_prompt": fields.String(required=False),
                "base_domain_id": fields.Integer(required=False),
                "debug": fields.Boolean(required=False, default=False),
                "profile_pipeline": fields.Boolean(required=False, default=False),
                "profile_pipeline_data": fields.Boolean(required=False, default=False),
                "fast_mode": fields.Boolean(required=False),
                "next_actions_async": fields.Boolean(required=False),
                "llm_id": fields.Integer(required=False, description="Optional workspace LLM override id"),
            },
        ),
        "next_actions_request_model": _register_model(
            namespace,
            "PlannerDomainNextActionsRequest",
            {
                "workspace_id": fields.String(required=False),
                "prompt": fields.String(required=True),
                "plan_json_v2": fields.Raw(required=True),
                "base_domain_id": fields.Integer(required=False),
                "conversation_id": fields.String(required=False),
                "trace_id": fields.String(required=False),
                "llm_id": fields.Integer(required=False, description="Optional workspace LLM override id"),
            },
        ),
        "plan_llm_request_model": _register_model(
            namespace,
            "PlannerLLMRequest",
            {
                "workspace_id": fields.String(required=False),
                "prompt": fields.String(required=True),
                "constraints": fields.Raw(required=False),
                "debug": fields.Boolean(required=False, default=False),
                "llm_id": fields.Integer(required=False, description="Optional workspace LLM id override"),
            },
        ),
    }
