from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Namespace, fields, Resource
from pydantic import ValidationError

from app.config import QF_PROMPT_FEEDBACK_MAX_PAYLOAD_BYTES
from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.models.query.prompt_feedback_schema import PromptFeedbackRequest, PromptFeedbackResponse
from app.services.prompt_feedback_service import PromptFeedbackService

from .service import ai_feature_service

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
        "workspace_id": fields.String(required=True, description="Workspace id. Must match the X-Workspace-Id header."),
        "trace_id": fields.String(required=False, description="Optional planner/copilot trace id used for idempotent feedback upserts."),
        "vote": fields.String(required=True, enum=["up", "down", "thumbs_up", "thumbs_down"], description="User feedback vote. Aliases normalize to up/down."),
        "normalized_prompt": fields.String(required=False, description="Normalized prompt text captured from the planner/copilot flow."),
        "prompt_text": fields.String(required=False, description="Raw prompt text as entered by the user."),
        "feedback_comment": fields.String(required=False, description="Optional reviewer-style free-text comment stored under reserved feedback-learning metadata."),
        "response_json": fields.Raw(required=True, description="Required planner/copilot response payload snapshot."),
        "meta": fields.Nested(_prompt_feedback_meta_model, required=False, description="Optional metadata captured alongside the feedback event."),
    },
)

_prompt_feedback_response_model = prompt_feedback_ns.model(
    "PromptFeedbackResponse",
    {
        "id": fields.Integer(required=True, description="Persisted prompt feedback record id."),
        "vote": fields.String(required=True, enum=["up", "down"], description="Normalized vote value."),
        "status": fields.String(required=True, enum=["recorded", "analysis_pending"], description="Submission status. Negative feedback returns analysis_pending for later learning analysis."),
        "created_at": fields.DateTime(required=True, description="Created timestamp in ISO-8601 format."),
        "updated_at": fields.DateTime(required=True, description="Updated timestamp in ISO-8601 format."),
    },
)


@prompt_feedback_ns.route("")
class PromptFeedback(Resource):
    @token_required
    @require_access("ai")
    @prompt_feedback_ns.expect(_prompt_feedback_request_model, validate=False)
    @prompt_feedback_ns.marshal_with(_prompt_feedback_response_model, code=201, description="Prompt feedback created.")
    @prompt_feedback_ns.doc(
        summary="Capture user prompt feedback",
        description=(
            "Stores user feedback for a planner/copilot response. The endpoint is backward compatible with existing callers, "
            "normalizes vote aliases, enforces workspace-header matching, and marks negative feedback as analysis_pending "
            "for the later feedback-learning pipeline. Optional feedback_comment text is stored under reserved feedback-learning metadata."
        ),
        responses={
            200: "Prompt feedback updated for an existing workspace/user/trace tuple.",
            400: "Invalid request payload or workspace mismatch.",
            401: "Authentication required.",
            403: "Caller lacks AI feature access.",
            413: "Payload exceeds configured size limit.",
            500: "Unexpected prompt feedback persistence failure.",
        },
    )
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            if not isinstance(body, dict):
                raise ForgeError("Invalid JSON body", status_code=400)

            if int(request.content_length or 0) > int(QF_PROMPT_FEEDBACK_MAX_PAYLOAD_BYTES):
                raise ForgeError(
                    f"request body exceeds max size of {int(QF_PROMPT_FEEDBACK_MAX_PAYLOAD_BYTES)} bytes",
                    status_code=413,
                )

            header_workspace_id = ai_feature_service.extract_workspace_id()
            payload_workspace_id = str(body.get("workspace_id") or "").strip()
            if not payload_workspace_id:
                raise ForgeError("workspace_id is required", status_code=400)
            if payload_workspace_id != header_workspace_id:
                raise ForgeError("workspace_id must match X-Workspace-Id header", status_code=400)

            parsed = PromptFeedbackRequest.model_validate(body)
            user_id = ai_feature_service.require_user_id()

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
                feedback_comment=parsed.feedback_comment,
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
                status=result.status,
            ).model_dump(mode="json")
            return payload, (201 if result.created else 200)
        except ValidationError as exc:
            return {
                "error": "Invalid request",
                "details": exc.errors(include_url=False, include_context=False, include_input=False),
            }, 400
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("prompt feedback failed")
            return {"error": "prompt feedback failed"}, 500
