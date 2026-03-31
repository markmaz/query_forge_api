from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace, Resource, fields

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.llm_unavailable_error import LLMUnavailableError
from app.routes.request_helpers import extract_workspace_id
from app.services.query_studio_summary_service import generate_preview_summary

logger = logging.getLogger(__name__)

query_studio_summary_ns = Namespace(
    "query_studio_summary",
    description="Query Studio AI Result Summary",
)

_summarize_request = query_studio_summary_ns.model(
    "SummarizeRequest",
    {
        "workspace_id": fields.String(required=True),
        "query_name": fields.String(required=True),
        "column_names": fields.List(fields.String(), required=True),
        "rows": fields.List(fields.Raw(), required=True),
        "prompt_hint": fields.String(required=False),
    },
)

_summarize_response = query_studio_summary_ns.model(
    "SummarizeResponse",
    {
        "narrative": fields.String(),
        "highlights": fields.List(fields.String()),
        "comparison": fields.String(allow_null=True),
        "capped": fields.Boolean(),
    },
)


@query_studio_summary_ns.route("/summarize")
class QueryStudioSummarize(Resource):
    @token_required
    @require_access("query_studio")
    @query_studio_summary_ns.expect(_summarize_request)
    def post(self):
        body = request.get_json(silent=True) or {}
        workspace_id = body.get("workspace_id")
        query_name = body.get("query_name")
        column_names = body.get("column_names")
        rows = body.get("rows")
        prompt_hint = body.get("prompt_hint")

        if not isinstance(workspace_id, str) or not workspace_id.strip():
            return {"error": "workspace_id is required", "code": "validation_error"}, 422
        if not isinstance(query_name, str) or not query_name.strip():
            return {"error": "query_name is required", "code": "validation_error"}, 422
        if column_names is None or not isinstance(column_names, list):
            return {"error": "column_names is required and must be an array", "code": "validation_error"}, 422
        if rows is None or not isinstance(rows, list):
            return {"error": "rows is required and must be an array", "code": "validation_error"}, 422

        header_workspace_id = extract_workspace_id()
        if workspace_id.strip() != header_workspace_id:
            return {"error": "workspace_id must match workspace header", "code": "validation_error"}, 422

        effective_hint = ""
        if isinstance(prompt_hint, str):
            effective_hint = prompt_hint

        try:
            result = generate_preview_summary(
                workspace_id=workspace_id,
                query_name=query_name,
                column_names=column_names,
                rows=rows,
                prompt_hint=effective_hint,
            )
        except LLMUnavailableError:
            return {"error": "LLM not configured for this workspace", "code": "llm_unavailable"}, 503
        except Exception:
            logger.exception("Summary generation failed")
            return {"error": "Summary generation failed", "code": "summary_failed"}, 500

        return result, 200
