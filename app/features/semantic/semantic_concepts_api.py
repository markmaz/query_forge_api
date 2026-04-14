from __future__ import annotations

import logging
from typing import Any, Dict

from flask import g, request
from flask_restx import Namespace, Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import int_arg
from app.services.embedding.semantic_concept_embedding_service import SemanticConceptEmbeddingService
from app.services.semantic.semantic_concept_service import SemanticConceptService

from .schemas import register_concept_models
from .service import semantic_feature_service

logger = logging.getLogger(__name__)

semantic_concepts_ns = Namespace("semantic-concepts", description="Semantic canonical concept endpoints")
semantic_concept_aliases_ns = Namespace("semantic-concept-aliases", description="Semantic concept alias endpoints")
semantic_value_aliases_ns = Namespace("semantic-value-aliases", description="Semantic concept value alias endpoints")
semantic_concept_column_maps_ns = Namespace(
    "semantic-concept-column-maps",
    description="Semantic concept to workspace_column mapping endpoints",
)
_models = register_concept_models(
    semantic_concepts_ns,
    semantic_concept_aliases_ns,
    semantic_value_aliases_ns,
    semantic_concept_column_maps_ns,
)
concept_create_model = _models["concept_create_model"]
concept_patch_model = _models["concept_patch_model"]
seed_model = _models["seed_model"]
rebuild_index_model = _models["rebuild_index_model"]
backfill_primary_keys_model = _models["backfill_primary_keys_model"]
alias_create_model = _models["alias_create_model"]
alias_patch_model = _models["alias_patch_model"]
value_alias_create_model = _models["value_alias_create_model"]
value_alias_patch_model = _models["value_alias_patch_model"]
concept_column_map_create_model = _models["concept_column_map_create_model"]
concept_column_map_patch_model = _models["concept_column_map_patch_model"]


