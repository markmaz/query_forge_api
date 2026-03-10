from __future__ import annotations

import logging

from flask import g, request
from flask_restx import Namespace, fields
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.models.domain_profile import (
    DomainProfileCreateRequest,
    DomainProfileUpdateRequest,
)
from app.models.domain_profile_embedding import (
    DomainProfileGenerateAllRequest,
    DomainProfileGenerateOneRequest,
    DomainProfileGenerateRequest,
)
from app.routes.request_helpers import extract_workspace_id
from app.services.admin.domain_profile_embedding_service import DomainProfileEmbeddingService
from app.services.admin.domain_profile_service import DomainProfileService
from app.services.admin.health_service import AdminHealthService
from app.services.embedding.embedding_index_service import EmbeddingIndexService
from app.services.embedding.semantic_concept_embedding_service import SemanticConceptEmbeddingService
from app.services.prompt_feedback_service import PromptFeedbackService
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

domain_profile_generate_batch_model = admin_ns.model(
    "DomainProfileGenerateBatchRequest",
    {
        "domain_ids": fields.List(fields.Integer, required=True),
        "force": fields.Boolean(required=False, default=False),
    },
)

domain_profile_generate_all_model = admin_ns.model(
    "DomainProfileGenerateAllRequest",
    {
        "force": fields.Boolean(required=False, default=False),
        "include_inactive": fields.Boolean(required=False, default=False),
    },
)

