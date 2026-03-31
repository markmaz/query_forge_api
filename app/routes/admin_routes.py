from __future__ import annotations

import logging

from flask import g, request
from flask_restx import Namespace, fields
from pydantic import ValidationError
from flask_restx import Resource

from app.decorators.security import token_required
from app.decorators.rbac import public, require_admin, require_role
from app.exceptions.forge_error import ForgeError
from app.models.domain.domain_profile import (
    DomainProfileCreateRequest,
    DomainProfileUpdateRequest,
)
from app.models.domain.domain_profile_embedding import (
    DomainProfileGenerateAllRequest,
    DomainProfileGenerateOneRequest,
    DomainProfileGenerateRequest,
)
from app.models.semantic.semantic_catalog_admin import SemanticCatalogBuildRequest
from app.models.tenancy.tenancy_admin import (
    DatasourceCreateRequest,
    DatasourceUpdateRequest,
    OrganizationCreateRequest,
    OrganizationMembershipCreateRequest,
    OrganizationMembershipUpdateRequest,
    OrganizationUpdateRequest,
    TenancyBootstrapRequest,
    WorkspaceCreateRequest,
    WorkspaceBindingUpdateRequest,
    WorkspaceMembershipCreateRequest,
    WorkspaceMembershipUpdateRequest,
)
from app.routes.request_helpers import extract_workspace_id
from app.services.admin.domain_profile_embedding_service import DomainProfileEmbeddingService
from app.services.admin.domain_profile_service import DomainProfileService
from app.services.admin.health_service import AdminHealthService
from app.services.domain.planner_projection_policy_service import PlannerProjectionPolicyService
from app.services.embedding.embedding_index_service import EmbeddingIndexService
from app.services.embedding.semantic_concept_embedding_service import SemanticConceptEmbeddingService
from app.services.prompt_feedback_service import PromptFeedbackService
from app.services.semantic.catalog.semantic_catalog_builder import SemanticCatalogBuilder
from app.services.tenancy.tenancy_admin_service import TenancyAdminService
from app.services.tenancy.tenancy_bootstrap_service import BootstrapInput, TenancyBootstrapService
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
        "llm_id": fields.Integer(required=False, description="Optional workspace LLM id override"),
    },
)

domain_profile_generate_all_model = admin_ns.model(
    "DomainProfileGenerateAllRequest",
    {
        "force": fields.Boolean(required=False, default=False),
        "include_inactive": fields.Boolean(required=False, default=False),
        "llm_id": fields.Integer(required=False, description="Optional workspace LLM id override"),
    },
)

domain_profile_generate_one_model = admin_ns.model(
    "DomainProfileGenerateOneRequest",
    {
        "force": fields.Boolean(required=False, default=False),
        "llm_id": fields.Integer(required=False, description="Optional workspace LLM id override"),
    },
)

semantic_catalog_build_model = admin_ns.model(
    "SemanticCatalogBuildRequest",
    {
        "workspace_id": fields.String(required=False),
        "domain_id": fields.Integer(required=True),
        "vertical_norm": fields.String(required=False, default="generic"),
        "domain_name": fields.String(required=False),
        "dry_run": fields.Boolean(required=False, default=True),
        "table_limit": fields.Integer(required=False, default=5000),
        "llm_id": fields.Integer(required=False, description="Optional workspace LLM id override"),
    },
)

organization_create_model = admin_ns.model(
    "OrganizationCreateRequest",
    {
        "id": fields.String(required=False),
        "name": fields.String(required=True),
        "slug": fields.String(required=False),
        "description": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
    },
)

organization_update_model = admin_ns.model(
    "OrganizationUpdateRequest",
    {
        "name": fields.String(required=False),
        "slug": fields.String(required=False),
        "description": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
    },
)

organization_membership_create_model = admin_ns.model(
    "OrganizationMembershipCreateRequest",
    {
        "user_id": fields.String(required=True),
        "role": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
    },
)

organization_membership_update_model = admin_ns.model(
    "OrganizationMembershipUpdateRequest",
    {
        "role": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
    },
)

datasource_create_model = admin_ns.model(
    "DatasourceCreateRequest",
    {
        "name": fields.String(required=True),
        "slug": fields.String(required=False),
        "type": fields.String(required=True),
        "description": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
        "secret_ref": fields.String(required=False),
        "config_json": fields.Raw(required=False),
    },
)

