from __future__ import annotations

from flask_restx import Namespace, fields


def register_plan_models(namespace: Namespace):
    return namespace.model(
        "SemanticPlanRequest",
        {
            "workspace_id": fields.String(required=False, description="Ignored when X-Workspace-Id header is provided"),
            "vertical_norm": fields.String(required=False, default="generic"),
            "prompt": fields.String(required=True),
            "domain_id": fields.Integer(required=False),
            "max_concepts": fields.Integer(required=False, default=12),
            "max_columns": fields.Integer(required=False, default=60),
            "debug": fields.Boolean(required=False, default=False),
            "llm_id": fields.Integer(required=False, description="Optional workspace LLM id override"),
        },
    )


def register_registry_models(namespace: Namespace):
    return namespace.model(
        "SemanticRegistryEntry",
        {
            "id": fields.Integer(readOnly=True),
            "vertical": fields.String(required=False, description="Vertical scope. Null means global."),
            "vertical_norm": fields.String(readOnly=True),
            "concept_key": fields.String(required=True),
            "semantic_type": fields.String(required=True),
            "sub_type": fields.String(required=False),
            "entity": fields.String(required=False),
            "description": fields.String(required=False),
            "granularity_rank": fields.Integer(required=False),
            "filter_allowed": fields.Boolean(required=False),
            "group_by_allowed": fields.Boolean(required=False),
            "aggregation_allowed": fields.Boolean(required=False),
            "is_identifier": fields.Boolean(required=False),
            "is_metric": fields.Boolean(required=False),
            "display_priority": fields.Integer(required=False),
            "sensitive": fields.Boolean(required=False),
            "created_at": fields.DateTime(readOnly=True),
            "updated_at": fields.DateTime(readOnly=True),
        },
    )


def register_concept_models(
    concepts_ns: Namespace,
    concept_aliases_ns: Namespace,
    value_aliases_ns: Namespace,
    concept_column_maps_ns: Namespace,
):
    concept_create_model = concepts_ns.model(
        "SemanticConceptCreate",
        {
            "vertical_norm": fields.String(required=True),
            "concept_key": fields.String(required=True),
            "name": fields.String(required=True),
            "description": fields.String(required=False),
            "semantic_type": fields.String(required=True),
            "sub_type": fields.String(required=False),
            "entity": fields.String(required=False),
            "granularity_rank": fields.Integer(required=False),
            "filter_allowed": fields.Boolean(required=False),
            "group_by_allowed": fields.Boolean(required=False),
            "aggregation_allowed": fields.Boolean(required=False),
            "is_identifier": fields.Boolean(required=False),
            "is_metric": fields.Boolean(required=False),
            "display_priority": fields.Integer(required=False),
            "sensitive": fields.Boolean(required=False),
            "status": fields.String(required=False),
        },
    )
    concept_patch_model = concepts_ns.clone("SemanticConceptPatch", concept_create_model)
    seed_model = concepts_ns.model("SemanticConceptSeed", {"vertical": fields.String(required=True)})
    rebuild_index_model = concepts_ns.model(
        "SemanticConceptRebuildIndex",
        {"vertical_norm": fields.String(required=False, default="generic")},
    )
    backfill_primary_keys_model = concepts_ns.model(
        "SemanticConceptBackfillPrimaryKeys",
        {
            "workspace_id": fields.String(required=False),
            "vertical_norm": fields.String(required=False),
            "dry_run": fields.Boolean(required=False, default=True),
        },
    )
    alias_create_model = concept_aliases_ns.model(
        "SemanticConceptAliasCreate",
        {
            "vertical_norm": fields.String(required=True),
            "alias_key": fields.String(required=True),
            "concept_key": fields.String(required=True),
            "match_kind": fields.String(required=False),
            "weight": fields.Float(required=False),
        },
    )
    alias_patch_model = concept_aliases_ns.clone("SemanticConceptAliasPatch", alias_create_model)
    value_alias_create_model = value_aliases_ns.model(
        "SemanticValueAliasCreate",
        {
            "vertical_norm": fields.String(required=True),
            "semantic_concept_id": fields.Integer(required=True),
            "canonical_value": fields.String(required=True),
            "alias_value": fields.String(required=True),
            "match_kind": fields.String(required=False),
            "weight": fields.Float(required=False),
        },
    )
    value_alias_patch_model = value_aliases_ns.clone("SemanticValueAliasPatch", value_alias_create_model)
    concept_column_map_create_model = concept_column_maps_ns.model(
        "SemanticConceptColumnMapCreate",
        {
            "vertical_norm": fields.String(required=True),
            "semantic_concept_id": fields.Integer(required=True),
            "workspace_column_id": fields.Integer(required=False),
            "relationship_kind": fields.String(required=False),
            "weight": fields.Float(required=False),
        },
    )
    concept_column_map_patch_model = concept_column_maps_ns.clone(
        "SemanticConceptColumnMapPatch",
        concept_column_map_create_model,
    )
    return {
        "concept_create_model": concept_create_model,
        "concept_patch_model": concept_patch_model,
        "seed_model": seed_model,
        "rebuild_index_model": rebuild_index_model,
        "backfill_primary_keys_model": backfill_primary_keys_model,
        "alias_create_model": alias_create_model,
        "alias_patch_model": alias_patch_model,
        "value_alias_create_model": value_alias_create_model,
        "value_alias_patch_model": value_alias_patch_model,
        "concept_column_map_create_model": concept_column_map_create_model,
        "concept_column_map_patch_model": concept_column_map_patch_model,
    }


