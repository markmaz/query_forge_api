from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_admin, require_role
from app.decorators.security import token_required
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
from app.routes.request_helpers import extract_workspace_id

from .base import admin_ns, logger
from .deps import (
    domain_profile_embedding_service,
    domain_profile_service,
    domain_vector_index_service,
    embedding_index_service,
    semantic_catalog_builder,
    semantic_concept_embedding_service,
)
from .helpers import _require_admin
from .models import (
    domain_profile_generate_all_model,
    domain_profile_generate_batch_model,
    domain_profile_generate_one_model,
    domain_profile_model,
    semantic_catalog_build_model,
)


@admin_ns.route("/vector/semantic-concepts/rebuild")
class RebuildSemanticConceptVectors(Resource):
    @token_required
    @require_admin()
    def post(self):
        _require_admin()
        result = semantic_concept_embedding_service().rebuild_semantic_concept_index()
        return {"result": result}, 200


@admin_ns.route("/vector/domains/reindex")
class ReindexDomainVectors(Resource):
    @token_required
    @require_admin()
    def post(self):
        _require_admin()
        body = request.get_json(silent=True) or {}
        if (
            body.get("workspace_id") is not None
            or body.get("workspaceId") is not None
        ):
            raise ForgeError(
                "workspace_id must be provided via X-Workspace-Id header",
                status_code=400,
        )
        workspace_id = extract_workspace_id()
        force = bool(body.get("force", False))
        json_fallback_path = str(body.get("json_fallback_path") or "").strip() or None
        try:
            result = domain_vector_index_service().reindex_domains(
                workspace_id=workspace_id,
                force=force,
                json_fallback_path=json_fallback_path,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.exception("domain vector reindex failed")
            return {
                "error": "domain vector reindex failed",
                "details": str(exc),
            }, 500
        return {"result": result}, 200


@admin_ns.route("/vector/embeddings/rebuild")
class RebuildEmbeddingVectors(Resource):
    @token_required
    @require_admin()
    def post(self):
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
        result = embedding_index_service().rebuild_index(
            include_tables=include_tables,
            limit=limit,
            workspace_id=workspace_id,
        )
        return {"result": result}, 200


@admin_ns.route("/vector/rebuild-all")
class RebuildAllVectors(Resource):
    @token_required
    @require_role("system:admin")
    def post(self):
        _require_admin()
        body = request.get_json(silent=True) or {}
        workspace_id = extract_workspace_id()
        force = bool(body.get("force", False))

        results = {}
        errors = {}

        try:
            results["semantic_concepts"] = semantic_concept_embedding_service().rebuild_semantic_concept_index()
        except (ForgeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.exception("rebuild-all: semantic concepts failed")
            errors["semantic_concepts"] = str(exc)

        try:
            results["embeddings"] = embedding_index_service().rebuild_index(
                include_tables=True,
                workspace_id=workspace_id,
            )
        except (ForgeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.exception("rebuild-all: embeddings failed")
            errors["embeddings"] = str(exc)

        try:
            results["domain_vectors"] = domain_vector_index_service().reindex_domains(
                workspace_id=workspace_id,
                force=force,
            )
        except (ForgeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.exception("rebuild-all: domain vectors failed")
            errors["domain_vectors"] = str(exc)

        overall = "completed" if not errors else "completed_with_errors"
        return {
            "status": overall,
            "results": results,
            "errors": errors,
            "workspace_id": workspace_id,
        }, 200


@admin_ns.route("/domain-profiles")
class DomainProfileList(Resource):
    @token_required
    @require_admin()
    def get(self):
        workspace_id = extract_workspace_id()
        profiles = domain_profile_service().list_profiles(workspace_id)
        return {"profiles": profiles, "count": len(profiles)}, 200

    @token_required
    @require_admin()
    @admin_ns.expect(domain_profile_model, validate=False)
    def post(self):
        body = request.get_json(silent=True) or {}
        workspace_id = extract_workspace_id()
        body["workspace_id"] = workspace_id
        req = DomainProfileCreateRequest(**body)
        result = domain_profile_service().create_profile(req)
        return result, 201


@admin_ns.route("/domain-profiles/<int:domain_id>")
class DomainProfileDetail(Resource):
    @token_required
    @require_admin()
    def get(self, domain_id: int):
        workspace_id = extract_workspace_id()
        result = domain_profile_service().get_profile(workspace_id, domain_id)
        return result, 200

    @token_required
    @require_admin()
    @admin_ns.expect(domain_profile_model, validate=False)
    def put(self, domain_id: int):
        body = request.get_json(silent=True) or {}
        workspace_id = extract_workspace_id()
        req = DomainProfileUpdateRequest(**body)
        result = domain_profile_service().update_profile(
            workspace_id,
            domain_id,
            req,
        )
        return result, 200

    @token_required
    @require_admin()
    def delete(self, domain_id: int):
        workspace_id = extract_workspace_id()
        result = domain_profile_service().delete_profile(workspace_id, domain_id)
        return result, 200


@admin_ns.route("/domain-profiles/<int:domain_id>/generate")
class DomainProfileGenerateOne(Resource):
    @token_required
    @require_admin()
    @admin_ns.expect(domain_profile_generate_one_model, validate=False)
    def post(self, domain_id: int):
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
        result = domain_profile_embedding_service().generate_one(**args)
        return {"result": result}, 200


@admin_ns.route("/domain-profiles/generate")
class DomainProfileGenerateBatch(Resource):
    @token_required
    @require_admin()
    @admin_ns.expect(domain_profile_generate_batch_model, validate=False)
    def post(self):
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
        result = domain_profile_embedding_service().generate_many(**args)
        return result, 200


@admin_ns.route("/domain-profiles/generate-all")
class DomainProfileGenerateAll(Resource):
    @token_required
    @require_admin()
    @admin_ns.expect(domain_profile_generate_all_model, validate=False)
    def post(self):
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
        result = domain_profile_embedding_service().generate_all(**args)
        return result, 200


@admin_ns.route("/semantic-catalog/build")
class SemanticCatalogBuild(Resource):
    @token_required
    @require_admin()
    @admin_ns.expect(semantic_catalog_build_model, validate=False)
    def post(self):
        _require_admin()
        req = SemanticCatalogBuildRequest(**(request.get_json(silent=True) or {}))
        header_workspace_id = extract_workspace_id()
        if req.workspace_id and req.workspace_id != header_workspace_id:
            raise ForgeError(
                "workspace_id in body must match X-Workspace-Id header",
                status_code=400,
            )
        workspace_id = req.workspace_id or header_workspace_id
        result = semantic_catalog_builder().build_catalog(
            workspace_id=workspace_id,
            domain_id=req.domain_id,
            domain_name=req.domain_name,
            dry_run=req.dry_run,
            table_limit=req.table_limit,
            llm_id=req.llm_id,
        )
        payload = (
            result.model_dump(mode="json")
            if hasattr(result, "model_dump")
            else result
        )
        return {"result": payload}, 200
