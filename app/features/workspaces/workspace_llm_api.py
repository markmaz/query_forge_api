from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace, Resource, fields

from app.constants.llm_roles import LLMProvider, LLMRole
from app.decorators.rbac import require_admin
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.services.tenancy.workspace_llm_service import WorkspaceLLMService

logger = logging.getLogger(__name__)

workspace_llm_ns = Namespace("workspace-llms", description="Workspace LLM configuration")
llm_roles_ns = Namespace("llm-roles", description="Available LLM roles")
llm_providers_ns = Namespace("llm-providers", description="Available LLM providers")

_llm_create_model = workspace_llm_ns.model(
    "WorkspaceLLMCreate",
    {
        "name": fields.String(required=True, description="Friendly name"),
        "provider": fields.String(required=True, description="LLM provider"),
        "model_name": fields.String(required=True, description="Model identifier"),
        "role": fields.String(required=True, description="Pipeline role"),
        "api_key": fields.String(description="API key (write-only, never returned)"),
        "endpoint_url": fields.String(description="Base URL for azure_openai or ollama"),
        "is_active": fields.Boolean(default=True),
        "config_json": fields.Raw(description="Optional extra provider config"),
    },
)


@llm_roles_ns.route("")
class LLMRolesList(Resource):
    @token_required
    @require_admin()
    def get(self):
        return [{"value": role, "label": LLMRole.DISPLAY_NAMES.get(role, role)} for role in LLMRole.ALL], 200


@llm_providers_ns.route("")
class LLMProvidersList(Resource):
    @token_required
    @require_admin()
    def get(self):
        return [{"value": provider, "label": LLMProvider.DISPLAY_NAMES.get(provider, provider)} for provider in LLMProvider.ALL], 200


@workspace_llm_ns.route("/workspaces/<string:workspace_id>/llms")
class WorkspaceLLMList(Resource):
    @token_required
    @require_admin()
    def get(self, workspace_id: str):
        try:
            svc = WorkspaceLLMService()
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
            svc = WorkspaceLLMService()
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
            svc = WorkspaceLLMService()
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
            svc = WorkspaceLLMService()
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
            svc = WorkspaceLLMService()
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
            svc = WorkspaceLLMService()
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
