from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from flask import request
from flask_restx import Namespace, Resource, fields

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import int_arg
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
        "parent_concept_key": fields.String(readOnly=True),
        "parent_concept_name": fields.String(readOnly=True),
        "parent_display_label": fields.String(readOnly=True),
        "child_concept_key": fields.String(readOnly=True),
        "child_concept_name": fields.String(readOnly=True),
        "child_display_label": fields.String(readOnly=True),
    },
)

semantic_relationship_patch_model = semantic_relationships_ns.model(
    "SemanticRelationshipPatch",
    {
        "parent_concept_id": fields.Integer(required=False),
        "child_concept_id": fields.Integer(required=False),
        "relationship_type": fields.String(required=False),
    },
)


def _strip_semantic_vertical_fields(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = dict(value)
        if "rows" in cleaned and isinstance(cleaned["rows"], list):
            cleaned["rows"] = [_strip_semantic_vertical_fields(row) for row in cleaned["rows"]]
        return cleaned
    return value


@semantic_relationships_ns.route("")
class SemanticRelationshipsCollection(Resource):
    @token_required
    @require_access("semantic")
    @semantic_relationships_ns.doc(
        params={
            "parent_id": "Filter by parent concept id",
            "child_id": "Filter by child concept id",
            "relationship_type": "Filter by relationship type",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        result = SemanticRelationshipService().list_relationships(
            parent_id=_optional_int(request.args.get("parent_id"), "parent_id"),
            child_id=_optional_int(request.args.get("child_id"), "child_id"),
            relationship_type=request.args.get("relationship_type") or None,
            page=int_arg("page", 1),
            page_size=int_arg("page_size", 25),
        )
        return _strip_semantic_vertical_fields(result), 200

    @token_required
    @require_access("semantic", role="admin")
    @semantic_relationships_ns.expect(semantic_relationship_model, validate=False)
    def post(self):
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        row = SemanticRelationshipService().create_relationship(body)
        return {"row": _strip_semantic_vertical_fields(row)}, 201


@semantic_relationships_ns.route("/concepts")
class SemanticRelationshipConceptLookup(Resource):
    @token_required
    @require_access("semantic")
    @semantic_relationships_ns.doc(params={"q": "Search by concept key/name/description", "page": "Page number", "page_size": "Page size"})
    def get(self):
        result = SemanticRelationshipService().list_concept_lookup(
            q=request.args.get("q") or None,
            page=int_arg("page", 1),
            page_size=int_arg("page_size", 100),
        )
        return _strip_semantic_vertical_fields(result), 200


@semantic_relationships_ns.route("/<int:relationship_id>")
class SemanticRelationshipsById(Resource):
    @token_required
    @require_access("semantic")
    def get(self, relationship_id: int):
        row = SemanticRelationshipService().get_relationship(relationship_id)
        return {"row": _strip_semantic_vertical_fields(row)}, 200

    @token_required
    @require_access("semantic", role="admin")
    @semantic_relationships_ns.expect(semantic_relationship_patch_model, validate=False)
    def patch(self, relationship_id: int):
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        row = SemanticRelationshipService().patch_relationship(relationship_id, body)
        return {"row": _strip_semantic_vertical_fields(row)}, 200

    @token_required
    @require_access("semantic", role="admin")
    def delete(self, relationship_id: int):
        SemanticRelationshipService().delete_relationship(relationship_id)
        return {"deleted": True, "id": relationship_id}, 200


def _optional_int(value: Optional[str], field: str) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ForgeError(f"{field} must be an integer", status_code=400) from exc
