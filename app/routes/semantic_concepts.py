from __future__ import annotations

import logging
from typing import Any, Dict

from flask import g, request
from flask_restx import Namespace, Resource, fields

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import int_arg
from app.services.embedding.semantic_concept_embedding_service import SemanticConceptEmbeddingService
from app.services.semantic.semantic_concept_service import SemanticConceptService

logger = logging.getLogger(__name__)

semantic_concepts_ns = Namespace("semantic-concepts", description="Semantic canonical concept endpoints")
semantic_concept_aliases_ns = Namespace("semantic-concept-aliases", description="Semantic concept alias endpoints")
semantic_value_aliases_ns = Namespace("semantic-value-aliases", description="Semantic concept value alias endpoints")
semantic_concept_column_maps_ns = Namespace(
    "semantic-concept-column-maps",
    description="Semantic concept to workspace_column mapping endpoints",
)

concept_create_model = semantic_concepts_ns.model(
    "SemanticConceptCreate",
    {
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

concept_patch_model = semantic_concepts_ns.clone("SemanticConceptPatch", concept_create_model)
seed_model = semantic_concepts_ns.model("SemanticConceptSeed", {})
rebuild_index_model = semantic_concepts_ns.model("SemanticConceptRebuildIndex", {})
backfill_primary_keys_model = semantic_concepts_ns.model(
    "SemanticConceptBackfillPrimaryKeys",
    {
        "workspace_id": fields.String(required=False),
        "dry_run": fields.Boolean(required=False, default=True),
    },
)

alias_create_model = semantic_concept_aliases_ns.model(
    "SemanticConceptAliasCreate",
    {
        "alias_key": fields.String(required=True),
        "concept_key": fields.String(required=True),
        "match_kind": fields.String(required=False),
        "weight": fields.Float(required=False),
    },
)
alias_patch_model = semantic_concept_aliases_ns.clone("SemanticConceptAliasPatch", alias_create_model)

value_alias_create_model = semantic_value_aliases_ns.model(
    "SemanticValueAliasCreate",
    {
        "semantic_concept_id": fields.Integer(required=True),
        "canonical_value": fields.String(required=True),
        "alias_value": fields.String(required=True),
        "match_kind": fields.String(required=False),
        "weight": fields.Float(required=False),
    },
)
value_alias_patch_model = semantic_value_aliases_ns.clone("SemanticValueAliasPatch", value_alias_create_model)

concept_column_map_create_model = semantic_concept_column_maps_ns.model(
    "SemanticConceptColumnMapCreate",
    {
        "semantic_concept_id": fields.Integer(required=True),
        "workspace_column_id": fields.Integer(required=False),
        "relationship_kind": fields.String(required=False),
        "weight": fields.Float(required=False),
    },
)
concept_column_map_patch_model = semantic_concept_column_maps_ns.clone(
    "SemanticConceptColumnMapPatch",
    concept_column_map_create_model,
)


def _strip_semantic_vertical_fields(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = dict(value)
        cleaned.pop("vertical", None)
        cleaned.pop("vertical_norm", None)
        if "rows" in cleaned and isinstance(cleaned["rows"], list):
            cleaned["rows"] = [_strip_semantic_vertical_fields(row) for row in cleaned["rows"]]
        return cleaned
    return value


@semantic_concepts_ns.route("")
class SemanticConceptCollection(Resource):
    @token_required
    @require_access("semantic")
    @semantic_concepts_ns.doc(
        params={
            "q": "Search concept_key/name/description",
            "semantic_type": "Filter by semantic_type",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        result = SemanticConceptService().list_concepts(
            q=request.args.get("q") or None,
            semantic_type=request.args.get("semantic_type") or None,
            page=int_arg("page", 1),
            page_size=int_arg("page_size", 25),
        )
        return _strip_semantic_vertical_fields(result), 200

    @token_required
    @require_access("semantic", role="admin")
    @semantic_concepts_ns.expect(concept_create_model, validate=False)
    def post(self):
        _require_admin()
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        row = SemanticConceptService().create_concept(body)
        return {"row": _strip_semantic_vertical_fields(row)}, 201


@semantic_concepts_ns.route("/keys")
class SemanticConceptKeyCollection(Resource):
    @token_required
    @require_access("semantic")
    def get(self):
        return (SemanticConceptService().list_concept_keys(), 200)


@semantic_concepts_ns.route("/<int:concept_id>")
class SemanticConceptById(Resource):
    @token_required
    @require_access("semantic", role="admin")
    @semantic_concepts_ns.expect(concept_patch_model, validate=False)
    def patch(self, concept_id: int):
        _require_admin()
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        row = SemanticConceptService().patch_concept(concept_id, body)
        return {"row": _strip_semantic_vertical_fields(row)}, 200

    @token_required
    @require_access("semantic", role="admin")
    def delete(self, concept_id: int):
        _require_admin()
        SemanticConceptService().delete_concept(concept_id)
        return {}, 204


@semantic_concepts_ns.route("/seed")
class SemanticConceptSeed(Resource):
    @token_required
    @require_access("semantic", role="admin")
    @semantic_concepts_ns.expect(seed_model, validate=False)
    def post(self):
        _require_admin()
        result = SemanticConceptService().seed()
        return {"result": _strip_semantic_vertical_fields(result)}, 200


@semantic_concepts_ns.route("/rebuild-index")
class SemanticConceptRebuildIndex(Resource):
    @token_required
    @require_access("semantic", role="admin")
    @semantic_concepts_ns.expect(rebuild_index_model, validate=False)
    def post(self):
        _require_admin()
        result = SemanticConceptEmbeddingService().rebuild_semantic_concept_index(vertical_norm="generic")
        return {"result": _strip_semantic_vertical_fields(result)}, 200


@semantic_concepts_ns.route("/backfill-primary-keys")
class SemanticConceptBackfillPrimaryKeys(Resource):
    @token_required
    @require_access("semantic", role="admin")
    @semantic_concepts_ns.expect(backfill_primary_keys_model, validate=False)
    def post(self):
        _require_admin()
        body = request.get_json(silent=True) or {}
        result = SemanticConceptService().backfill_primary_semantic_keys(
            workspace_id=body.get("workspace_id"),
            dry_run=bool(body.get("dry_run", True)),
        )
        return {"result": _strip_semantic_vertical_fields(result)}, 200


@semantic_concept_aliases_ns.route("")
class SemanticConceptAliasCollection(Resource):
    @token_required
    @require_access("semantic")
    @semantic_concept_aliases_ns.doc(params={"concept_key": "Filter by concept_key", "q": "Search aliases"})
    def get(self):
        result = SemanticConceptService().list_aliases(
            concept_key=request.args.get("concept_key") or None,
            q=request.args.get("q") or None,
        )
        return _strip_semantic_vertical_fields(result), 200

    @token_required
    @require_access("semantic", role="admin")
    @semantic_concept_aliases_ns.expect(alias_create_model, validate=False)
    def post(self):
        _require_admin()
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        row = SemanticConceptService().create_alias(body)
        return {"row": _strip_semantic_vertical_fields(row)}, 201


@semantic_concept_aliases_ns.route("/<int:alias_id>")
class SemanticConceptAliasById(Resource):
    @token_required
    @require_access("semantic", role="admin")
    @semantic_concept_aliases_ns.expect(alias_patch_model, validate=False)
    def patch(self, alias_id: int):
        _require_admin()
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        row = SemanticConceptService().patch_alias(alias_id, body)
        return {"row": _strip_semantic_vertical_fields(row)}, 200

    @token_required
    @require_access("semantic", role="admin")
    def delete(self, alias_id: int):
        _require_admin()
        SemanticConceptService().delete_alias(alias_id)
        return {}, 204


@semantic_value_aliases_ns.route("")
class SemanticValueAliasCollection(Resource):
    @token_required
    @require_access("semantic")
    @semantic_value_aliases_ns.doc(
        params={
            "semantic_concept_id": "Filter by semantic_concept_id",
            "q": "Search alias/canonical values",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        result = SemanticConceptService().list_value_aliases(
            semantic_concept_id=_optional_int(request.args.get("semantic_concept_id"), "semantic_concept_id"),
            q=request.args.get("q") or None,
            page=int_arg("page", 1),
            page_size=int_arg("page_size", 25),
        )
        return _strip_semantic_vertical_fields(result), 200

    @token_required
    @require_access("semantic", role="admin")
    @semantic_value_aliases_ns.expect(value_alias_create_model, validate=False)
    def post(self):
        _require_admin()
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        row = SemanticConceptService().create_value_alias(body)
        return {"row": _strip_semantic_vertical_fields(row)}, 201


@semantic_value_aliases_ns.route("/<int:value_alias_id>")
class SemanticValueAliasById(Resource):
    @token_required
    @require_access("semantic", role="admin")
    @semantic_value_aliases_ns.expect(value_alias_patch_model, validate=False)
    def patch(self, value_alias_id: int):
        _require_admin()
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        row = SemanticConceptService().patch_value_alias(value_alias_id, body)
        return {"row": _strip_semantic_vertical_fields(row)}, 200

    @token_required
    @require_access("semantic", role="admin")
    def delete(self, value_alias_id: int):
        _require_admin()
        SemanticConceptService().delete_value_alias(value_alias_id)
        return {}, 204


@semantic_concept_column_maps_ns.route("")
class SemanticConceptColumnMapCollection(Resource):
    @token_required
    @require_access("semantic")
    @semantic_concept_column_maps_ns.doc(
        params={
            "semantic_concept_id": "Filter by semantic_concept_id",
            "concept_key": "Filter by concept_key (contains, case-insensitive)",
            "workspace_column_id": "Filter by workspace_column_id",
            "column_name": "Filter by column_name (contains, case-insensitive)",
            "relationship_kind": "Filter by relationship_kind",
            "q": "Type-ahead search across concept_key, concept_name, column_name, model_table_name",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        result = SemanticConceptService().list_concept_column_maps(
            semantic_concept_id=_optional_int(request.args.get("semantic_concept_id"), "semantic_concept_id"),
            concept_key=request.args.get("concept_key") or None,
            workspace_column_id=_optional_int(request.args.get("workspace_column_id"), "workspace_column_id"),
            column_name=request.args.get("column_name") or None,
            relationship_kind=request.args.get("relationship_kind") or None,
            q=request.args.get("q") or None,
            page=int_arg("page", 1),
            page_size=int_arg("page_size", 25),
        )
        return _strip_semantic_vertical_fields(result), 200

    @token_required
    @require_access("semantic", role="admin")
    @semantic_concept_column_maps_ns.expect(concept_column_map_create_model, validate=False)
    def post(self):
        _require_admin()
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        row = SemanticConceptService().create_concept_column_map(body)
        return {"row": _strip_semantic_vertical_fields(row)}, 201


@semantic_concept_column_maps_ns.route("/<int:map_id>")
class SemanticConceptColumnMapById(Resource):
    @token_required
    @require_access("semantic", role="admin")
    @semantic_concept_column_maps_ns.expect(concept_column_map_patch_model, validate=False)
    def patch(self, map_id: int):
        _require_admin()
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        row = SemanticConceptService().patch_concept_column_map(map_id, body)
        return {"row": _strip_semantic_vertical_fields(row)}, 200

    @token_required
    @require_access("semantic", role="admin")
    def delete(self, map_id: int):
        _require_admin()
        SemanticConceptService().delete_concept_column_map(map_id)
        return {}, 204


def _require_admin() -> None:
    if not bool(getattr(g, "is_admin", False)):
        raise ForgeError("Admin access required", status_code=403)


def _optional_int(value: Any, field: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ForgeError(f"{field} must be an integer", status_code=400) from exc
