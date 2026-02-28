from __future__ import annotations

from flask import g, request
from flask_restx import Namespace, Resource

from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.services.embedding.semantic_concept_embedding_service import SemanticConceptEmbeddingService

admin_ns = Namespace("admin", description="Admin operations")

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


def _require_admin() -> None:
    if not bool(getattr(g, "is_admin", False)):
        raise ServiceError("Admin access required", status_code=403)
