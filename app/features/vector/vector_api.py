from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Namespace, fields, Resource

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.services.vector import DomainVectorIndexService

from .service import vector_feature_service

logger = logging.getLogger(__name__)

vector_ns = Namespace("vector", description="Domain-first vector retrieval")

_domain_search_request_model = vector_ns.model(
    "DomainVectorSearchRequest",
    {
        "workspace_id": fields.String(required=False),
        "query": fields.String(required=True),
        "limit": fields.Integer(required=False, default=5),
        "score_threshold": fields.Float(required=False, default=0.2),
        "include_payload": fields.Boolean(required=False, default=True),
    },
)


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return default


def _parse_int(value: Any, *, default: int, minimum: int = 1) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except Exception:
        raise ForgeError("limit must be an integer", status_code=400)
    return max(minimum, parsed)


def _parse_float(value: Any, *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        raise ForgeError("score_threshold must be numeric", status_code=400)


@vector_ns.route("/domains/search")
class DomainVectorSearch(Resource):
    @token_required
    @require_access("vector")
    @vector_ns.expect(_domain_search_request_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            header_workspace_id = vector_feature_service.extract_workspace_id()
            payload_workspace_id = str(body.get("workspace_id") or "").strip()
            if payload_workspace_id and payload_workspace_id != header_workspace_id:
                raise ForgeError("workspace_id must match X-Workspace-Id header", status_code=400)

            query = str(body.get("query") or "").strip()
            if not query:
                raise ForgeError("query is required", status_code=400)

            limit = _parse_int(body.get("limit"), default=5)
            score_threshold = _parse_float(body.get("score_threshold"), default=0.2)
            include_payload = _parse_bool(body.get("include_payload"), default=True)

            svc = DomainVectorIndexService()
            result = svc.search_domains(
                workspace_id=header_workspace_id,
                query=query,
                limit=limit,
                score_threshold=score_threshold,
                include_payload=include_payload,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain vector search failed")
            return {"error": "domain vector search failed"}, 500