@semantic_concepts_ns.route("")
class SemanticConceptCollection(Resource):
    @token_required
    @require_access("semantic")
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
                semantic_feature_service.build_concept_service(
                    concept_service_factory=SemanticConceptService
                ).list_concepts(
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
    @require_access("semantic", role="admin")
    @semantic_concepts_ns.expect(concept_create_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).create_concept(body)
            return {"row": row}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept create failed")
            return {"error": "semantic concept create failed"}, 500


@semantic_concepts_ns.route("/keys")
class SemanticConceptKeyCollection(Resource):
    @token_required
    @require_access("semantic")
    @semantic_concepts_ns.doc(params={"vertical": "Filter by vertical"})
    def get(self):
        try:
            return (
                semantic_feature_service.build_concept_service(
                    concept_service_factory=SemanticConceptService
                ).list_concept_keys(
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
class SemanticConceptById(Resource):
    @token_required
    @require_access("semantic")
    def get(self, concept_id: int):
        try:
            row = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).get_concept(concept_id)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept get failed")
            return {"error": "semantic concept get failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    @semantic_concepts_ns.expect(concept_patch_model, validate=False)
    def patch(self, concept_id: int):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).patch_concept(concept_id, body)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept patch failed")
            return {"error": "semantic concept patch failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    def delete(self, concept_id: int):
        try:
            _require_admin()
            semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).delete_concept(concept_id)
            return {}, 204
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept delete failed")
            return {"error": "semantic concept delete failed"}, 500


@semantic_concepts_ns.route("/seed")
class SemanticConceptSeed(Resource):
    @token_required
    @require_access("semantic", role="admin")
    @semantic_concepts_ns.expect(seed_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            vertical = str(body.get("vertical") or "").strip().lower()
            if vertical == "":
                raise ForgeError("vertical is required", status_code=400)
            result = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).seed(vertical)
            return {"result": result}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept seed failed")
            return {"error": "semantic concept seed failed"}, 500


@semantic_concepts_ns.route("/rebuild-index")
class SemanticConceptRebuildIndex(Resource):
    @token_required
    @require_access("semantic", role="admin")
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
class SemanticConceptBackfillPrimaryKeys(Resource):
    @token_required
    @require_access("semantic", role="admin")
    @semantic_concepts_ns.expect(backfill_primary_keys_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            result = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).backfill_primary_semantic_keys(
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
class SemanticConceptAliasCollection(Resource):
    @token_required
    @require_access("semantic")
    @semantic_concept_aliases_ns.doc(
        params={
            "vertical": "Filter by vertical",
            "concept_key": "Filter by concept_key",
            "q": "Search aliases",
        }
    )
    def get(self):
        try:
            result = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).list_aliases(
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
    @require_access("semantic", role="admin")
    @semantic_concept_aliases_ns.expect(alias_create_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).create_alias(body)
            return {"row": row}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic alias create failed")
            return {"error": "semantic alias create failed"}, 500


@semantic_concept_aliases_ns.route("/<int:alias_id>")
class SemanticConceptAliasById(Resource):
    @token_required
    @require_access("semantic")
    def get(self, alias_id: int):
        try:
            row = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).get_alias(alias_id)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic alias get failed")
            return {"error": "semantic alias get failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    @semantic_concept_aliases_ns.expect(alias_patch_model, validate=False)
    def patch(self, alias_id: int):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).patch_alias(alias_id, body)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic alias patch failed")
            return {"error": "semantic alias patch failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    def delete(self, alias_id: int):
        try:
            _require_admin()
            semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).delete_alias(alias_id)
            return {}, 204
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic alias delete failed")
            return {"error": "semantic alias delete failed"}, 500


@semantic_value_aliases_ns.route("")
class SemanticValueAliasCollection(Resource):
    @token_required
    @require_access("semantic")
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
            result = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).list_value_aliases(
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
    @require_access("semantic", role="admin")
    @semantic_value_aliases_ns.expect(value_alias_create_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).create_value_alias(body)
            return {"row": row}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic value alias create failed")
            return {"error": "semantic value alias create failed"}, 500


@semantic_value_aliases_ns.route("/<int:value_alias_id>")
class SemanticValueAliasById(Resource):
    @token_required
    @require_access("semantic")
    def get(self, value_alias_id: int):
        try:
            row = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).get_value_alias(value_alias_id)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic value alias get failed")
            return {"error": "semantic value alias get failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    @semantic_value_aliases_ns.expect(value_alias_patch_model, validate=False)
    def patch(self, value_alias_id: int):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).patch_value_alias(value_alias_id, body)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic value alias patch failed")
            return {"error": "semantic value alias patch failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    def delete(self, value_alias_id: int):
        try:
            _require_admin()
            semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).delete_value_alias(value_alias_id)
            return {}, 204
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic value alias delete failed")
            return {"error": "semantic value alias delete failed"}, 500


@semantic_concept_column_maps_ns.route("")
class SemanticConceptColumnMapCollection(Resource):
    @token_required
    @require_access("semantic")
    @semantic_concept_column_maps_ns.doc(
        params={
            "vertical": "Filter by vertical",
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
        try:
            result = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).list_concept_column_maps(
                vertical=request.args.get("vertical") or None,
                semantic_concept_id=_optional_int(request.args.get("semantic_concept_id"), "semantic_concept_id"),
                concept_key=request.args.get("concept_key") or None,
                workspace_column_id=_optional_int(request.args.get("workspace_column_id"), "workspace_column_id"),
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
    @require_access("semantic", role="admin")
    @semantic_concept_column_maps_ns.expect(concept_column_map_create_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).create_concept_column_map(body)
            return {"row": row}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept-column map create failed")
            return {"error": "semantic concept-column map create failed"}, 500


@semantic_concept_column_maps_ns.route("/<int:map_id>")
class SemanticConceptColumnMapById(Resource):
    @token_required
    @require_access("semantic")
    def get(self, map_id: int):
        try:
            row = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).get_concept_column_map(map_id)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept-column map get failed")
            return {"error": "semantic concept-column map get failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    @semantic_concept_column_maps_ns.expect(concept_column_map_patch_model, validate=False)
    def patch(self, map_id: int):
        try:
            _require_admin()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).patch_concept_column_map(map_id, body)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic concept-column map patch failed")
            return {"error": "semantic concept-column map patch failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    def delete(self, map_id: int):
        try:
            _require_admin()
            semantic_feature_service.build_concept_service(
                concept_service_factory=SemanticConceptService
            ).delete_concept_column_map(map_id)
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
