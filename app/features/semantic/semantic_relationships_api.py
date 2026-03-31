from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from flask import request
from flask_restx import Namespace, Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import int_arg
from app.services.semantic.semantic_relationship_service import SemanticRelationshipService

from .schemas import register_relationship_models
from .service import semantic_feature_service

logger = logging.getLogger(__name__)

semantic_relationships_ns = Namespace("semantic-relationships", description="Semantic relationship endpoints")
semantic_relationship_model, semantic_relationship_patch_model = register_relationship_models(
    semantic_relationships_ns
)


@semantic_relationships_ns.route("")
class SemanticRelationshipsCollection(Resource):
    @token_required
    @require_access("semantic")
    @semantic_relationships_ns.doc(
        params={
            "vertical": "Filter by vertical scope",
            "parent_id": "Filter by parent concept id",
            "child_id": "Filter by child concept id",
            "relationship_type": "Filter by relationship type",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        try:
            result = semantic_feature_service.build_relationship_service(
                relationship_service_factory=SemanticRelationshipService
            ).list_relationships(
                vertical=request.args.get("vertical") or None,
                parent_id=_optional_int(request.args.get("parent_id"), "parent_id"),
                child_id=_optional_int(request.args.get("child_id"), "child_id"),
                relationship_type=request.args.get("relationship_type") or None,
                page=int_arg("page", 1),
                page_size=int_arg("page_size", 25),
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic relationships list failed")
            return {"error": "semantic relationships list failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    @semantic_relationships_ns.expect(semantic_relationship_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = semantic_feature_service.build_relationship_service(
                relationship_service_factory=SemanticRelationshipService
            ).create_relationship(body)
            return {"row": row}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic relationship create failed")
            return {"error": "semantic relationship create failed"}, 500


@semantic_relationships_ns.route("/concepts")
class SemanticRelationshipConceptLookup(Resource):
    @token_required
    @require_access("semantic")
    @semantic_relationships_ns.doc(
        params={
            "vertical": "Filter by vertical scope",
            "q": "Search by concept key/name/description",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        try:
            result = semantic_feature_service.build_relationship_service(
                relationship_service_factory=SemanticRelationshipService
            ).list_concept_lookup(
                vertical=request.args.get("vertical") or None,
                q=request.args.get("q") or None,
                page=int_arg("page", 1),
                page_size=int_arg("page_size", 100),
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic relationship concept lookup failed")
            return {"error": "semantic relationship concept lookup failed"}, 500


@semantic_relationships_ns.route("/<int:relationship_id>")
class SemanticRelationshipsById(Resource):
    @token_required
    @require_access("semantic")
    def get(self, relationship_id: int):
        try:
            row = semantic_feature_service.build_relationship_service(
                relationship_service_factory=SemanticRelationshipService
            ).get_relationship(relationship_id)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic relationship get failed")
            return {"error": "semantic relationship get failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    @semantic_relationships_ns.expect(semantic_relationship_patch_model, validate=False)
    def patch(self, relationship_id: int):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = semantic_feature_service.build_relationship_service(
                relationship_service_factory=SemanticRelationshipService
            ).patch_relationship(relationship_id, body)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic relationship patch failed")
            return {"error": "semantic relationship patch failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    def delete(self, relationship_id: int):
        try:
            semantic_feature_service.build_relationship_service(
                relationship_service_factory=SemanticRelationshipService
            ).delete_relationship(relationship_id)
            return {"deleted": True, "id": relationship_id}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic relationship delete failed")
            return {"error": "semantic relationship delete failed"}, 500


def _optional_int(value: Optional[str], field: str) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except Exception as exc:
        raise ForgeError(f"{field} must be an integer", status_code=400) from exc