datasource_update_model = admin_ns.model(
    "DatasourceUpdateRequest",
    {
        "name": fields.String(required=False),
        "slug": fields.String(required=False),
        "type": fields.String(required=False),
        "description": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
        "secret_ref": fields.String(required=False),
        "config_json": fields.Raw(required=False),
    },
)

workspace_membership_create_model = admin_ns.model(
    "WorkspaceMembershipCreateRequest",
    {
        "user_id": fields.String(required=True),
        "role": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
        "is_default": fields.Boolean(required=False),
    },
)

workspace_membership_update_model = admin_ns.model(
    "WorkspaceMembershipUpdateRequest",
    {
        "role": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
        "is_default": fields.Boolean(required=False),
    },
)

workspace_binding_update_model = admin_ns.model(
    "WorkspaceBindingUpdateRequest",
    {
        "organization_id": fields.String(required=False),
        "datasource_id": fields.Integer(required=False),
        "name": fields.String(required=False),
        "description": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
        "default_catalog": fields.String(required=False),
        "default_schema": fields.String(required=False),
    },
)

workspace_create_model = admin_ns.model(
    "WorkspaceCreateRequest",
    {
        "workspace_id": fields.String(required=False),
        "organization_id": fields.String(required=True),
        "datasource_id": fields.Integer(required=False),
        "name": fields.String(required=False),
        "description": fields.String(required=False),
        "is_active": fields.Boolean(required=False),
        "default_catalog": fields.String(required=False),
        "default_schema": fields.String(required=False),
    },
)

tenancy_bootstrap_model = admin_ns.model(
    "TenancyBootstrapRequest",
    {
        "workspace_id": fields.String(required=True),
        "organization_name": fields.String(required=True),
        "organization_id": fields.String(required=False),
        "organization_slug": fields.String(required=False),
        "organization_description": fields.String(required=False),
        "datasource_name": fields.String(required=True),
        "datasource_type": fields.String(required=True, enum=["databricks", "snowflake", "mysql", "postgres", "bigquery"]),
        "datasource_slug": fields.String(required=False),
        "datasource_description": fields.String(required=False),
        "datasource_secret_ref": fields.String(required=False),
        "datasource_config_json": fields.Raw(required=False),
        "default_catalog": fields.String(required=False),
        "default_schema": fields.String(required=False),
        "admin_user_id": fields.String(required=False),
    },
)

