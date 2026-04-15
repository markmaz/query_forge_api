from __future__ import annotations

import logging

from flask import g, request
from flask_restx import Namespace, fields
from flask_restx import Resource

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.models.domain.domain_profile_embedding import (
    DomainProfileGenerateAllRequest,
    DomainProfileGenerateOneRequest,
    DomainProfileGenerateRequest,
)
from app.routes.request_helpers import extract_workspace_id
from app.services.admin.domain_profile_embedding_service import DomainProfileEmbeddingService

logger = logging.getLogger(__name__)

domain_profile_embeddings_ns = Namespace(
    "domain-profiles",
    description="LLM domain profile embedding generation",
)

_generate_one_model = domain_profile_embeddings_ns.model(
    "DomainProfileGenerateOneRequestPublic",
    {
        "force": fields.Boolean(required=False, default=False),
        "llm_id": fields.Integer(required=False, description="Optional workspace LLM id override"),
    },
)

_generate_batch_model = domain_profile_embeddings_ns.model(
    "DomainProfileGenerateBatchRequestPublic",
    {
        "domain_ids": fields.List(fields.Integer, required=True),
        "force": fields.Boolean(required=False, default=False),
        "llm_id": fields.Integer(required=False, description="Optional workspace LLM id override"),
    },
)

_generate_all_model = domain_profile_embeddings_ns.model(
    "DomainProfileGenerateAllRequestPublic",
    {
        "force": fields.Boolean(required=False, default=False),
        "include_inactive": fields.Boolean(required=False, default=False),
        "llm_id": fields.Integer(required=False, description="Optional workspace LLM id override"),
    },
)


@domain_profile_embeddings_ns.route("/<int:domain_id>/generate")
class DomainProfileGenerateOne(Resource):
    @token_required
    @require_access("vector", role="admin")
    @domain_profile_embeddings_ns.expect(_generate_one_model, validate=False)
    def post(self, domain_id: int):
        _require_admin()
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


@domain_profile_embeddings_ns.route("/generate")
class DomainProfileGenerateBatch(Resource):
    @token_required
    @require_access("vector", role="admin")
    @domain_profile_embeddings_ns.expect(_generate_batch_model, validate=False)
    def post(self):
        _require_admin()
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


@domain_profile_embeddings_ns.route("/generate-all")
class DomainProfileGenerateAll(Resource):
    @token_required
    @require_access("vector", role="admin")
    @domain_profile_embeddings_ns.expect(_generate_all_model, validate=False)
    def post(self):
        _require_admin()
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


def _require_admin() -> None:
    if not bool(getattr(g, "is_admin", False)):
        raise ForgeError("Admin access required", status_code=403)
