from __future__ import annotations

from flask_restx import fields


def register_matching_models(namespace):
    matching_policy_validation = namespace.model(
        "FlowForgeMatchingPolicyValidation",
        {
            "workspace_id": fields.String(required=False),
            "valid": fields.Boolean(required=True),
            "errors": fields.List(fields.String, required=True),
            "warnings": fields.List(fields.String, required=True),
            "policy": fields.Raw(required=True),
        },
    )
    matching_policy = namespace.model(
        "FlowForgeMatchingPolicy",
        {
            "id": fields.Integer(required=True, description="Internal matching policy id."),
            "workspace_id": fields.String(required=True, description="Workspace that owns the policy."),
            "policy_key": fields.String(required=True, description="Stable workspace-local policy key."),
            "display_name": fields.String(required=True, description="Human-readable matching policy name."),
            "description": fields.String(required=False, description="Optional policy description."),
            "resource_set_id": fields.Integer(required=True, description="Resource set evaluated by this policy."),
            "status": fields.String(required=True, description="Policy lifecycle status. Initial values are draft/published/archived."),
            "current_draft_version_id": fields.Integer(required=False, description="Current draft version id, when available."),
            "latest_published_version_id": fields.Integer(required=False, description="Latest published version id, when available."),
        },
    )
    matching_policy_version = namespace.model(
        "FlowForgeMatchingPolicyVersion",
        {
            "id": fields.Integer(required=True, description="Internal matching policy version id."),
            "workspace_id": fields.String(required=True, description="Workspace that owns the version."),
            "matching_policy_id": fields.Integer(required=True, description="Parent matching policy id."),
            "resource_set_id": fields.Integer(required=True, description="Resource set evaluated by this version."),
            "version_number": fields.Integer(required=True, description="Monotonic version number within the policy."),
            "version_status": fields.String(required=True, description="Version lifecycle status. This phase creates draft versions."),
            "policy": fields.Raw(required=True, description="Validated deterministic matching policy JSON."),
            "validation_status": fields.String(required=True, description="Validation status for the policy JSON."),
            "validation_result": fields.Raw(required=True, description="Policy validation errors and warnings captured at save time."),
            "created_at": fields.Raw(required=False, description="Version creation timestamp."),
            "published_at": fields.Raw(required=False, description="Publish timestamp, when this version has been published."),
        },
    )
    matching_policy_llm_draft = namespace.model(
        "FlowForgeMatchingPolicyLLMDraft",
        {
            "id": fields.Integer(required=True, description="Internal LLM draft id."),
            "workspace_id": fields.String(required=True, description="Workspace that owns the draft."),
            "matching_policy_id": fields.Integer(required=False, description="Parent matching policy id."),
            "resource_set_id": fields.Integer(required=True, description="Resource set used for policy constraints."),
            "prompt": fields.String(required=True, description="Plain-language admin instructions used to generate the draft."),
            "generated_policy": fields.Raw(required=True, description="Generated deterministic matching policy JSON."),
            "plain_language_summary": fields.String(required=False, description="Plain-language interpretation of the generated policy."),
            "validation_status": fields.String(required=True, description="Validation status for the generated policy."),
            "validation_result": fields.Raw(required=True, description="Validation errors and warnings for the generated policy."),
            "model_provider": fields.String(required=False, description="Generator or LLM provider label."),
            "model_name": fields.String(required=False, description="Model or local generator name."),
            "status": fields.String(required=True, description="Draft lifecycle status, such as drafted or accepted."),
            "created_at": fields.Raw(required=False, description="Draft creation timestamp."),
            "reviewed_at": fields.Raw(required=False, description="Review/acceptance timestamp, when available."),
        },
    )
    matching_policy_llm_draft_acceptance = namespace.model(
        "FlowForgeMatchingPolicyLLMDraftAcceptance",
        {
            "draft": fields.Nested(matching_policy_llm_draft, required=True),
            "version": fields.Nested(matching_policy_version, required=True),
        },
    )
    matching_candidate = namespace.model(
        "FlowForgeMatchingCandidate",
        {
            "source_record_key": fields.String(required=True),
            "display_name": fields.String(required=False),
            "included": fields.Boolean(required=False),
            "excluded": fields.Boolean(required=False),
            "selected": fields.Boolean(required=False),
            "rank_position": fields.Integer(required=False),
            "score": fields.Raw(required=False),
            "eligibility_result": fields.Raw(required=False),
            "score_breakdown": fields.Raw(required=False),
            "exclusion_reasons": fields.Raw(required=False),
            "explanation": fields.String(required=False),
        },
    )
    matching_simulation = namespace.model(
        "FlowForgeMatchingSimulation",
        {
            "workspace_id": fields.String(required=False),
            "valid": fields.Boolean(required=True),
            "errors": fields.List(fields.String, required=True),
            "warnings": fields.List(fields.String, required=True),
            "eligible_candidates": fields.List(fields.Nested(matching_candidate), required=True),
            "excluded_candidates": fields.List(fields.Nested(matching_candidate), required=True),
            "ranked_candidates": fields.List(fields.Nested(matching_candidate), required=True),
            "selected_candidate": fields.Raw(required=False),
            "no_match_reason": fields.String(required=False),
        },
    )
    return {
        "matching_policy": matching_policy,
        "matching_policy_version": matching_policy_version,
        "matching_policy_llm_draft": matching_policy_llm_draft,
        "matching_policy_llm_draft_acceptance": matching_policy_llm_draft_acceptance,
        "matching_policy_validation": matching_policy_validation,
        "matching_simulation": matching_simulation,
    }