domain_profile_generate_one_model = admin_ns.model(
    "DomainProfileGenerateOneRequest",
    {
        "force": fields.Boolean(required=False, default=False),
    },
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@admin_ns.route("/healthz")
class ShowHealth(ForgeResource):
    def get(self):
        return "OK", 200


@admin_ns.route("/health/detailed")
class DetailedHealth(ForgeResource):
    @token_required
    def get(self):
        try:
            _require_admin()
            result = AdminHealthService().check_all()
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("detailed health check failed")
            return {"error": "health check failed"}, 500


# ---------------------------------------------------------------------------
# Pipeline profile (list recent)
# ---------------------------------------------------------------------------

@admin_ns.route("/pipeline-profiles")
class PipelineProfileList(ForgeResource):
    @token_required
    def get(self):
        try:
            _require_admin()
            from app.services.planner_domain import PlannerDomainService

            limit = request.args.get("limit", 50, type=int)
            result = PlannerDomainService().list_pipeline_profiles(limit=limit)
            return {"profiles": result, "count": len(result)}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("pipeline profile list failed")
            return {"error": "pipeline profile list failed"}, 500


# ---------------------------------------------------------------------------
# Prompt feedback admin (view/delete)
# ---------------------------------------------------------------------------

@admin_ns.route("/prompt-feedback")
class AdminPromptFeedbackList(ForgeResource):
    @token_required
    def get(self):
        try:
            _require_admin()
            workspace_id = extract_workspace_id()
            limit = request.args.get("limit", default=100, type=int) or 100
            offset = request.args.get("offset", default=0, type=int) or 0
            vote = str(request.args.get("vote") or "").strip() or None
            user_id = str(request.args.get("user_id") or "").strip() or None
            trace_id = str(request.args.get("trace_id") or "").strip() or None
            include_payload = str(request.args.get("include_payload") or "").strip().lower() in {
                "1",
                "true",
                "yes",
                "y",
                "on",
            }

            result = PromptFeedbackService().list_feedback(
                workspace_id=workspace_id,
                limit=limit,
                offset=offset,
                vote=vote,
                user_id=user_id,
                trace_id=trace_id,
                include_payload=include_payload,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("prompt feedback list failed")
            return {"error": "prompt feedback list failed"}, 500


@admin_ns.route("/prompt-feedback/<int:feedback_id>")
class AdminPromptFeedbackDelete(ForgeResource):
    @token_required
    def delete(self, feedback_id: int):
        try:
            _require_admin()
            workspace_id = extract_workspace_id()
            result = PromptFeedbackService().delete_feedback(
                workspace_id=workspace_id,
                feedback_id=feedback_id,
            )
            return {"id": result.id, "deleted": result.deleted}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("prompt feedback delete failed")
            return {"error": "prompt feedback delete failed"}, 500


# ---------------------------------------------------------------------------
# Vector index rebuild
# ---------------------------------------------------------------------------

@admin_ns.route("/vector/semantic-concepts/rebuild")
class RebuildSemanticConceptVectors(ForgeResource):
    @token_required
    def post(self):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            vertical_norm = str(body.get("vertical_norm") or "generic").strip().lower() or "generic"
            result = SemanticConceptEmbeddingService().rebuild_semantic_concept_index(vertical_norm=vertical_norm)
            return {"result": result, "vertical_norm": vertical_norm}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            return {"error": "semantic concept vector rebuild failed"}, 500


@admin_ns.route("/vector/domains/reindex")
class ReindexDomainVectors(ForgeResource):
    @token_required
    def post(self):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            if body.get("workspace_id") is not None or body.get("workspaceId") is not None:
                raise ForgeError(
                    "workspace_id must be provided via X-Workspace-Id header",
                    status_code=400,
                )
            workspace_id = extract_workspace_id()
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
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception as exc:
            logger.exception("domain vector reindex failed")
            return {"error": "domain vector reindex failed", "details": str(exc)}, 500


@admin_ns.route("/vector/embeddings/rebuild")
class RebuildEmbeddingVectors(ForgeResource):
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
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception as exc:
            logger.exception("embedding vector rebuild failed")
            return {"error": "embedding vector rebuild failed", "details": str(exc)}, 500


@admin_ns.route("/vector/rebuild-all")
class RebuildAllVectors(ForgeResource):
    @token_required
    def post(self):
        """Rebuild all vector indexes in the correct order."""
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            workspace_id = extract_workspace_id()
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
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception as exc:
            logger.exception("rebuild-all failed")
            return {"error": "rebuild-all failed", "details": str(exc)}, 500


# ---------------------------------------------------------------------------
# Domain profile CRUD
# ---------------------------------------------------------------------------

@admin_ns.route("/domain-profiles")
class DomainProfileList(ForgeResource):
    @token_required
    def get(self):
        try:
            _require_admin()
            workspace_id = extract_workspace_id()
            profiles = DomainProfileService().list_profiles(workspace_id)
            return {"profiles": profiles, "count": len(profiles)}, 200
        except ForgeError as exc:
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
            workspace_id = extract_workspace_id()
            body["workspace_id"] = workspace_id
            req = DomainProfileCreateRequest(**body)
            result = DomainProfileService().create_profile(req)
            return result, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile create failed")
            return {"error": "domain profile create failed"}, 500


@admin_ns.route("/domain-profiles/<int:domain_id>")
class DomainProfileDetail(ForgeResource):
    @token_required
    def get(self, domain_id: int):
        try:
            _require_admin()
            workspace_id = extract_workspace_id()
            result = DomainProfileService().get_profile(workspace_id, domain_id)
            return result, 200
        except ForgeError as exc:
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
            workspace_id = extract_workspace_id()
            req = DomainProfileUpdateRequest(**body)
            result = DomainProfileService().update_profile(workspace_id, domain_id, req)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile update failed")
            return {"error": "domain profile update failed"}, 500

    @token_required
    def delete(self, domain_id: int):
        try:
            _require_admin()
            workspace_id = extract_workspace_id()
            result = DomainProfileService().delete_profile(workspace_id, domain_id)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile delete failed")
            return {"error": "domain profile delete failed"}, 500


@admin_ns.route("/domain-profiles/<int:domain_id>/generate")
class DomainProfileGenerateOne(ForgeResource):
    @token_required
    @admin_ns.expect(domain_profile_generate_one_model, validate=False)
    def post(self, domain_id: int):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            req = DomainProfileGenerateOneRequest(**body)
            workspace_id = extract_workspace_id()
            result = DomainProfileEmbeddingService().generate_one(
                workspace_id=workspace_id,
                domain_id=domain_id,
                force=req.force,
            )
            return {"result": result}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile generate one failed")
            return {"error": "domain profile generate one failed"}, 500


@admin_ns.route("/domain-profiles/generate")
class DomainProfileGenerateBatch(ForgeResource):
    @token_required
    @admin_ns.expect(domain_profile_generate_batch_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            req = DomainProfileGenerateRequest(**body)
            workspace_id = extract_workspace_id()
            result = DomainProfileEmbeddingService().generate_many(
                workspace_id=workspace_id,
                domain_ids=req.domain_ids,
                force=req.force,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile generate batch failed")
            return {"error": "domain profile generate batch failed"}, 500


@admin_ns.route("/domain-profiles/generate-all")
class DomainProfileGenerateAll(ForgeResource):
    @token_required
    @admin_ns.expect(domain_profile_generate_all_model, validate=False)
    def post(self):
        try:
            _require_admin()
            body = request.get_json(silent=True) or {}
            req = DomainProfileGenerateAllRequest(**body)
            workspace_id = extract_workspace_id()
            result = DomainProfileEmbeddingService().generate_all(
                workspace_id=workspace_id,
                force=req.force,
                include_inactive=req.include_inactive,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile generate all failed")
            return {"error": "domain profile generate all failed"}, 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_admin() -> None:
    if not bool(getattr(g, "is_admin", False)):
        raise ForgeError("Admin access required", status_code=403)
