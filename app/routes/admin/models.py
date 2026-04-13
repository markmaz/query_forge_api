from __future__ import annotations

from flask_restx import fields

from .base import admin_ns

domain_profile_model = admin_ns.model(
    "DomainProfileRequest",
    {
        "workspace_id": fields.String(required=False),
        "domain_id": fields.Integer(required=False),
        "summary": fields.String(required=False),
        "keywords": fields.List(fields.String, required=False),
        "entities": fields.List(fields.String, required=False),
        "metrics": fields.List(fields.String, required=False),
        "attributes": fields.List(fields.String, required=False),
        "synonyms": fields.Raw(required=False),
        "acronyms": fields.Raw(required=False),
        "notes": fields.String(required=False),
        "embedding_text": fields.String(required=False),
    },
)

domain_profile_generate_batch_model = admin_ns.model(
    "DomainProfileGenerateBatchRequest",
    {
        "domain_ids": fields.List(fields.Integer, required=True),
        "force": fields.Boolean(required=False, default=False),
        "llm_id": fields.Integer(
            required=False,
            description="Optional workspace LLM id override",
        ),
    },
)

domain_profile_generate_all_model = admin_ns.model(
    "DomainProfileGenerateAllRequest",
    {
        "force": fields.Boolean(required=False, default=False),
        "include_inactive": fields.Boolean(required=False, default=False),
        "llm_id": fields.Integer(
            required=False,
            description="Optional workspace LLM id override",
        ),
    },
)

domain_profile_generate_one_model = admin_ns.model(
    "DomainProfileGenerateOneRequest",
    {
        "force": fields.Boolean(required=False, default=False),
        "llm_id": fields.Integer(
            required=False,
            description="Optional workspace LLM id override",
        ),
    },
)

semantic_catalog_build_model = admin_ns.model(
    "SemanticCatalogBuildRequest",
    {
        "workspace_id": fields.String(required=False),
        "domain_id": fields.Integer(required=True),
        "vertical_norm": fields.String(required=False, default="generic"),
        "domain_name": fields.String(required=False),
        "dry_run": fields.Boolean(required=False, default=True),
        "table_limit": fields.Integer(required=False, default=5000),
        "llm_id": fields.Integer(
            required=False,
            description="Optional workspace LLM id override",
        ),
    },
)

organization_create_model = admin_ns.model(
    "OrganizationCreateRequest",
    {
        "id": fields.String(required=False),
        "name": fields.String(required=True),
        "slug": fields.String(required=False),
        "description": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
    },
)

organization_update_model = admin_ns.model(
    "OrganizationUpdateRequest",
    {
        "name": fields.String(required=False),
        "slug": fields.String(required=False),
        "description": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
    },
)

organization_membership_create_model = admin_ns.model(
    "OrganizationMembershipCreateRequest",
    {
        "user_id": fields.String(required=True),
        "role": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
    },
)

organization_membership_update_model = admin_ns.model(
    "OrganizationMembershipUpdateRequest",
    {
        "role": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
    },
)

datasource_create_model = admin_ns.model(
    "DatasourceCreateRequest",
    {
        "name": fields.String(required=True),
        "slug": fields.String(required=False),
        "type": fields.String(required=True),
        "description": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
        "secret_ref": fields.String(required=False),
        "config_json": fields.Raw(required=False),
    },
)

datasource_update_model = admin_ns.model(
    "DatasourceUpdateRequest",
    {
        "name": fields.String(required=False),
        "slug": fields.String(required=False),
        "type": fields.String(required=False),
        "description": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
        "secret_ref": fields.String(required=False),
        "config_json": fields.Raw(required=False),
    },
)

workspace_membership_create_model = admin_ns.model(
    "WorkspaceMembershipCreateRequest",
    {
        "user_id": fields.String(required=True),
        "role": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
        "is_default": fields.Boolean(required=False),
    },
)

workspace_membership_update_model = admin_ns.model(
    "WorkspaceMembershipUpdateRequest",
    {
        "role": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
        "is_default": fields.Boolean(required=False),
    },
)

workspace_binding_update_model = admin_ns.model(
    "WorkspaceBindingUpdateRequest",
    {
        "organization_id": fields.String(required=False),
        "datasource_id": fields.Integer(required=False),
        "name": fields.String(required=False),
        "description": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
        "default_catalog": fields.String(required=False),
        "default_schema": fields.String(required=False),
    },
)

