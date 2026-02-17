from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from flask import request
from flask_restx import Namespace, Resource, fields

from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.routes._route_utils import int_arg
from app.services.semantic.semantic_relationship_service import SemanticRelationshipService

logger = logging.getLogger(__name__)

semantic_relationships_ns = Namespace("semantic-relationships", description="Semantic relationship endpoints")

semantic_relationship_model = semantic_relationships_ns.model(
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
        "child_concept_key": fields.String(readOnly=True),
    },
)


@semantic_relationships_ns.route("")
class SemanticRelationshipsCollection(Resource):
    @token_required
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
            result = SemanticRelationshipService().list_relationships(
                vertical=request.args.get("vertical") or None,
                parent_id=_optional_int(request.args.get("parent_id"), "parent_id"),
                child_id=_optional_int(request.args.get("child_id"), "child_id"),
                relationship_type=request.args.get("relationship_type") or None,
                page=int_arg("page", 1),
                page_size=int_arg("page_size", 25),
            )
            return result, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic relationships list failed")
            return {"error": "semantic relationships list failed"}, 500

    @token_required
    @semantic_relationships_ns.expect(semantic_relationship_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticRelationshipService().create_relationship(body)
            return {"row": row}, 201
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic relationship create failed")
            return {"error": "semantic relationship create failed"}, 500


@semantic_relationships_ns.route("/<int:relationship_id>")
class SemanticRelationshipsById(Resource):
    @token_required
    def delete(self, relationship_id: int):
        try:
            SemanticRelationshipService().delete_relationship(relationship_id)
            return {"deleted": True, "id": relationship_id}, 200
        except ServiceError as exc:
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
        raise ServiceError(f"{field} must be an integer", status_code=400) from exc
