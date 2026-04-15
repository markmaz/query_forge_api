from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Namespace, fields
from flask_restx import Resource

from app.config import QF_PROMPT_FEEDBACK_MAX_PAYLOAD_BYTES
from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.models.query.prompt_feedback_schema import PromptFeedbackRequest, PromptFeedbackResponse
from app.routes.request_helpers import require_user_id, extract_workspace_id
from app.services.prompt_feedback_service import PromptFeedbackService

logger = logging.getLogger(__name__)

prompt_feedback_ns = Namespace("prompt-feedback", description="Prompt feedback endpoints")

_prompt_feedback_meta_model = prompt_feedback_ns.model(
    "PromptFeedbackMeta",
    {
        "model": fields.String(required=False),
        "timings_ms": fields.Raw(required=False),
        "domain_id": fields.Integer(required=False),
        "domain_version": fields.Integer(required=False),
        "intent": fields.String(required=False),
    },
)

_prompt_feedback_request_model = prompt_feedback_ns.model(
    "PromptFeedbackRequest",
    {
        "workspace_id": fields.String(required=True),
        "trace_id": fields.String(required=False),
        "vote": fields.String(required=True, enum=["up", "down", "thumbs_up", "thumbs_down"]),
        "normalized_prompt": fields.String(required=False),
        "prompt_text": fields.String(required=False),
        "response_json": fields.Raw(required=True),
        "meta": fields.Nested(_prompt_feedback_meta_model, required=False),
    },
)


@prompt_feedback_ns.route("")
class PromptFeedback(Resource):
    @token_required
    @require_access("ai")
    @prompt_feedback_ns.expect(_prompt_feedback_request_model, validate=False)
    def post(self):
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            raise ForgeError("Invalid JSON body", status_code=400)

        if int(request.content_length or 0) > int(QF_PROMPT_FEEDBACK_MAX_PAYLOAD_BYTES):
            raise ForgeError(
                f"request body exceeds max size of {int(QF_PROMPT_FEEDBACK_MAX_PAYLOAD_BYTES)} bytes",
                status_code=413,
            )

        header_workspace_id = extract_workspace_id()
        payload_workspace_id = str(body.get("workspace_id") or "").strip()
        if not payload_workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)
        if payload_workspace_id != header_workspace_id:
            raise ForgeError("workspace_id must match X-Workspace-Id header", status_code=400)

        parsed = PromptFeedbackRequest.model_validate(body)
        user_id = require_user_id()

        service = PromptFeedbackService(
            max_payload_bytes=int(QF_PROMPT_FEEDBACK_MAX_PAYLOAD_BYTES),
        )
        result = service.save_feedback(
            workspace_id=header_workspace_id,
            user_id=user_id,
            trace_id=parsed.trace_id,
            vote=parsed.vote,
            normalized_prompt=parsed.normalized_prompt,
            prompt_text=parsed.prompt_text,
            response_json=parsed.response_json,
            meta=parsed.meta.model_dump(mode="json", exclude_none=True) if parsed.meta else None,
        )
        logger.info(
            "prompt feedback stored trace_id=%s workspace_id=%s user_id=%s vote=%s created=%s",
            parsed.trace_id,
            header_workspace_id,
            user_id,
            result.vote,
            result.created,
        )
        payload = PromptFeedbackResponse(
            id=result.id,
            created_at=result.created_at,
            updated_at=result.updated_at,
            vote=result.vote,
        ).model_dump(mode="json")
        return payload, (201 if result.created else 200)
