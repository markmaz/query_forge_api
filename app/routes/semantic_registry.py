from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Namespace, Resource, fields

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.routes.request_helpers import int_arg
from app.services.semantic.semantic_registry_service import SemanticRegistryService

logger = logging.getLogger(__name__)

semantic_registry_ns = Namespace("semantic-registry", description="Semantic registry endpoints")

semantic_registry_entry_model = semantic_registry_ns.model(
    "SemanticRegistryEntry",
    {
        "id": fields.Integer(readOnly=True),
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


def _strip_semantic_vertical_fields(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = dict(value)
        if "rows" in cleaned and isinstance(cleaned["rows"], list):
            cleaned["rows"] = [_strip_semantic_vertical_fields(row) for row in cleaned["rows"]]
        return cleaned
    return value


@semantic_registry_ns.route("")
class SemanticRegistryCollection(Resource):
    @token_required
    @require_access("semantic")
    @semantic_registry_ns.doc(
        params={
            "q": "Search concept_key and description",
            "semantic_type": "Filter by semantic_type",
            "entity": "Filter by entity",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        result = SemanticRegistryService().list_entries(
            q=(request.args.get("q") or None),
            semantic_type=(request.args.get("semantic_type") or None),
            entity=(request.args.get("entity") or None),
            page=int_arg("page", 1),
            page_size=int_arg("page_size", 25),
        )
        return _strip_semantic_vertical_fields(result), 200

    @token_required
    @require_access("semantic", role="admin")
    @semantic_registry_ns.expect(semantic_registry_entry_model, validate=False)
    def post(self):
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        row = SemanticRegistryService().create_entry(body)
        return {"row": _strip_semantic_vertical_fields(row)}, 201


@semantic_registry_ns.route("/<int:entry_id>")
class SemanticRegistryById(Resource):
    @token_required
    @require_access("semantic")
    def get(self, entry_id: int):
        row = SemanticRegistryService().get_entry(entry_id)
        return {"row": _strip_semantic_vertical_fields(row)}, 200

    @token_required
    @require_access("semantic", role="admin")
    @semantic_registry_ns.expect(semantic_registry_entry_model, validate=False)
    def patch(self, entry_id: int):
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        row = SemanticRegistryService().update_entry(entry_id, body)
        return {"row": _strip_semantic_vertical_fields(row)}, 200

    @token_required
    @require_access("semantic", role="admin")
    def delete(self, entry_id: int):
        SemanticRegistryService().delete_entry(entry_id)
        return {"deleted": True, "id": entry_id}, 200