planner_projection_policy_model = admin_ns.model(
    "PlannerProjectionPolicyRequest",
    {
        "id": fields.Integer(required=False),
        "policy_key": fields.String(required=True),
        "name": fields.String(required=True),
        "description": fields.String(required=False),
        "scope_type": fields.String(required=True),
        "scope_workspace_id": fields.String(required=False),
        "scope_vertical_norm": fields.String(required=False),
        "scope_base_domain_id": fields.Integer(required=False),
        "priority": fields.Integer(required=False, default=100),
        "is_active": fields.Boolean(required=False, default=True),
        "stop_on_match": fields.Boolean(required=False, default=False),
        "policy_json": fields.Raw(required=True),
    },
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@admin_ns.route("/healthz")
class ShowHealth(Resource):
    @public
    def get(self):
        return "OK", 200


@admin_ns.route("/health/detailed")
class DetailedHealth(Resource):
    @token_required
    @require_admin()
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


@admin_ns.route("/health/broker")
class BrokerHealth(Resource):
    @token_required
    @require_role("system:admin")
    def get(self):
        try:
            _require_admin()
            result = AdminHealthService().check_broker()
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("broker health check failed")
            return {"error": "broker health check failed"}, 500


# ---------------------------------------------------------------------------
# Pipeline profile (list recent)
# ---------------------------------------------------------------------------

@admin_ns.route("/pipeline-profiles")
class PipelineProfileList(Resource):
    @token_required
    @require_admin()
    def get(self):
        try:
            from app.services.planner_domain import PlannerDomainService

            limit = request.args.get("limit", 50, type=int)
            result = PlannerDomainService().list_pipeline_profiles(limit=limit)
            return {"profiles": result, "count": len(result)}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("pipeline profile list failed")
            return {"error": "pipeline profile list failed"}, 500


@admin_ns.route("/pipeline-profiles/<string:trace_id>")
class PipelineProfileDetail(Resource):
    @token_required
    @require_admin()
    def get(self, trace_id: str):
        try:
            from app.services.planner_domain import PlannerDomainService

            workspace_id = extract_workspace_id()
            user_id = str(getattr(g, "user_id", "") or "")
            result = PlannerDomainService().get_pipeline_profile(
                trace_id=trace_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("pipeline profile detail failed")
            return {"error": "pipeline profile detail failed"}, 500


# ---------------------------------------------------------------------------
# Prompt feedback admin (view/delete)
# ---------------------------------------------------------------------------

@admin_ns.route("/prompt-feedback")
class AdminPromptFeedbackList(Resource):
    @token_required
    @require_admin()
    def get(self):
        try:
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
class AdminPromptFeedbackDelete(Resource):
    @token_required
    @require_admin()
    def delete(self, feedback_id: int):
        try:
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
# Planner projection policies
# ---------------------------------------------------------------------------

@admin_ns.route("/planner-projection-policies")
class AdminPlannerProjectionPolicies(Resource):
    @token_required
    @require_admin()
    def get(self):
        try:
            workspace_id = extract_workspace_id()
            base_domain_id_raw = request.args.get("base_domain_id")
            base_domain_id = int(base_domain_id_raw) if (base_domain_id_raw or "").strip() else None
            vertical_norm = (request.args.get("vertical_norm") or "generic").strip().lower() or "generic"
            include_inactive = str(request.args.get("include_inactive") or "").strip().lower() in {
                "1",
                "true",
                "yes",
                "y",
                "on",
            }
            include_seeded = str(request.args.get("include_seeded") or "true").strip().lower() in {
                "1",
                "true",
                "yes",
                "y",
                "on",
            }
            result = PlannerProjectionPolicyService().list_policies(
                workspace_id=workspace_id,
                base_domain_id=base_domain_id,
                vertical_norm=vertical_norm,
                include_inactive=include_inactive,
                include_seeded=include_seeded,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("planner projection policy list failed")
            return {"error": "planner projection policy list failed"}, 500

    @token_required
    @require_admin()
    @admin_ns.expect(planner_projection_policy_model, validate=False)
    def put(self):
        try:
            workspace_id = extract_workspace_id()
            result = PlannerProjectionPolicyService().upsert_policy(
                workspace_id=workspace_id,
                actor_user_id=str(getattr(g, "user_id", "") or ""),
                payload=request.get_json(silent=True) or {},
            )
            return result, 200
        except ValidationError as exc:
            return {"error": "Invalid planner projection policy request", "details": {"errors": exc.errors()}}, 400
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("planner projection policy upsert failed")
            return {"error": "planner projection policy upsert failed"}, 500


@admin_ns.route("/planner-projection-policies/<int:policy_id>")
class AdminPlannerProjectionPolicyDetail(Resource):
    @token_required
    @require_admin()
    def delete(self, policy_id: int):
        try:
            workspace_id = extract_workspace_id()
            result = PlannerProjectionPolicyService().delete_policy(
                workspace_id=workspace_id,
                actor_user_id=str(getattr(g, "user_id", "") or ""),
                policy_id=policy_id,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("planner projection policy delete failed")
            return {"error": "planner projection policy delete failed"}, 500


# ---------------------------------------------------------------------------
# Vector index rebuild
# ---------------------------------------------------------------------------

@admin_ns.route("/vector/semantic-concepts/rebuild")
class RebuildSemanticConceptVectors(Resource):
    @token_required
    @require_admin()
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
class ReindexDomainVectors(Resource):
    @token_required
    @require_admin()
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
class RebuildEmbeddingVectors(Resource):
    @token_required
    @require_admin()
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
class RebuildAllVectors(Resource):
    @token_required
    @require_role("system:admin")
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
class DomainProfileList(Resource):
    @token_required
    @require_admin()
    def get(self):
        try:
            workspace_id = extract_workspace_id()
            profiles = DomainProfileService().list_profiles(workspace_id)
            return {"profiles": profiles, "count": len(profiles)}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile list failed")
            return {"error": "domain profile list failed"}, 500

    @token_required
    @require_admin()
    @admin_ns.expect(domain_profile_model, validate=False)
    def post(self):
        try:
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
class DomainProfileDetail(Resource):
    @token_required
    @require_admin()
    def get(self, domain_id: int):
        try:
            workspace_id = extract_workspace_id()
            result = DomainProfileService().get_profile(workspace_id, domain_id)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile get failed")
            return {"error": "domain profile get failed"}, 500

    @token_required
    @require_admin()
    @admin_ns.expect(domain_profile_model, validate=False)
    def put(self, domain_id: int):
        try:
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
    @require_admin()
    def delete(self, domain_id: int):
        try:
            workspace_id = extract_workspace_id()
            result = DomainProfileService().delete_profile(workspace_id, domain_id)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile delete failed")
            return {"error": "domain profile delete failed"}, 500


@admin_ns.route("/domain-profiles/<int:domain_id>/generate")
class DomainProfileGenerateOne(Resource):
    @token_required
    @require_admin()
    @admin_ns.expect(domain_profile_generate_one_model, validate=False)
    def post(self, domain_id: int):
        try:
            body = request.get_json(silent=True) or {}
            req = DomainProfileGenerateOneRequest(**body)
            workspace_id = extract_workspace_id()
            args = {
                "workspace_id": workspace_id,
                "domain_id": domain_id,
                "force": req.force,
            }
            if req.llm_id is not None:
                args["llm_id"] = req.llm_id
            result = DomainProfileEmbeddingService().generate_one(**args)
            return {"result": result}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile generate one failed")
            return {"error": "domain profile generate one failed"}, 500


@admin_ns.route("/domain-profiles/generate")
class DomainProfileGenerateBatch(Resource):
    @token_required
    @require_admin()
    @admin_ns.expect(domain_profile_generate_batch_model, validate=False)
    def post(self):
        try:
            body = request.get_json(silent=True) or {}
            req = DomainProfileGenerateRequest(**body)
            workspace_id = extract_workspace_id()
            args = {
                "workspace_id": workspace_id,
                "domain_ids": req.domain_ids,
                "force": req.force,
            }
            if req.llm_id is not None:
                args["llm_id"] = req.llm_id
            result = DomainProfileEmbeddingService().generate_many(**args)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile generate batch failed")
            return {"error": "domain profile generate batch failed"}, 500


@admin_ns.route("/domain-profiles/generate-all")
class DomainProfileGenerateAll(Resource):
    @token_required
    @require_admin()
    @admin_ns.expect(domain_profile_generate_all_model, validate=False)
    def post(self):
        try:
            body = request.get_json(silent=True) or {}
            req = DomainProfileGenerateAllRequest(**body)
            workspace_id = extract_workspace_id()
            args = {
                "workspace_id": workspace_id,
                "force": req.force,
                "include_inactive": req.include_inactive,
            }
            if req.llm_id is not None:
                args["llm_id"] = req.llm_id
            result = DomainProfileEmbeddingService().generate_all(**args)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("domain profile generate all failed")
            return {"error": "domain profile generate all failed"}, 500


# ---------------------------------------------------------------------------
# Semantic catalog build
# ---------------------------------------------------------------------------

@admin_ns.route("/semantic-catalog/build")
class SemanticCatalogBuild(Resource):
    @token_required
    @require_admin()
    @admin_ns.expect(semantic_catalog_build_model, validate=False)
    def post(self):
        try:
            _require_admin()
            req = SemanticCatalogBuildRequest(**(request.get_json(silent=True) or {}))
            header_workspace_id = extract_workspace_id()
            if req.workspace_id and req.workspace_id != header_workspace_id:
                raise ForgeError(
                    "workspace_id in body must match X-Workspace-Id header",
                    status_code=400,
                )
            workspace_id = req.workspace_id or header_workspace_id
            result = SemanticCatalogBuilder().build_catalog(
                workspace_id=workspace_id,
                domain_id=req.domain_id,
                vertical_norm=req.vertical_norm,
                domain_name=req.domain_name,
                dry_run=req.dry_run,
                table_limit=req.table_limit,
                llm_id=req.llm_id,
            )
            payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
            return {"result": payload}, 200
        except ValidationError as exc:
            return {
                "error": "Invalid semantic catalog build request",
                "details": {"errors": exc.errors()},
            }, 400
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic catalog build failed")
            return {"error": "semantic catalog build failed"}, 500


# ---------------------------------------------------------------------------
# Tenancy admin CRUD (organization / membership / datasource / workspace membership)
# ---------------------------------------------------------------------------

@admin_ns.route("/tenancy/bootstrap")
class TenancyBootstrap(Resource):
    @token_required
    @require_role("system:admin")
    @admin_ns.expect(tenancy_bootstrap_model, validate=False)
    def post(self):
        try:
            _require_admin()
            req = TenancyBootstrapRequest(**(request.get_json(silent=True) or {}))
            result = TenancyBootstrapService().bootstrap(
                BootstrapInput(
                    workspace_id=req.workspace_id,
                    organization_name=req.organization_name,
                    organization_id=req.organization_id,
                    organization_slug=req.organization_slug,
                    organization_description=req.organization_description,
                    datasource_name=req.datasource_name,
                    datasource_type=req.datasource_type,
                    datasource_slug=req.datasource_slug,
                    datasource_description=req.datasource_description,
                    datasource_secret_ref=req.datasource_secret_ref,
                    datasource_config_json=req.datasource_config_json,
                    default_catalog=req.default_catalog,
                    default_schema=req.default_schema,
                    admin_user_id=req.admin_user_id,
                )
            )
            return {"result": result}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("tenancy bootstrap failed")
            return {"error": "tenancy bootstrap failed"}, 500


@admin_ns.route("/organizations")
class OrganizationListCreate(Resource):
    @token_required
    @require_admin()
    def get(self):
        try:
            _require_admin()
            include_inactive = _as_bool(request.args.get("include_inactive"), default=False)
            q = str(request.args.get("q") or "").strip() or None
            limit = request.args.get("limit", default=100, type=int) or 100
            offset = request.args.get("offset", default=0, type=int) or 0
            service = TenancyAdminService()
            if _is_super_admin_request():
                return service.list_organizations(
                    include_inactive=include_inactive,
                    q=q,
                    limit=limit,
                    offset=offset,
                ), 200

            scoped_binding = _current_workspace_binding(service)
            organization_id = str(scoped_binding.get("organization_id") or "").strip()
            if not organization_id:
                return _paged_rows([], limit=limit, offset=offset), 200

            organization = service.get_organization(organization_id)
            rows = [organization] if _matches_scoped_organization_row(organization, include_inactive=include_inactive, q=q) else []
            return _paged_rows(rows, limit=limit, offset=offset), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("organization list failed")
            return {"error": "organization list failed"}, 500

    @token_required
    @require_role("system:admin")
    @admin_ns.expect(organization_create_model, validate=False)
    def post(self):
        try:
            _require_admin()
            req = OrganizationCreateRequest(**(request.get_json(silent=True) or {}))
            result = TenancyAdminService().create_organization(req)
            return result, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("organization create failed")
            return {"error": "organization create failed"}, 500


@admin_ns.route("/organizations/<string:organization_id>")
class OrganizationDetail(Resource):
    @token_required
    @require_role("system:admin")
    def get(self, organization_id: str):
        try:
            _require_admin()
            return TenancyAdminService().get_organization(organization_id), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("organization get failed")
            return {"error": "organization get failed"}, 500

    @token_required
    @require_role("system:admin")
    @admin_ns.expect(organization_update_model, validate=False)
    def patch(self, organization_id: str):
        try:
            _require_admin()
            req = OrganizationUpdateRequest(**(request.get_json(silent=True) or {}))
            result = TenancyAdminService().update_organization(organization_id, req)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("organization update failed")
            return {"error": "organization update failed"}, 500

    @token_required
    @require_role("system:admin")
    def delete(self, organization_id: str):
        try:
            _require_admin()
            hard = _as_bool(request.args.get("hard"), default=False)
            result = TenancyAdminService().delete_organization(organization_id, hard=hard)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("organization delete failed")
            return {"error": "organization delete failed"}, 500


@admin_ns.route("/organizations/<string:organization_id>/memberships")
class OrganizationMembershipListCreate(Resource):
    @token_required
    @require_role("system:admin")
    def get(self, organization_id: str):
        try:
            _require_admin()
            include_inactive = _as_bool(request.args.get("include_inactive"), default=False)
            limit = request.args.get("limit", default=200, type=int) or 200
            offset = request.args.get("offset", default=0, type=int) or 0
            result = TenancyAdminService().list_organization_memberships(
                organization_id=organization_id,
                include_inactive=include_inactive,
                limit=limit,
                offset=offset,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("organization membership list failed")
            return {"error": "organization membership list failed"}, 500

    @token_required
    @require_role("system:admin")
    @admin_ns.expect(organization_membership_create_model, validate=False)
    def post(self, organization_id: str):
        try:
            _require_admin()
            req = OrganizationMembershipCreateRequest(**(request.get_json(silent=True) or {}))
            result = TenancyAdminService().upsert_organization_membership(
                organization_id=organization_id,
                req=req,
            )
            return result, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("organization membership create failed")
            return {"error": "organization membership create failed"}, 500


@admin_ns.route("/organizations/<string:organization_id>/memberships/<int:membership_id>")
class OrganizationMembershipDetail(Resource):
    @token_required
    @require_role("system:admin")
    @admin_ns.expect(organization_membership_update_model, validate=False)
    def patch(self, organization_id: str, membership_id: int):
        try:
            _require_admin()
            req = OrganizationMembershipUpdateRequest(**(request.get_json(silent=True) or {}))
            result = TenancyAdminService().update_organization_membership(
                organization_id=organization_id,
                membership_id=membership_id,
                req=req,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("organization membership update failed")
            return {"error": "organization membership update failed"}, 500

    @token_required
    @require_role("system:admin")
    def delete(self, organization_id: str, membership_id: int):
        try:
            _require_admin()
            result = TenancyAdminService().delete_organization_membership(
                organization_id=organization_id,
                membership_id=membership_id,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("organization membership delete failed")
            return {"error": "organization membership delete failed"}, 500


@admin_ns.route("/organizations/<string:organization_id>/datasources")
class OrganizationDatasourceListCreate(Resource):
    @token_required
    @require_admin()
    def get(self, organization_id: str):
        try:
            _require_admin()
            service = TenancyAdminService()
            _assert_workspace_admin_organization_access(service, organization_id)
            include_inactive = _as_bool(request.args.get("include_inactive"), default=False)
            limit = request.args.get("limit", default=100, type=int) or 100
            offset = request.args.get("offset", default=0, type=int) or 0
            result = service.list_datasources(
                organization_id=organization_id,
                include_inactive=include_inactive,
                limit=limit,
                offset=offset,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("organization datasource list failed")
            return {"error": "organization datasource list failed"}, 500

    @token_required
    @require_admin()
    @admin_ns.expect(datasource_create_model, validate=False)
    def post(self, organization_id: str):
        try:
            _require_admin()
            service = TenancyAdminService()
            _assert_workspace_admin_organization_access(service, organization_id)
            req = DatasourceCreateRequest(**(request.get_json(silent=True) or {}))
            result = service.create_datasource(organization_id=organization_id, req=req)
            return result, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("organization datasource create failed")
            return {"error": "organization datasource create failed"}, 500


@admin_ns.route("/datasources/<int:datasource_id>")
class DatasourceDetail(Resource):
    @token_required
    @require_admin()
    def get(self, datasource_id: int):
        try:
            _require_admin()
            service = TenancyAdminService()
            row = _assert_workspace_admin_datasource_access(service, datasource_id)
            return row, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("datasource get failed")
            return {"error": "datasource get failed"}, 500

    @token_required
    @require_admin()
    @admin_ns.expect(datasource_update_model, validate=False)
    def patch(self, datasource_id: int):
        try:
            _require_admin()
            service = TenancyAdminService()
            _assert_workspace_admin_datasource_access(service, datasource_id)
            req = DatasourceUpdateRequest(**(request.get_json(silent=True) or {}))
            result = service.update_datasource(datasource_id=datasource_id, req=req)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("datasource update failed")
            return {"error": "datasource update failed"}, 500

    @token_required
    @require_admin()
    def delete(self, datasource_id: int):
        try:
            _require_admin()
            service = TenancyAdminService()
            _assert_workspace_admin_datasource_access(service, datasource_id)
            hard = _as_bool(request.args.get("hard"), default=False)
            result = service.delete_datasource(datasource_id=datasource_id, hard=hard)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("datasource delete failed")
            return {"error": "datasource delete failed"}, 500


@admin_ns.route("/datasources/<int:datasource_id>/test")
class DatasourceConnectionTest(Resource):
    @token_required
    @require_admin()
    def post(self, datasource_id: int):
        try:
            _require_admin()
            service = TenancyAdminService()
            _assert_workspace_admin_datasource_access(service, datasource_id)
            result = service.test_datasource(datasource_id=datasource_id)
            return {"result": result}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("datasource test failed")
            return {"error": "datasource test failed"}, 500


@admin_ns.route("/datasources/<int:datasource_id>/namespaces")
class DatasourceNamespaces(Resource):
    @token_required
    @require_admin()
    def get(self, datasource_id: int):
        try:
            _require_admin()
            service = TenancyAdminService()
            _assert_workspace_admin_datasource_access(service, datasource_id)
            result = service.list_datasource_namespaces(
                datasource_id=datasource_id,
                catalog=(request.args.get("catalog") or "").strip() or None,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("datasource namespaces failed")
            return {"error": "datasource namespaces failed"}, 500


@admin_ns.route("/workspaces")
class WorkspaceBindingList(Resource):
    @token_required
    @require_admin()
    def get(self):
        try:
            _require_admin()
            include_inactive = _as_bool(request.args.get("include_inactive"), default=False)
            organization_id = str(request.args.get("organization_id") or "").strip() or None
            limit = request.args.get("limit", default=200, type=int) or 200
            offset = request.args.get("offset", default=0, type=int) or 0
            service = TenancyAdminService()
            if _is_super_admin_request():
                result = service.list_workspace_bindings(
                    organization_id=organization_id,
                    include_inactive=include_inactive,
                    limit=limit,
                    offset=offset,
                )
                return result, 200

            scoped_binding = _current_workspace_binding(service)
            rows = [
                scoped_binding,
            ] if _matches_scoped_workspace_row(
                scoped_binding,
                include_inactive=include_inactive,
                organization_id=organization_id,
            ) else []
            result = _paged_rows(rows, limit=limit, offset=offset)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("workspace binding list failed")
            return {"error": "workspace binding list failed"}, 500

    @token_required
    @require_role("system:admin")
    @admin_ns.expect(workspace_create_model, validate=False)
    def post(self):
        try:
            _require_admin()
            req = WorkspaceCreateRequest(**(request.get_json(silent=True) or {}))
            result = TenancyAdminService().create_workspace(req)
            return result, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("workspace create failed")
            return {"error": "workspace create failed"}, 500


@admin_ns.route("/workspaces/<string:workspace_id>/binding")
class WorkspaceBindingDetail(Resource):
    @token_required
    @require_role("system:admin")
    def get(self, workspace_id: str):
        try:
            _require_admin()
            return TenancyAdminService().get_workspace_binding(workspace_id), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("workspace binding get failed")
            return {"error": "workspace binding get failed"}, 500

    @token_required
    @require_role("system:admin")
    @admin_ns.expect(workspace_binding_update_model, validate=False)
    def patch(self, workspace_id: str):
        try:
            _require_admin()
            req = WorkspaceBindingUpdateRequest(**(request.get_json(silent=True) or {}))
            result = TenancyAdminService().update_workspace_binding(workspace_id=workspace_id, req=req)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("workspace binding update failed")
            return {"error": "workspace binding update failed"}, 500


@admin_ns.route("/workspaces/<string:workspace_id>")
class WorkspaceDetail(Resource):
    @token_required
    @require_role("system:admin")
    def delete(self, workspace_id: str):
        try:
            _require_admin()
            hard = _as_bool(request.args.get("hard"), default=False)
            result = TenancyAdminService().delete_workspace(workspace_id=workspace_id, hard=hard)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("workspace delete failed")
            return {"error": "workspace delete failed"}, 500


@admin_ns.route("/workspaces/<string:workspace_id>/memberships")
class WorkspaceMembershipListCreate(Resource):
    @token_required
    @require_role("system:admin")
    def get(self, workspace_id: str):
        try:
            _require_admin()
            include_inactive = _as_bool(request.args.get("include_inactive"), default=False)
            limit = request.args.get("limit", default=200, type=int) or 200
            offset = request.args.get("offset", default=0, type=int) or 0
            result = TenancyAdminService().list_workspace_memberships(
                workspace_id=workspace_id,
                include_inactive=include_inactive,
                limit=limit,
                offset=offset,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("workspace membership list failed")
            return {"error": "workspace membership list failed"}, 500

    @token_required
    @require_role("system:admin")
    @admin_ns.expect(workspace_membership_create_model, validate=False)
    def post(self, workspace_id: str):
        try:
            _require_admin()
            req = WorkspaceMembershipCreateRequest(**(request.get_json(silent=True) or {}))
            result = TenancyAdminService().upsert_workspace_membership(workspace_id=workspace_id, req=req)
            return result, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("workspace membership create failed")
            return {"error": "workspace membership create failed"}, 500


@admin_ns.route("/workspaces/<string:workspace_id>/memberships/<int:membership_id>")
class WorkspaceMembershipDetail(Resource):
    @token_required
    @require_role("system:admin")
    @admin_ns.expect(workspace_membership_update_model, validate=False)
    def patch(self, workspace_id: str, membership_id: int):
        try:
            _require_admin()
            req = WorkspaceMembershipUpdateRequest(**(request.get_json(silent=True) or {}))
            result = TenancyAdminService().update_workspace_membership(
                workspace_id=workspace_id,
                membership_id=membership_id,
                req=req,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("workspace membership update failed")
            return {"error": "workspace membership update failed"}, 500

    @token_required
    @require_role("system:admin")
    def delete(self, workspace_id: str, membership_id: int):
        try:
            _require_admin()
            result = TenancyAdminService().delete_workspace_membership(
                workspace_id=workspace_id,
                membership_id=membership_id,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("workspace membership delete failed")
            return {"error": "workspace membership delete failed"}, 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_admin() -> None:
    effective_roles = getattr(g, "effective_roles", set()) or set()
    if bool(getattr(g, "is_admin", False)) or "super_admin" in effective_roles or "workspace_admin" in effective_roles:
        return
    raise ForgeError("Admin access required", status_code=403)


def _is_super_admin_request() -> bool:
    effective_roles = getattr(g, "effective_roles", set()) or set()
    return "super_admin" in effective_roles


def _current_workspace_binding(service: TenancyAdminService) -> dict:
    workspace_id = str(getattr(g, "workspace_id", "") or "").strip()
    if not workspace_id:
        raise ForgeError("X-Workspace-Id header is required for workspace-scoped admin access", status_code=400)
    return service.get_workspace_binding(workspace_id)


def _assert_workspace_admin_organization_access(service: TenancyAdminService, organization_id: str) -> None:
    if _is_super_admin_request():
        return
    scoped_binding = _current_workspace_binding(service)
    scoped_org_id = str(scoped_binding.get("organization_id") or "").strip()
    requested_org_id = str(organization_id or "").strip()
    if not scoped_org_id or requested_org_id != scoped_org_id:
        raise ForgeError("Workspace admin access is limited to the current workspace organization", status_code=403)


def _assert_workspace_admin_datasource_access(service: TenancyAdminService, datasource_id: int) -> dict:
    if _is_super_admin_request():
        return {}
    row = service.get_datasource(int(datasource_id))
    _assert_workspace_admin_organization_access(service, str(row.get("organization_id") or ""))
    return row


def _paged_rows(rows: list[dict], *, limit: int, offset: int) -> dict:
    page_limit = max(1, int(limit or 1))
    page_offset = max(0, int(offset or 0))
    paged = rows[page_offset: page_offset + page_limit]
    return {
        "rows": paged,
        "count": len(paged),
        "total": len(rows),
        "limit": page_limit,
        "offset": page_offset,
    }


def _matches_scoped_organization_row(row: dict, *, include_inactive: bool, q: str | None) -> bool:
    if not include_inactive and not bool(row.get("is_active", True)):
        return False
    if not q:
        return True
    query = str(q or "").strip().lower()
    name = str(row.get("name") or "").strip().lower()
    slug = str(row.get("slug") or "").strip().lower()
    return query in name or query in slug


def _matches_scoped_workspace_row(
    row: dict,
    *,
    include_inactive: bool,
    organization_id: str | None,
) -> bool:
    if not include_inactive and not bool(row.get("workspace_is_active", True)):
        return False
    if organization_id and str(row.get("organization_id") or "").strip() != str(organization_id).strip():
        return False
    return True


def _as_bool(value, *, default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default
