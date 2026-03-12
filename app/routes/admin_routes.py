from __future__ import annotations

import logging

from flask import g, request
from flask_restx import Namespace, fields
from pydantic import ValidationError
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
from app.models.semantic_catalog_admin import SemanticCatalogBuildRequest
from app.models.tenancy_admin import (
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

semantic_catalog_build_model = admin_ns.model(
    "SemanticCatalogBuildRequest",
    {
        "workspace_id": fields.String(required=False),
        "domain_id": fields.Integer(required=True),
        "vertical_norm": fields.String(required=False, default="generic"),
        "domain_name": fields.String(required=False),
        "dry_run": fields.Boolean(required=False, default=True),
        "table_limit": fields.Integer(required=False, default=5000),
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
# Semantic catalog build
# ---------------------------------------------------------------------------

@admin_ns.route("/semantic-catalog/build")
class SemanticCatalogBuild(ForgeResource):
    @token_required
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
class TenancyBootstrap(ForgeResource):
    @token_required
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
class OrganizationListCreate(ForgeResource):
    @token_required
    def get(self):
        try:
            _require_admin()
            include_inactive = _as_bool(request.args.get("include_inactive"), default=False)
            q = str(request.args.get("q") or "").strip() or None
            limit = request.args.get("limit", default=100, type=int) or 100
            offset = request.args.get("offset", default=0, type=int) or 0
            return TenancyAdminService().list_organizations(
                include_inactive=include_inactive,
                q=q,
                limit=limit,
                offset=offset,
            ), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("organization list failed")
            return {"error": "organization list failed"}, 500

    @token_required
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
class OrganizationDetail(ForgeResource):
    @token_required
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
class OrganizationMembershipListCreate(ForgeResource):
    @token_required
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
class OrganizationMembershipDetail(ForgeResource):
    @token_required
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
class OrganizationDatasourceListCreate(ForgeResource):
    @token_required
    def get(self, organization_id: str):
        try:
            _require_admin()
            include_inactive = _as_bool(request.args.get("include_inactive"), default=False)
            limit = request.args.get("limit", default=100, type=int) or 100
            offset = request.args.get("offset", default=0, type=int) or 0
            result = TenancyAdminService().list_datasources(
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
    @admin_ns.expect(datasource_create_model, validate=False)
    def post(self, organization_id: str):
        try:
            _require_admin()
            req = DatasourceCreateRequest(**(request.get_json(silent=True) or {}))
            result = TenancyAdminService().create_datasource(organization_id=organization_id, req=req)
            return result, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("organization datasource create failed")
            return {"error": "organization datasource create failed"}, 500


@admin_ns.route("/datasources/<int:datasource_id>")
class DatasourceDetail(ForgeResource):
    @token_required
    def get(self, datasource_id: int):
        try:
            _require_admin()
            return TenancyAdminService().get_datasource(datasource_id), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("datasource get failed")
            return {"error": "datasource get failed"}, 500

    @token_required
    @admin_ns.expect(datasource_update_model, validate=False)
    def patch(self, datasource_id: int):
        try:
            _require_admin()
            req = DatasourceUpdateRequest(**(request.get_json(silent=True) or {}))
            result = TenancyAdminService().update_datasource(datasource_id=datasource_id, req=req)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("datasource update failed")
            return {"error": "datasource update failed"}, 500

    @token_required
    def delete(self, datasource_id: int):
        try:
            _require_admin()
            hard = _as_bool(request.args.get("hard"), default=False)
            result = TenancyAdminService().delete_datasource(datasource_id=datasource_id, hard=hard)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("datasource delete failed")
            return {"error": "datasource delete failed"}, 500


@admin_ns.route("/datasources/<int:datasource_id>/test")
class DatasourceConnectionTest(ForgeResource):
    @token_required
    def post(self, datasource_id: int):
        try:
            _require_admin()
            result = TenancyAdminService().test_datasource(datasource_id=datasource_id)
            return {"result": result}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("datasource test failed")
            return {"error": "datasource test failed"}, 500


@admin_ns.route("/workspaces")
class WorkspaceBindingList(ForgeResource):
    @token_required
    def get(self):
        try:
            _require_admin()
            include_inactive = _as_bool(request.args.get("include_inactive"), default=False)
            organization_id = str(request.args.get("organization_id") or "").strip() or None
            limit = request.args.get("limit", default=200, type=int) or 200
            offset = request.args.get("offset", default=0, type=int) or 0
            result = TenancyAdminService().list_workspace_bindings(
                organization_id=organization_id,
                include_inactive=include_inactive,
                limit=limit,
                offset=offset,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("workspace binding list failed")
            return {"error": "workspace binding list failed"}, 500

    @token_required
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
class WorkspaceBindingDetail(ForgeResource):
    @token_required
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


@admin_ns.route("/workspaces/<string:workspace_id>/memberships")
class WorkspaceMembershipListCreate(ForgeResource):
    @token_required
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
class WorkspaceMembershipDetail(ForgeResource):
    @token_required
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
    if not bool(getattr(g, "is_admin", False)):
        raise ForgeError("Admin access required", status_code=403)


def _as_bool(value, *, default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default
