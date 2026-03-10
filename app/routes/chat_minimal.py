from __future__ import annotations

import logging
from typing import Any, Dict

from flask import current_app, request
from flask_restx import Namespace, fields
from app.routes.forge_resource import ForgeResource

from app.config import QF_FORGE_INSIGHTS_ENABLED, QF_MINIMAL_CHAT_ENABLED
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import require_user_id, extract_workspace_id, int_arg
from app.services.chat import ForgeInsightsChatService, ForgeInsightsRouterService, MinimalChatService

logger = logging.getLogger(__name__)

chat_ns = Namespace("chat", description="Chat endpoints")

_chat_message_model = chat_ns.model(
    "MinimalChatMessage",
    {
        "role": fields.String(required=True, enum=["user", "assistant", "system"]),
        "content": fields.String(required=True),
    },
)

_chat_request_model = chat_ns.model(
    "MinimalChatRequest",
    {
        "messages": fields.List(fields.Nested(_chat_message_model), required=True),
        "conversation_id": fields.String(required=False),
        "stream": fields.Boolean(required=False, default=False),
        "temperature": fields.Float(required=False, default=0.2),
        "max_tokens": fields.Integer(required=False, default=512),
        "debug": fields.Boolean(required=False, default=False),
    },
)


@chat_ns.route("/minimal")
class MinimalChatRoute(ForgeResource):
    @token_required
    @chat_ns.expect(_chat_request_model, validate=False)
    def post(self):
        try:
            if not (current_app.config.get("QF_MINIMAL_CHAT_ENABLED", QF_MINIMAL_CHAT_ENABLED)):
                return {"error": "minimal chat route disabled"}, 404

            body: Dict[str, Any] = request.get_json(silent=True) or {}
            header_workspace_id = extract_workspace_id()
            if str(body.get("workspace_id") or "").strip():
                raise ForgeError(
                    "workspace_id must be provided via X-Workspace-Id header only",
                    status_code=400,
                )

            service = MinimalChatService(
                base_url=current_app.config.get("VLLM_BASE_URL"),
                model=current_app.config.get("VLLM_MODEL"),
                timeout_seconds=current_app.config.get("VLLM_TIMEOUT"),
            )
            result = service.chat(body, workspace_id=header_workspace_id, user_id=require_user_id())
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("minimal chat failed")
            return {"error": "minimal chat failed"}, 500


_forge_insights_list_response = chat_ns.model(
    "ForgeInsightsConversationListResponse",
    {
        "feature": fields.String(required=True, example="ForgeInsights"),
        "count": fields.Integer(required=True),
        "items": fields.List(fields.Raw, required=True),
    },
)

_forge_insights_detail_response = chat_ns.model(
    "ForgeInsightsConversationDetailResponse",
    {
        "feature": fields.String(required=True, example="ForgeInsights"),
        "conversation_id": fields.String(required=True),
        "messages": fields.List(fields.Nested(_chat_message_model), required=True),
        "summary": fields.String(required=False),
        "title": fields.String(required=False),
        "created_at": fields.String(required=False),
        "updated_at": fields.String(required=False),
        "message_count": fields.Integer(required=False),
        "last_user_message": fields.String(required=False),
    },
)

_forge_insights_delete_response = chat_ns.model(
    "ForgeInsightsConversationDeleteResponse",
    {
        "feature": fields.String(required=True, example="ForgeInsights"),
        "conversation_id": fields.String(required=True),
        "deleted": fields.Boolean(required=True),
    },
)


def _new_forge_insights_service() -> ForgeInsightsChatService:
    return ForgeInsightsChatService(
        base_url=current_app.config.get("VLLM_BASE_URL"),
        model=current_app.config.get("VLLM_MODEL"),
        timeout_seconds=current_app.config.get("VLLM_TIMEOUT"),
    )


def _new_forge_insights_router_service() -> ForgeInsightsRouterService:
    return ForgeInsightsRouterService(
        chat_service=ForgeInsightsChatService(
            base_url=current_app.config.get("VLLM_BASE_URL"),
            model=current_app.config.get("VLLM_MODEL"),
            timeout_seconds=current_app.config.get("VLLM_TIMEOUT"),
        )
    )


def _validate_forge_insights_enabled() -> None:
    if not current_app.config.get("QF_FORGE_INSIGHTS_ENABLED", QF_FORGE_INSIGHTS_ENABLED):
        raise ForgeError("forge insights route disabled", status_code=404)


@chat_ns.route("/forge-insights")
class ForgeInsightsChatRoute(ForgeResource):
    @token_required
    @chat_ns.expect(_chat_request_model, validate=False)
    def post(self):
        try:
            _validate_forge_insights_enabled()
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            header_workspace_id = extract_workspace_id()
            if str(body.get("workspace_id") or "").strip():
                raise ForgeError(
                    "workspace_id must be provided via X-Workspace-Id header only",
                    status_code=400,
                )

            result, status_code = _new_forge_insights_router_service().ask(
                body,
                workspace_id=header_workspace_id,
                user_id=require_user_id(),
                query_args=dict(request.args or {}),
            )
            return result, status_code
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge insights chat failed")
            return {"error": "forge insights chat failed"}, 500


@chat_ns.route("/forge-insights/conversations")
class ForgeInsightsConversationListRoute(ForgeResource):
    @token_required
    def get(self):
        try:
            _validate_forge_insights_enabled()
            workspace_id = extract_workspace_id()
            user_id = require_user_id()
            limit = int_arg("limit", 50)
            result = _new_forge_insights_service().list_conversations(
                workspace_id=workspace_id,
                user_id=user_id,
                limit=limit,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge insights list conversations failed")
            return {"error": "forge insights list conversations failed"}, 500


@chat_ns.route("/forge-insights/conversations/<string:conversation_id>")
class ForgeInsightsConversationDetailRoute(ForgeResource):
    @token_required
    def get(self, conversation_id: str):
        try:
            _validate_forge_insights_enabled()
            workspace_id = extract_workspace_id()
            user_id = require_user_id()
            result = _new_forge_insights_service().get_conversation(
                workspace_id=workspace_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge insights get conversation failed")
            return {"error": "forge insights get conversation failed"}, 500

    @token_required
    def delete(self, conversation_id: str):
        try:
            _validate_forge_insights_enabled()
            workspace_id = extract_workspace_id()
            user_id = require_user_id()
            result = _new_forge_insights_service().reset_conversation(
                workspace_id=workspace_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("forge insights delete conversation failed")
            return {"error": "forge insights delete conversation failed"}, 500