workspace_create_model = admin_ns.model(
    "WorkspaceCreateRequest",
    {
        "workspace_id": fields.String(required=False),
        "organization_id": fields.String(required=True),
        "datasource_id": fields.Integer(required=False),
        "name": fields.String(required=False),
        "description": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
        "default_catalog": fields.String(required=False),
        "default_schema": fields.String(required=False),
    },
)

tenancy_bootstrap_model = admin_ns.model(
    "TenancyBootstrapRequest",
    {
        "workspace_id": fields.String(required=True),
        "organization_name": fields.String(required=True),
        "organization_id": fields.String(required=False),
        "organization_slug": fields.String(required=False),
        "organization_description": fields.String(required=False),
        "datasource_name": fields.String(required=True),
        "datasource_type": fields.String(
            required=True,
            enum=["databricks", "snowflake", "mysql", "postgres", "bigquery"],
        ),
        "datasource_slug": fields.String(required=False),
        "datasource_description": fields.String(required=False),
        "datasource_secret_ref": fields.String(required=False),
        "datasource_config_json": fields.Raw(required=False),
        "default_catalog": fields.String(required=False),
        "default_schema": fields.String(required=False),
        "admin_user_id": fields.String(required=False),
    },
)

planner_projection_policy_model = admin_ns.model(
    "PlannerProjectionPolicyRequest",
    {
        "id": fields.Integer(required=False),
        "policy_key": fields.String(required=True),
        "name": fields.String(required=True),
        "description": fields.String(required=False),
        "scope_type": fields.String(required=True),
        "scope_workspace_id": fields.String(required=False),
        "scope_base_domain_id": fields.Integer(required=False),
        "priority": fields.Integer(required=False, default=100),
        "is_active": fields.Boolean(required=False, default=True),
        "stop_on_match": fields.Boolean(required=False, default=False),
        "policy_json": fields.Raw(required=True),
    },
)

planner_signal_policy_model = admin_ns.model(
    "PlannerSignalPolicyRequest",
    {
        "id": fields.Integer(required=False),
        "policy_key": fields.String(required=True),
        "name": fields.String(required=True),
        "description": fields.String(required=False),
        "scope_type": fields.String(required=True),
        "scope_workspace_id": fields.String(required=False),
        "priority": fields.Integer(required=False, default=100),
        "is_active": fields.Boolean(required=False, default=True),
        "stop_on_match": fields.Boolean(required=False, default=False),
        "policy_json": fields.Raw(required=True),
    },
)

planner_prompt_intent_policy_model = admin_ns.model(
    "PlannerPromptIntentPolicyRequest",
    {
        "id": fields.Integer(required=False),
        "policy_key": fields.String(required=True),
        "name": fields.String(required=True),
        "description": fields.String(required=False),
        "scope_type": fields.String(required=True),
        "scope_workspace_id": fields.String(required=False),
        "priority": fields.Integer(required=False, default=100),
        "is_active": fields.Boolean(required=False, default=True),
        "stop_on_match": fields.Boolean(required=False, default=False),
        "policy_json": fields.Raw(required=True),
    },
)

planner_retrieval_policy_model = admin_ns.model(
    "PlannerRetrievalPolicyRequest",
    {
        "id": fields.Integer(required=False),
        "policy_key": fields.String(required=True),
        "name": fields.String(required=True),
        "description": fields.String(required=False),
        "scope_type": fields.String(required=True),
        "scope_workspace_id": fields.String(required=False),
        "priority": fields.Integer(required=False, default=100),
        "is_active": fields.Boolean(required=False, default=True),
        "stop_on_match": fields.Boolean(required=False, default=False),
        "policy_json": fields.Raw(required=True),
    },
)

planner_domain_selection_policy_model = admin_ns.model(
    "PlannerDomainSelectionPolicyRequest",
    {
        "id": fields.Integer(required=False),
        "policy_key": fields.String(required=True),
        "name": fields.String(required=True),
        "description": fields.String(required=False),
        "scope_type": fields.String(required=True),
        "scope_workspace_id": fields.String(required=False),
        "priority": fields.Integer(required=False, default=100),
        "is_active": fields.Boolean(required=False, default=True),
        "stop_on_match": fields.Boolean(required=False, default=False),
        "policy_json": fields.Raw(required=True),
    },
)
