from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Namespace, fields
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import int_arg
from app.services.semantic.semantic_registry_service import SemanticRegistryService

logger = logging.getLogger(__name__)

semantic_registry_ns = Namespace("semantic-registry", description="Semantic registry endpoints")

semantic_registry_entry_model = semantic_registry_ns.model(
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


@semantic_registry_ns.route("")
class SemanticRegistryCollection(ForgeResource):
    @token_required
    @semantic_registry_ns.doc(
        params={
            "vertical": "Filter by vertical scope",
            "q": "Search concept_key and description",
            "semantic_type": "Filter by semantic_type",
            "entity": "Filter by entity",
            "page": "Page number",
            "page_size": "Page size",
        }
    )
    def get(self):
        try:
            result = SemanticRegistryService().list_entries(
                vertical=(request.args.get("vertical") or None),
                q=(request.args.get("q") or None),
                semantic_type=(request.args.get("semantic_type") or None),
                entity=(request.args.get("entity") or None),
                page=int_arg("page", 1),
                page_size=int_arg("page_size", 25),
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic registry list failed")
            return {"error": "semantic registry list failed"}, 500

    @token_required
    @semantic_registry_ns.expect(semantic_registry_entry_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticRegistryService().create_entry(body)
            return {"row": row}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic registry create failed")
            return {"error": "semantic registry create failed"}, 500


@semantic_registry_ns.route("/<int:entry_id>")
class SemanticRegistryById(ForgeResource):
    @token_required
    def get(self, entry_id: int):
        try:
            row = SemanticRegistryService().get_entry(entry_id)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic registry get failed")
            return {"error": "semantic registry get failed"}, 500

    @token_required
    @semantic_registry_ns.expect(semantic_registry_entry_model, validate=False)
    def patch(self, entry_id: int):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticRegistryService().update_entry(entry_id, body)
            return {"row": row}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic registry update failed")
            return {"error": "semantic registry update failed"}, 500

    @token_required
    def delete(self, entry_id: int):
        try:
            SemanticRegistryService().delete_entry(entry_id)
            return {"deleted": True, "id": entry_id}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic registry delete failed")
            return {"error": "semantic registry delete failed"}, 500
