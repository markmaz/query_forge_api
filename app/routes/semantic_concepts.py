from __future__ import annotations

import logging
from typing import Any, Dict

from flask import g, request
from flask_restx import Namespace, fields
from app.routes.forge_resource import ForgeResource

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
    description="Semantic concept to model_column mapping endpoints",
)

concept_create_model = semantic_concepts_ns.model(
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

concept_patch_model = semantic_concepts_ns.clone("SemanticConceptPatch", concept_create_model)

seed_model = semantic_concepts_ns.model(
    "SemanticConceptSeed",
    {
        "vertical": fields.String(required=True),
    },
)
rebuild_index_model = semantic_concepts_ns.model(
    "SemanticConceptRebuildIndex",
    {
        "vertical_norm": fields.String(required=False, default="generic"),
    },
)
backfill_primary_keys_model = semantic_concepts_ns.model(
    "SemanticConceptBackfillPrimaryKeys",
    {
        "workspace_id": fields.String(required=False),
        "vertical_norm": fields.String(required=False),
        "dry_run": fields.Boolean(required=False, default=True),
    },
)

alias_create_model = semantic_concept_aliases_ns.model(
    "SemanticConceptAliasCreate",
    {
        "vertical_norm": fields.String(required=True),
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
        "vertical_norm": fields.String(required=True),
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
        "vertical_norm": fields.String(required=True),
        "semantic_concept_id": fields.Integer(required=True),
        "model_column_id": fields.Integer(required=True),
        "relationship_kind": fields.String(required=False),
        "weight": fields.Float(required=False),
    },
)
concept_column_map_patch_model = semantic_concept_column_maps_ns.clone(
    "SemanticConceptColumnMapPatch",
    concept_column_map_create_model,
)


@semantic_concepts_ns.route("")
class SemanticConceptCollection(ForgeResource):
    @token_required
    @semantic_concepts_ns.doc(
        params={
            "vertical": "Filter by vertical",
            "q": "Search concept_key/name/description",
            "semantic_type": "Filter by semantic_type",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        try:
            return (
                SemanticConceptService().list_concepts(
                    vertical=request.args.get("vertical") or None,
                    q=request.args.get("q") or None,
                    semantic_type=request.args.get("semantic_type") or None,
                    page=int_arg("page", 1),
                    page_size=int_arg("page_size", 25),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concepts list failed")
            return {"error": "semantic concepts list failed"}, 500

    @token_required
    @semantic_concepts_ns.expect(concept_create_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticConceptService().create_concept(body)
            return {"row": row}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept create failed")
            return {"error": "semantic concept create failed"}, 500


@semantic_concepts_ns.route("/keys")
class SemanticConceptKeyCollection(ForgeResource):
    @token_required
    @semantic_concepts_ns.doc(
        params={
            "vertical": "Filter by vertical",
        }
    )
    def get(self):
        try:
            return (
                SemanticConceptService().list_concept_keys(
                    vertical=request.args.get("vertical") or None,
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept keys list failed")
            return {"error": "semantic concept keys list failed"}, 500


@semantic_concepts_ns.route("/<int:concept_id>")
class SemanticConceptById(ForgeResource):
    @token_required
    def get(self, concept_id: int):
        try:
            row = SemanticConceptService().get_concept(concept_id)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept get failed")
            return {"error": "semantic concept get failed"}, 500

    @token_required
    @semantic_concepts_ns.expect(concept_patch_model, validate=False)
    def patch(self, concept_id: int):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticConceptService().patch_concept(concept_id, body)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept patch failed")
            return {"error": "semantic concept patch failed"}, 500

    @token_required
    def delete(self, concept_id: int):
        try:
            _require_admin()
            SemanticConceptService().delete_concept(concept_id)
            return {}, 204
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept delete failed")
            return {"error": "semantic concept delete failed"}, 500


@semantic_concepts_ns.route("/seed")
class SemanticConceptSeed(ForgeResource):
    @token_required
    @semantic_concepts_ns.expect(seed_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            vertical = str(body.get("vertical") or "").strip().lower()
            if vertical == "":
                raise ForgeError("vertical is required", status_code=400)
            result = SemanticConceptService().seed(vertical)
            return {"result": result}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept seed failed")
            return {"error": "semantic concept seed failed"}, 500


@semantic_concepts_ns.route("/rebuild-index")
class SemanticConceptRebuildIndex(ForgeResource):
    @token_required
    @semantic_concepts_ns.expect(rebuild_index_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            vertical_norm = str(body.get("vertical_norm") or "generic").strip().lower() or "generic"
            result = SemanticConceptEmbeddingService().rebuild_semantic_concept_index(vertical_norm=vertical_norm)
            return {"result": result, "vertical_norm": vertical_norm}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept index rebuild failed")
            return {"error": "semantic concept index rebuild failed"}, 500


@semantic_concepts_ns.route("/backfill-primary-keys")
class SemanticConceptBackfillPrimaryKeys(ForgeResource):
    @token_required
    @semantic_concepts_ns.expect(backfill_primary_keys_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            result = SemanticConceptService().backfill_primary_semantic_keys(
                workspace_id=body.get("workspace_id"),
                vertical_norm=body.get("vertical_norm"),
                dry_run=bool(body.get("dry_run", True)),
            )
            return {"result": result}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept backfill primary keys failed")
            return {"error": "semantic concept backfill primary keys failed"}, 500


@semantic_concept_aliases_ns.route("")
class SemanticConceptAliasCollection(ForgeResource):
    @token_required
    @semantic_concept_aliases_ns.doc(
        params={
            "vertical": "Filter by vertical",
            "concept_key": "Filter by concept_key",
            "q": "Search aliases",
        }
    )
    def get(self):
        try:
            result = SemanticConceptService().list_aliases(
                vertical=request.args.get("vertical") or None,
                concept_key=request.args.get("concept_key") or None,
                q=request.args.get("q") or None,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic alias list failed")
            return {"error": "semantic alias list failed"}, 500

    @token_required
    @semantic_concept_aliases_ns.expect(alias_create_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticConceptService().create_alias(body)
            return {"row": row}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic alias create failed")
            return {"error": "semantic alias create failed"}, 500


@semantic_concept_aliases_ns.route("/<int:alias_id>")
class SemanticConceptAliasById(ForgeResource):
    @token_required
    def get(self, alias_id: int):
        try:
            row = SemanticConceptService().get_alias(alias_id)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic alias get failed")
            return {"error": "semantic alias get failed"}, 500

    @token_required
    @semantic_concept_aliases_ns.expect(alias_patch_model, validate=False)
    def patch(self, alias_id: int):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticConceptService().patch_alias(alias_id, body)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic alias patch failed")
            return {"error": "semantic alias patch failed"}, 500

    @token_required
    def delete(self, alias_id: int):
        try:
            _require_admin()
            SemanticConceptService().delete_alias(alias_id)
            return {}, 204
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic alias delete failed")
            return {"error": "semantic alias delete failed"}, 500


@semantic_value_aliases_ns.route("")
class SemanticValueAliasCollection(ForgeResource):
    @token_required
    @semantic_value_aliases_ns.doc(
        params={
            "vertical": "Filter by vertical",
            "semantic_concept_id": "Filter by semantic_concept_id",
            "q": "Search alias/canonical values",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        try:
            result = SemanticConceptService().list_value_aliases(
                vertical=request.args.get("vertical") or None,
                semantic_concept_id=_optional_int(request.args.get("semantic_concept_id"), "semantic_concept_id"),
                q=request.args.get("q") or None,
                page=int_arg("page", 1),
                page_size=int_arg("page_size", 25),
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic value alias list failed")
            return {"error": "semantic value alias list failed"}, 500

    @token_required
    @semantic_value_aliases_ns.expect(value_alias_create_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticConceptService().create_value_alias(body)
            return {"row": row}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic value alias create failed")
            return {"error": "semantic value alias create failed"}, 500


@semantic_value_aliases_ns.route("/<int:value_alias_id>")
class SemanticValueAliasById(ForgeResource):
    @token_required
    def get(self, value_alias_id: int):
        try:
            row = SemanticConceptService().get_value_alias(value_alias_id)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic value alias get failed")
            return {"error": "semantic value alias get failed"}, 500

    @token_required
    @semantic_value_aliases_ns.expect(value_alias_patch_model, validate=False)
    def patch(self, value_alias_id: int):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticConceptService().patch_value_alias(value_alias_id, body)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic value alias patch failed")
            return {"error": "semantic value alias patch failed"}, 500

    @token_required
    def delete(self, value_alias_id: int):
        try:
            _require_admin()
            SemanticConceptService().delete_value_alias(value_alias_id)
            return {}, 204
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic value alias delete failed")
            return {"error": "semantic value alias delete failed"}, 500


@semantic_concept_column_maps_ns.route("")
class SemanticConceptColumnMapCollection(ForgeResource):
    @token_required
    @semantic_concept_column_maps_ns.doc(
        params={
            "vertical": "Filter by vertical",
            "semantic_concept_id": "Filter by semantic_concept_id",
            "concept_key": "Filter by concept_key (contains, case-insensitive)",
            "model_column_id": "Filter by model_column_id",
            "column_name": "Filter by column_name (contains, case-insensitive)",
            "relationship_kind": "Filter by relationship_kind",
            "q": "Type-ahead search across concept_key, concept_name, column_name, model_table_name",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        try:
            result = SemanticConceptService().list_concept_column_maps(
                vertical=request.args.get("vertical") or None,
                semantic_concept_id=_optional_int(request.args.get("semantic_concept_id"), "semantic_concept_id"),
                concept_key=request.args.get("concept_key") or None,
                model_column_id=_optional_int(request.args.get("model_column_id"), "model_column_id"),
                column_name=request.args.get("column_name") or None,
                relationship_kind=request.args.get("relationship_kind") or None,
                q=request.args.get("q") or None,
                page=int_arg("page", 1),
                page_size=int_arg("page_size", 25),
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept-column map list failed")
            return {"error": "semantic concept-column map list failed"}, 500

    @token_required
    @semantic_concept_column_maps_ns.expect(concept_column_map_create_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticConceptService().create_concept_column_map(body)
            return {"row": row}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept-column map create failed")
            return {"error": "semantic concept-column map create failed"}, 500


@semantic_concept_column_maps_ns.route("/<int:map_id>")
class SemanticConceptColumnMapById(ForgeResource):
    @token_required
    def get(self, map_id: int):
        try:
            row = SemanticConceptService().get_concept_column_map(map_id)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept-column map get failed")
            return {"error": "semantic concept-column map get failed"}, 500

    @token_required
    @semantic_concept_column_maps_ns.expect(concept_column_map_patch_model, validate=False)
    def patch(self, map_id: int):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticConceptService().patch_concept_column_map(map_id, body)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept-column map patch failed")
            return {"error": "semantic concept-column map patch failed"}, 500

    @token_required
    def delete(self, map_id: int):
        try:
            _require_admin()
            SemanticConceptService().delete_concept_column_map(map_id)
            return {}, 204
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept-column map delete failed")
            return {"error": "semantic concept-column map delete failed"}, 500


def _require_admin() -> None:
    if not bool(getattr(g, "is_admin", False)):
        raise ForgeError("Admin access required", status_code=403)


def _optional_int(value: Any, field: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except Exception as exc:
        raise ForgeError(f"{field} must be an integer", status_code=400) from exc