def register_relationship_models(namespace: Namespace):
    relationship_model = namespace.model(
        "SemanticRelationship",
        {
            "id": fields.Integer(readOnly=True),
            "parent_concept_id": fields.Integer(required=True),
            "child_concept_id": fields.Integer(required=True),
            "relationship_type": fields.String(required=True),
            "created_at": fields.DateTime(readOnly=True),
            "vertical": fields.String(readOnly=True),
            "vertical_norm": fields.String(readOnly=True),
            "parent_concept_key": fields.String(readOnly=True),
            "parent_concept_name": fields.String(readOnly=True),
            "parent_display_label": fields.String(readOnly=True),
            "child_concept_key": fields.String(readOnly=True),
            "child_concept_name": fields.String(readOnly=True),
            "child_display_label": fields.String(readOnly=True),
        },
    )
    relationship_patch_model = namespace.model(
        "SemanticRelationshipPatch",
        {
            "parent_concept_id": fields.Integer(required=False),
            "child_concept_id": fields.Integer(required=False),
            "relationship_type": fields.String(required=False),
        },
    )
    return relationship_model, relationship_patch_model


def register_mapping_models(namespace: Namespace):
    return namespace.model(
        "SemanticColumnMap",
        {
            "id": fields.Integer(readOnly=True),
            "semantic_registry_id": fields.Integer(required=True),
            "workspace_id": fields.String(required=False),
            "workspace_norm": fields.String(readOnly=True),
            "model_column_id": fields.Integer(required=False),
            "workspace_column_id": fields.Integer(required=False),
            "table_name": fields.String(required=False),
            "column_name": fields.String(required=False),
            "priority_rank": fields.Integer(required=False),
            "confidence_score": fields.Float(required=False),
            "created_at": fields.DateTime(readOnly=True),
            "concept_key": fields.String(readOnly=True),
            "vertical": fields.String(readOnly=True),
            "vertical_norm": fields.String(readOnly=True),
            "semantic_type": fields.String(readOnly=True),
            "entity": fields.String(readOnly=True),
        },
    )


def register_suggestion_models(namespace: Namespace):
    run_model = namespace.model(
        "SemanticSuggestionRun",
        {
            "id": fields.Integer(readOnly=True),
            "workspace_id": fields.String,
            "vertical": fields.String,
            "status": fields.String,
            "params_json": fields.Raw,
            "total_columns": fields.Integer,
            "processed_columns": fields.Integer,
            "valid_items": fields.Integer,
            "invalid_items": fields.Integer,
            "auto_approved_items": fields.Integer,
            "approved_items": fields.Integer,
            "rejected_items": fields.Integer,
            "applied_items": fields.Integer,
            "failed_apply_items": fields.Integer,
            "error_message": fields.String,
            "created_at": fields.DateTime,
            "updated_at": fields.DateTime,
        },
    )
    item_patch_model = namespace.model(
        "SemanticSuggestionItemPatch",
        {
            "decision_status": fields.String(description="approved|rejected|pending"),
            "decision_reason": fields.String,
        },
    )
    return run_model, item_patch_model
