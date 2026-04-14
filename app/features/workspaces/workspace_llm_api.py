from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace, Resource

from app.constants.llm_roles import LLMProvider, LLMRole
from app.decorators.rbac import require_admin
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.services.tenancy.workspace_llm_service import WorkspaceLLMService

from .schemas import register_workspace_llm_models
from .service import workspaces_feature_service

logger = logging.getLogger(__name__)

workspace_llm_ns = Namespace("workspace-llms", description="Workspace LLM configuration")
llm_roles_ns = Namespace("llm-roles", description="Available LLM roles")
llm_providers_ns = Namespace("llm-providers", description="Available LLM providers")

_llm_create_model = register_workspace_llm_models(workspace_llm_ns)


@llm_roles_ns.route("")
class LLMRolesList(Resource):
    @token_required
    @require_admin()
    def get(self):
        return [
            {"value": role, "label": LLMRole.DISPLAY_NAMES.get(role, role)}
            for role in LLMRole.ALL
        ], 200


@llm_providers_ns.route("")
class LLMProvidersList(Resource):
    @token_required
    @require_admin()
    def get(self):
        return [
            {"value": provider, "label": LLMProvider.DISPLAY_NAMES.get(provider, provider)}
            for provider in LLMProvider.ALL
        ], 200


@workspace_llm_ns.route("/workspaces/<string:workspace_id>/llms")
class WorkspaceLLMList(Resource):
    @token_required
    @require_admin()
    def get(self, workspace_id: str):
        try:
            svc = workspaces_feature_service.build_workspace_llm_service(
                workspace_llm_service_factory=WorkspaceLLMService
            )
            return svc.get_all_for_workspace(workspace_id), 200
        except ForgeError as exc:
            return {"error": str(exc)}, getattr(exc, "status_code", 400)
        except Exception:
            logger.exception("GET workspace llms failed ws=%s", workspace_id)
            return {"error": "Failed to list workspace LLMs"}, 500

    @workspace_llm_ns.expect(_llm_create_model)
    @token_required
    @require_admin()
    def post(self, workspace_id: str):
        body = request.get_json(silent=True) or {}
        try:
            svc = workspaces_feature_service.build_workspace_llm_service(
                workspace_llm_service_factory=WorkspaceLLMService
            )
            result = svc.create_llm(workspace_id, body)
            return result, 201
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except ForgeError as exc:
            return {"error": str(exc)}, getattr(exc, "status_code", 400)
        except Exception:
            logger.exception("POST workspace llm failed ws=%s", workspace_id)
            return {"error": "Failed to create workspace LLM"}, 500


@workspace_llm_ns.route("/workspaces/<string:workspace_id>/llms/<int:llm_id>")
class WorkspaceLLMDetail(Resource):
    @token_required
    @require_admin()
    def get(self, workspace_id: str, llm_id: int):
        try:
            svc = workspaces_feature_service.build_workspace_llm_service(
                workspace_llm_service_factory=WorkspaceLLMService
            )
            result = svc.get_by_id(llm_id)
            if result is None or result.get("workspace_id") != workspace_id:
                return {"error": "Not found"}, 404
            return result, 200
        except Exception:
            logger.exception("GET workspace llm detail failed ws=%s id=%s", workspace_id, llm_id)
            return {"error": "Failed to get workspace LLM"}, 500

    @token_required
    @require_admin()
    def put(self, workspace_id: str, llm_id: int):
        body = request.get_json(silent=True) or {}
        try:
            svc = workspaces_feature_service.build_workspace_llm_service(
                workspace_llm_service_factory=WorkspaceLLMService
            )
            existing = svc.get_by_id(llm_id)
            if existing is None or existing.get("workspace_id") != workspace_id:
                return {"error": "Not found"}, 404
            result = svc.update_llm(llm_id, body)
            return result, 200
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except Exception:
            logger.exception("PUT workspace llm failed ws=%s id=%s", workspace_id, llm_id)
            return {"error": "Failed to update workspace LLM"}, 500

    @token_required
    @require_admin()
    def delete(self, workspace_id: str, llm_id: int):
        try:
            svc = workspaces_feature_service.build_workspace_llm_service(
                workspace_llm_service_factory=WorkspaceLLMService
            )
            existing = svc.get_by_id(llm_id)
            if existing is None or existing.get("workspace_id") != workspace_id:
                return {"error": "Not found"}, 404
            svc.delete_llm(llm_id)
            return {"deleted": True}, 200
        except ValueError as exc:
            return {"error": str(exc)}, 404
        except Exception:
            logger.exception("DELETE workspace llm failed ws=%s id=%s", workspace_id, llm_id)
            return {"error": "Failed to delete workspace LLM"}, 500


@workspace_llm_ns.route("/workspaces/<string:workspace_id>/llms/<int:llm_id>/test")
class WorkspaceLLMTest(Resource):
    @token_required
    @require_admin()
    def post(self, workspace_id: str, llm_id: int):
        try:
            svc = workspaces_feature_service.build_workspace_llm_service(
                workspace_llm_service_factory=WorkspaceLLMService
            )
            existing = svc.get_by_id(llm_id)
            if existing is None or existing.get("workspace_id") != workspace_id:
                return {"error": "Not found"}, 404
            result = svc.test_connection(llm_id)
            return result, 200
        except ValueError as exc:
            return {"error": str(exc)}, 404
        except Exception:
            logger.exception("POST workspace llm test failed ws=%s id=%s", workspace_id, llm_id)
            return {"error": "Connection test failed"}, 500
