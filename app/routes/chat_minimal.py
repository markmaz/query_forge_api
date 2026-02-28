from __future__ import annotations

import logging
from typing import Any, Dict

from flask import current_app, request
from flask_restx import Namespace, Resource, fields

from app.config import QF_MINIMAL_CHAT_ENABLED
from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.routes._route_utils import get_user_id, get_workspace_id_from_header
from app.services.chat import MinimalChatService

logger = logging.getLogger(__name__)

chat_ns = Namespace("chat", description="Minimal chat endpoints")

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
class MinimalChatRoute(Resource):
    @token_required
    @chat_ns.expect(_chat_request_model, validate=False)
    def post(self):
        try:
            if not (current_app.config.get("QF_MINIMAL_CHAT_ENABLED", QF_MINIMAL_CHAT_ENABLED)):
                return {"error": "minimal chat route disabled"}, 404

            body: Dict[str, Any] = request.get_json(silent=True) or {}
            header_workspace_id = get_workspace_id_from_header()
            if str(body.get("workspace_id") or "").strip():
                raise ServiceError(
                    "workspace_id must be provided via X-Workspace-Id header only",
                    status_code=400,
                )

            service = MinimalChatService(
                base_url=current_app.config.get("VLLM_BASE_URL"),
                model=current_app.config.get("VLLM_MODEL"),
                timeout_seconds=current_app.config.get("VLLM_TIMEOUT"),
            )
            result = service.chat(body, workspace_id=header_workspace_id, user_id=get_user_id())
            return result, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("minimal chat failed")
            return {"error": "minimal chat failed"}, 500
