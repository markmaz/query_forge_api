from __future__ import annotations

from typing import Any, Dict

from flask import request
from flask_restx import fields
from flask_restx import Resource

from app.config import QF_PLANNER_LLM_ENABLED
from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.planner.planner_extract_api import planner_ns
from app.routes.request_helpers import extract_workspace_id
from app.services.planner_llm import PlannerLLMService

plan_llm_request_model = planner_ns.model(
    "PlannerLLMRequest",
    {
        "workspace_id": fields.String(required=False),
        "prompt": fields.String(required=True),
        "vertical": fields.String(required=False, default="generic"),
        "constraints": fields.Raw(required=False),
        "debug": fields.Boolean(required=False, default=False),
        "llm_id": fields.Integer(required=False, description="Optional workspace LLM id override"),
    },
)


@planner_ns.route("/plan_llm")
class PlannerPlanLLM(Resource):
    @token_required
    @require_access("planner")
    @planner_ns.expect(plan_llm_request_model, validate=False)
    def post(self):
        if not QF_PLANNER_LLM_ENABLED:
            return {"error": "planner_llm route disabled"}, 404
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        header_workspace_id = extract_workspace_id()
        payload_workspace_id = str(body.get("workspace_id") or "").strip()
        if payload_workspace_id and payload_workspace_id != header_workspace_id:
            raise ForgeError("workspace_id must match X-Workspace-Id header", status_code=400)
        body["workspace_id"] = header_workspace_id
        result = PlannerLLMService().plan(body)
        return result, 200
