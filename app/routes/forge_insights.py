from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Namespace, fields
from flask_restx import Resource

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.models.query.forge_insights_schema import (
    ForgeInsightsProjectCreateRequest,
    ForgeInsightsProjectResponse,
    ForgeInsightsProjectUpdateRequest,
    ForgeInsightsThreadCreateRequest,
    ForgeInsightsThreadResponse,
    ForgeInsightsThreadUpdateRequest,
)
from app.routes.request_helpers import bool_arg, require_user_id, extract_workspace_id, int_arg
from app.services.forge_insights_threads_service import ForgeInsightsThreadsService

logger = logging.getLogger(__name__)

forge_insights_ns = Namespace("forge-insights", description="ForgeInsights projects and threads")

_project_create_model = forge_insights_ns.model(
    "ForgeInsightsProjectCreateRequest",
    {
        "name": fields.String(required=True),
        "description": fields.String(required=False),
    },
)

_project_patch_model = forge_insights_ns.model(
    "ForgeInsightsProjectUpdateRequest",
    {
        "name": fields.String(required=False),
        "description": fields.String(required=False),
        "is_archived": fields.Boolean(required=False),
    },
)

_thread_create_model = forge_insights_ns.model(
    "ForgeInsightsThreadCreateRequest",
    {
        "project_id": fields.Integer(required=False),
        "conversation_id": fields.String(required=False),
        "title": fields.String(required=False),
        "preview_text": fields.String(required=False),
        "is_pinned": fields.Boolean(required=False),
        "is_archived": fields.Boolean(required=False),
    },
)

_thread_patch_model = forge_insights_ns.model(
    "ForgeInsightsThreadUpdateRequest",
    {
        "project_id": fields.Integer(required=False),
        "title": fields.String(required=False),
        "preview_text": fields.String(required=False),
        "is_pinned": fields.Boolean(required=False),
        "is_archived": fields.Boolean(required=False),
        "last_message_at": fields.String(required=False, description="ISO datetime"),
    },
)


def _service() -> ForgeInsightsThreadsService:
    return ForgeInsightsThreadsService()


@forge_insights_ns.route("/projects")
class ForgeInsightsProjectsRoute(Resource):
    @token_required
    @require_access("forge_insights")
    def get(self):
        workspace_id = extract_workspace_id()
        user_id = require_user_id()
        include_archived = bool_arg("include_archived", False) is True
        items = _service().list_projects(
            workspace_id=workspace_id,
            user_id=user_id,
            include_archived=include_archived,
        )
        return {"items": [ForgeInsightsProjectResponse.model_validate(i).model_dump(mode="json") for i in items]}, 200

    @token_required
    @require_access("forge_insights")
    @forge_insights_ns.expect(_project_create_model, validate=False)
    def post(self):
        workspace_id = extract_workspace_id()
        user_id = require_user_id()
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        parsed = ForgeInsightsProjectCreateRequest.model_validate(body)
        row = _service().create_project(
            workspace_id=workspace_id,
            user_id=user_id,
            name=parsed.name,
            description=parsed.description,
        )
        return ForgeInsightsProjectResponse.model_validate(row).model_dump(mode="json"), 201


@forge_insights_ns.route("/projects/<int:project_id>")
class ForgeInsightsProjectRoute(Resource):
    @token_required
    @require_access("forge_insights")
    @forge_insights_ns.expect(_project_patch_model, validate=False)
    def patch(self, project_id: int):
        workspace_id = extract_workspace_id()
        user_id = require_user_id()
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        parsed = ForgeInsightsProjectUpdateRequest.model_validate(body)
        row = _service().update_project(
            workspace_id=workspace_id,
            user_id=user_id,
            project_id=project_id,
            name=parsed.name,
            description=parsed.description,
            is_archived=parsed.is_archived,
        )
        return ForgeInsightsProjectResponse.model_validate(row).model_dump(mode="json"), 200

    @token_required
    @require_access("forge_insights")
    def delete(self, project_id: int):
        workspace_id = extract_workspace_id()
        user_id = require_user_id()
        result = _service().delete_project(workspace_id=workspace_id, user_id=user_id, project_id=project_id)
        return result, 200


@forge_insights_ns.route("/threads")
class ForgeInsightsThreadsRoute(Resource):
    @token_required
    @require_access("forge_insights")
    def get(self):
        try:
            workspace_id = extract_workspace_id()
            user_id = require_user_id()
            project_id_raw = request.args.get("project_id")
            project_id = int(project_id_raw) if project_id_raw not in (None, "") else None
            include_archived = bool_arg("include_archived", False) is True
            include_stale = bool_arg("include_stale", False) is True
            limit = int_arg("limit", 50)
            offset = int_arg("offset", 0)
            items = _service().list_threads(
                workspace_id=workspace_id,
                user_id=user_id,
                project_id=project_id,
                include_archived=include_archived,
                include_stale=include_stale,
                limit=limit,
                offset=offset,
            )
            return {"items": [ForgeInsightsThreadResponse.model_validate(i).model_dump(mode="json") for i in items]}, 200
        except ValueError:
            return {"error": "Invalid integer for 'project_id'"}, 400
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @token_required
    @require_access("forge_insights")
    @forge_insights_ns.expect(_thread_create_model, validate=False)
    def post(self):
        workspace_id = extract_workspace_id()
        user_id = require_user_id()
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        parsed = ForgeInsightsThreadCreateRequest.model_validate(body)
        row = _service().create_thread(
            workspace_id=workspace_id,
            user_id=user_id,
            project_id=parsed.project_id,
            conversation_id=parsed.conversation_id,
            title=parsed.title,
            preview_text=parsed.preview_text,
            is_pinned=parsed.is_pinned,
            is_archived=parsed.is_archived,
        )
        return ForgeInsightsThreadResponse.model_validate(row).model_dump(mode="json"), 201


@forge_insights_ns.route("/threads/<int:thread_id>")
class ForgeInsightsThreadRoute(Resource):
    @token_required
    @require_access("forge_insights")
    def get(self, thread_id: int):
        workspace_id = extract_workspace_id()
        user_id = require_user_id()
        row = _service().get_thread(workspace_id=workspace_id, user_id=user_id, thread_id=thread_id)
        return ForgeInsightsThreadResponse.model_validate(row).model_dump(mode="json"), 200

    @token_required
    @require_access("forge_insights")
    @forge_insights_ns.expect(_thread_patch_model, validate=False)
    def patch(self, thread_id: int):
        workspace_id = extract_workspace_id()
        user_id = require_user_id()
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        parsed = ForgeInsightsThreadUpdateRequest.model_validate(body)
        row = _service().update_thread(
            workspace_id=workspace_id,
            user_id=user_id,
            thread_id=thread_id,
            project_id=parsed.project_id,
            title=parsed.title,
            preview_text=parsed.preview_text,
            is_pinned=parsed.is_pinned,
            is_archived=parsed.is_archived,
            last_message_at=parsed.last_message_at,
        )
        return ForgeInsightsThreadResponse.model_validate(row).model_dump(mode="json"), 200

    @token_required
    @require_access("forge_insights")
    def delete(self, thread_id: int):
        workspace_id = extract_workspace_id()
        user_id = require_user_id()
        result = _service().delete_thread(workspace_id=workspace_id, user_id=user_id, thread_id=thread_id)
        return result, 200
