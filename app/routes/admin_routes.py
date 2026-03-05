from __future__ import annotations

import logging

from flask import g, request
from flask_restx import Namespace, Resource, fields

from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.models.domain_profile import (
    DomainProfileCreateRequest,
    DomainProfileUpdateRequest,
)
from app.routes._route_utils import get_workspace_id_from_header
from app.services.admin.domain_profile_service import DomainProfileService
from app.services.admin.health_service import AdminHealthService
from app.services.embedding.embedding_index_service import EmbeddingIndexService
from app.services.embedding.semantic_concept_embedding_service import SemanticConceptEmbeddingService
from app.services.vector import DomainVectorIndexService

admin_ns = Namespace("admin", description="Admin operations")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Swagger models
# ---------------------------------------------------------------------------

domain_profile_model = admin_ns.model(
    "DomainProfileRequest",
    {
        "workspace_id": fields.String(required=False),
        "domain_id": fields.Integer(required=False),
        "summary": fields.String(required=False),
        "keywords": fields.List(fields.String, required=False),
        "entities": fields.List(fields.String, required=False),
        "metrics": fields.List(fields.String, required=False),
        "attributes": fields.List(fields.String, required=False),
        "synonyms": fields.Raw(required=False),
        "acronyms": fields.Raw(required=False),
        "notes": fields.String(required=False),
        "embedding_text": fields.String(required=False),
    },
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@admin_ns.route("/healthz")
class ShowHealth(Resource):
    def get(self):
        return "OK", 200


@admin_ns.route("/health/detailed")
class DetailedHealth(Resource):
    @token_required
    def get(self):
        try:
            _require_admin()
            result = AdminHealthService().check_all()
            status_code = 200 if result["overall"] == "healthy" else 503
            return result, status_code
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("detailed health check failed")
            return {"error": "health check failed"}, 500


# ---------------------------------------------------------------------------
# Pipeline profile (list recent)
# ---------------------------------------------------------------------------

@admin_ns.route("/pipeline-profiles")
class PipelineProfileList(Resource):
    @token_required
    def get(self):
        try:
            _require_admin()
            from app.services.planner_domain import PlannerDomainService

            limit = request.args.get("limit", 50, type=int)
            result = PlannerDomainService().list_pipeline_profiles(limit=limit)
            return {"profiles": result, "count": len(result)}, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("pipeline profile list failed")
            return {"error": "pipeline profile list failed"}, 500


# ---------------------------------------------------------------------------
# Vector index rebuild
# ---------------------------------------------------------------------------

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


@admin_ns.route("/vector/embeddings/rebuild")
class RebuildEmbeddingVectors(Resource):
    @token_required
    def post(self):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            workspace_id = None
            if "workspace_id" in body or request.headers.get("X-Workspace-Id"):
                workspace_id = (
                    str(body.get("workspace_id") or "").strip()
                    or request.headers.get("X-Workspace-Id", "").strip()
                    or None
                )
            include_tables = bool(body.get("include_tables", True))
            limit = int(body.get("limit", 0))
            result = EmbeddingIndexService().rebuild_index(
                include_tables=include_tables,
                limit=limit,
                workspace_id=workspace_id,
            )
            return {"result": result}, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception as exc:
            logger.exception("embedding vector rebuild failed")
            return {"error": "embedding vector rebuild failed", "details": str(exc)}, 500


@admin_ns.route("/vector/rebuild-all")
class RebuildAllVectors(Resource):
    @token_required
    def post(self):
        """Rebuild all vector indexes in the correct order."""
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            workspace_id = get_workspace_id_from_header()
            vertical_norm = str(body.get("vertical_norm") or "generic").strip().lower() or "generic"
            force = bool(body.get("force", False))

            results = {}
            errors = {}

            # Step 1: Semantic concepts (no dependencies)
            try:
                results["semantic_concepts"] = (
                    SemanticConceptEmbeddingService().rebuild_semantic_concept_index(
                        vertical_norm=vertical_norm,
                    )
                )
            except Exception as exc:
                logger.exception("rebuild-all: semantic concepts failed")
                errors["semantic_concepts"] = str(exc)

            # Step 2: Table & column embeddings (no dependencies on step 1)
            try:
                results["embeddings"] = EmbeddingIndexService().rebuild_index(
                    include_tables=True,
                    workspace_id=workspace_id,
                )
            except Exception as exc:
                logger.exception("rebuild-all: embeddings failed")
                errors["embeddings"] = str(exc)

            # Step 3: Domain vectors (benefits from fresh domain_profile data)
            try:
                results["domain_vectors"] = DomainVectorIndexService().reindex_domains(
                    workspace_id=workspace_id,
                    vertical_norm=vertical_norm,
                    force=force,
                )
            except Exception as exc:
                logger.exception("rebuild-all: domain vectors failed")
                errors["domain_vectors"] = str(exc)

            overall = "completed" if not errors else "completed_with_errors"
            return {
                "status": overall,
                "results": results,
                "errors": errors,
                "workspace_id": workspace_id,
                "vertical_norm": vertical_norm,
            }, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception as exc:
            logger.exception("rebuild-all failed")
            return {"error": "rebuild-all failed", "details": str(exc)}, 500


# ---------------------------------------------------------------------------
# Domain profile CRUD
# ---------------------------------------------------------------------------

@admin_ns.route("/domain-profiles")
class DomainProfileList(Resource):
    @token_required
    def get(self):
        try:
            _require_admin()
            workspace_id = get_workspace_id_from_header()
            profiles = DomainProfileService().list_profiles(workspace_id)
            return {"profiles": profiles, "count": len(profiles)}, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile list failed")
            return {"error": "domain profile list failed"}, 500

    @token_required
    @admin_ns.expect(domain_profile_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            workspace_id = get_workspace_id_from_header()
            body["workspace_id"] = workspace_id
            req = DomainProfileCreateRequest(**body)
            result = DomainProfileService().create_profile(req)
            return result, 201
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile create failed")
            return {"error": "domain profile create failed"}, 500


@admin_ns.route("/domain-profiles/<int:domain_id>")
class DomainProfileDetail(Resource):
    @token_required
    def get(self, domain_id: int):
        try:
            _require_admin()
            workspace_id = get_workspace_id_from_header()
            result = DomainProfileService().get_profile(workspace_id, domain_id)
            return result, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile get failed")
            return {"error": "domain profile get failed"}, 500

    @token_required
    @admin_ns.expect(domain_profile_model, validate=False)
    def put(self, domain_id: int):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            workspace_id = get_workspace_id_from_header()
            req = DomainProfileUpdateRequest(**body)
            result = DomainProfileService().update_profile(workspace_id, domain_id, req)
            return result, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile update failed")
            return {"error": "domain profile update failed"}, 500

    @token_required
    def delete(self, domain_id: int):
        try:
            _require_admin()
            workspace_id = get_workspace_id_from_header()
            result = DomainProfileService().delete_profile(workspace_id, domain_id)
            return result, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile delete failed")
            return {"error": "domain profile delete failed"}, 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_admin() -> None:
    if not bool(getattr(g, "is_admin", False)):
        raise ServiceError("Admin access required", status_code=403)
