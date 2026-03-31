from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from flask import request
from flask_restx import Namespace, fields
from flask_restx import Resource

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import int_arg
from app.services.semantic.semantic_mapping_service import SemanticMappingService

logger = logging.getLogger(__name__)

semantic_mappings_ns = Namespace("semantic-mappings", description="Semantic column mapping endpoints")

semantic_mapping_model = semantic_mappings_ns.model(
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


@semantic_mappings_ns.route("")
class SemanticMappingsCollection(Resource):
    @token_required
    @require_access("semantic")
    @semantic_mappings_ns.doc(
        params={
            "vertical": "Filter by vertical scope",
            "workspace_id": "Filter by workspace",
            "concept_key": "Filter by concept_key",
            "model_column_id": "Filter by model_column_id",
            "workspace_column_id": "Filter by workspace_column_id",
            "table_name": "Filter by table_name",
            "column_name": "Filter by column_name",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        try:
            result = SemanticMappingService().list_mappings(
                vertical=request.args.get("vertical") or None,
                workspace_id=request.args.get("workspace_id") or None,
                concept_key=request.args.get("concept_key") or None,
                model_column_id=_optional_int(request.args.get("model_column_id"), "model_column_id"),
                workspace_column_id=_optional_int(request.args.get("workspace_column_id"), "workspace_column_id"),
                table_name=request.args.get("table_name") or None,
                column_name=request.args.get("column_name") or None,
                page=int_arg("page", 1),
                page_size=int_arg("page_size", 25),
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic mappings list failed")
            return {"error": "semantic mappings list failed"}, 500

    @token_required
    @require_access("semantic", role="admin")
    @semantic_mappings_ns.expect(semantic_mapping_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticMappingService().create_mapping(body)
            return {"row": row}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic mapping create failed")
            return {"error": "semantic mapping create failed"}, 500


@semantic_mappings_ns.route("/<int:mapping_id>")
class SemanticMappingsById(Resource):
    @token_required
    @require_access("semantic", role="admin")
    def delete(self, mapping_id: int):
        try:
            SemanticMappingService().delete_mapping(mapping_id)
            return {"deleted": True, "id": mapping_id}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic mapping delete failed")
            return {"error": "semantic mapping delete failed"}, 500


def _optional_int(value: Optional[str], field: str) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except Exception as exc:
        raise ForgeError(f"{field} must be an integer", status_code=400) from exc
