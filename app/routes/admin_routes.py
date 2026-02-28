from __future__ import annotations

import logging

from flask import g, request
from flask_restx import Namespace, Resource

from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.routes._route_utils import get_workspace_id_from_header
from app.services.embedding.semantic_concept_embedding_service import SemanticConceptEmbeddingService
from app.services.vector import DomainVectorIndexService

admin_ns = Namespace("admin", description="Admin operations")
logger = logging.getLogger(__name__)

@admin_ns.route("/healthz")
class ShowHealth(Resource):
    def get(self):
        return "OK", 200


@admin_ns.route("/vector/semantic-concepts/rebuild")
class RebuildSemanticConceptVectors(Resource):
    @token_required
    def post(self):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            vertical_norm = str(body.get("vertical_norm") or "generic").strip().lower() or "generic"
            result = SemanticConceptEmbeddingService().rebuild_semantic_concept_index(vertical_norm=vertical_norm)
            return {"result": result, "vertical_norm": vertical_norm}, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            return {"error": "semantic concept vector rebuild failed"}, 500


@admin_ns.route("/vector/domains/reindex")
class ReindexDomainVectors(Resource):
    @token_required
    def post(self):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            if body.get("workspace_id") is not None or body.get("workspaceId") is not None:
                raise ServiceError(
                    "workspace_id must be provided via X-Workspace-Id header",
                    status_code=400,
                )
            workspace_id = get_workspace_id_from_header()
            vertical_norm = str(body.get("vertical_norm") or "").strip().lower() or None
            force = bool(body.get("force", False))
            json_fallback_path = str(body.get("json_fallback_path") or "").strip() or None
            result = DomainVectorIndexService().reindex_domains(
                workspace_id=workspace_id,
                vertical_norm=vertical_norm,
                force=force,
                json_fallback_path=json_fallback_path,
            )
            return {"result": result}, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception as exc:
            logger.exception("domain vector reindex failed")
            return {"error": "domain vector reindex failed", "details": str(exc)}, 500


def _require_admin() -> None:
    if not bool(getattr(g, "is_admin", False)):
        raise ServiceError("Admin access required", status_code=403)
