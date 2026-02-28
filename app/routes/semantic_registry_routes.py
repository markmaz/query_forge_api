from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Namespace, Resource, fields

from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.routes._route_utils import int_arg
from app.services.semantic_registry_service import SemanticRegistryService

logger = logging.getLogger(__name__)

semantic_registry_ns = Namespace(
    "semantic-registry",
    description="Semantic registry CRUD for vertical-agnostic business semantics",
)

semantic_registry_entry_model = semantic_registry_ns.model(
    "SemanticRegistryEntry",
    {
        "id": fields.String(description="Primary UUID identifier"),
        "vertical": fields.String(
            required=False,
            description="Optional vertical/domain scope (education, healthcare, finance). Null for global concepts.",
        ),
        "concept_key": fields.String(
            required=True,
            description="Unique business concept key used by ranking/planning layers.",
        ),
        "semantic_type": fields.String(
            required=True,
            description="High-level semantic type: entity|identifier|attribute|geography|time|metric|flag|reference.",
        ),
        "sub_type": fields.String(
            required=False,
            description="Fine-grained subtype path, e.g. attribute.student.first_name.",
        ),
        "entity": fields.String(required=False, description="Business entity this concept belongs to."),
        "description": fields.String(required=False, description="Human-readable description of business meaning."),
        "granularity_rank": fields.Integer(
            required=False,
            description="Lower values indicate more specific granularity.",
        ),
        "filter_allowed": fields.Boolean(
            required=False,
            description="Whether filtering on this concept is allowed.",
        ),
        "group_by_allowed": fields.Boolean(
            required=False,
            description="Whether grouping on this concept is allowed.",
        ),
        "aggregation_allowed": fields.Boolean(
            required=False,
            description="Whether aggregation on this concept is allowed.",
        ),
        "identifier": fields.Boolean(
            required=False,
            description="True if this concept is an identifier.",
        ),
        "metric": fields.Boolean(
            required=False,
            description="True if this concept is numeric/aggregatable.",
        ),
        "display_priority": fields.Integer(
            required=False,
            description="Display ordering priority for selection UIs.",
        ),
        "sensitive": fields.Boolean(
            required=False,
            description="True when concept may contain sensitive data.",
        ),
        "created_at": fields.DateTime(description="Created timestamp (UTC)."),
        "updated_at": fields.DateTime(description="Updated timestamp (UTC)."),
    },
)


def _handle_service_error(exc: ServiceError):
    return {"error": str(exc)}, getattr(exc, "status_code", 400) or 400


@semantic_registry_ns.route("")
class SemanticRegistryCollection(Resource):
    @token_required
    @semantic_registry_ns.doc(
        params={
            "limit": "Page size (default 50, max 500).",
            "offset": "Pagination offset (default 0).",
            "vertical": "Filter by vertical/domain.",
            "semantic_type": "Filter by semantic_type.",
            "q": "Case-insensitive free-text filter across concept_key/sub_type/entity/description.",
        }
    )
    def get(self):
        try:
            limit = int_arg("limit", 50)
            offset = int_arg("offset", 0)
            vertical = (request.args.get("vertical") or "").strip() or None
            semantic_type = (request.args.get("semantic_type") or "").strip() or None
            q = (request.args.get("q") or "").strip() or None

            rows, total = SemanticRegistryService().list_entries(
                limit=limit,
                offset=offset,
                vertical=vertical,
                semantic_type=semantic_type,
                q=q,
            )
            return {"rows": rows, "total": total, "limit": max(1, min(limit, 500)), "offset": max(0, offset)}, 200
        except ServiceError as exc:
            return _handle_service_error(exc)
        except Exception:
            logger.exception("Semantic registry list failed")
            return {"error": "Semantic registry list failed"}, 500

    @token_required
    @semantic_registry_ns.expect(semantic_registry_entry_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticRegistryService().create_entry(body)
            return {"row": row}, 201
        except ServiceError as exc:
            return _handle_service_error(exc)
        except Exception:
            logger.exception("Semantic registry create failed")
            return {"error": "Semantic registry create failed"}, 500


@semantic_registry_ns.route("/<string:entry_id>")
class SemanticRegistryById(Resource):
    @token_required
    def get(self, entry_id: str):
        try:
            row = SemanticRegistryService().get_entry(entry_id)
            return {"row": row}, 200
        except ServiceError as exc:
            return _handle_service_error(exc)
        except Exception:
            logger.exception("Semantic registry get failed")
            return {"error": "Semantic registry get failed"}, 500

    @token_required
    @semantic_registry_ns.expect(semantic_registry_entry_model, validate=False)
    def patch(self, entry_id: str):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            row = SemanticRegistryService().update_entry(entry_id, body)
            return {"row": row}, 200
        except ServiceError as exc:
            return _handle_service_error(exc)
        except Exception:
            logger.exception("Semantic registry update failed")
            return {"error": "Semantic registry update failed"}, 500

    @token_required
    def delete(self, entry_id: str):
        try:
            SemanticRegistryService().delete_entry(entry_id)
            return {"deleted": True, "id": entry_id}, 200
        except ServiceError as exc:
            return _handle_service_error(exc)
        except Exception:
            logger.exception("Semantic registry delete failed")
            return {"error": "Semantic registry delete failed"}, 500

