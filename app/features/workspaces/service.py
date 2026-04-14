from __future__ import annotations

from flask import request

from app.exceptions.forge_error import ForgeError
from app.services.tenancy.workspace_llm_service import WorkspaceLLMService
from app.services.workspace_service import WorkspaceService


class WorkspacesFeatureService:
    @staticmethod
    def build_workspace_service(workspace_service_factory=WorkspaceService) -> WorkspaceService:
        return workspace_service_factory()

    @staticmethod
    def build_workspace_llm_service(workspace_llm_service_factory=WorkspaceLLMService) -> WorkspaceLLMService:
        return workspace_llm_service_factory()

    @staticmethod
    def workspace_id_header() -> str:
        workspace_id = (request.headers.get("X-Workspace-Id") or "").strip()
        if not workspace_id:
            raise ForgeError("Missing X-Workspace-Id header", status_code=400)
        return workspace_id

    @staticmethod
    def required_workspace_id_header() -> str:
        workspace_id = (request.headers.get("X-Workspace-Id") or "").strip()
        if not workspace_id:
            raise ForgeError("X-Workspace-Id header is required", status_code=400)
        return workspace_id

    @staticmethod
    def int_arg(name: str, default: int) -> int:
        raw = (request.args.get(name) or "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ForgeError(f"Invalid integer for '{name}'", status_code=400) from exc


workspaces_feature_service = WorkspacesFeatureService()
