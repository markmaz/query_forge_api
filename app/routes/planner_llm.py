from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import fields
from app.routes.forge_resource import ForgeResource

from app.config import QF_PLANNER_LLM_ENABLED
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import extract_workspace_id
from app.routes.planner_extract import planner_ns
from app.services.planner_llm import PlannerLLMService

logger = logging.getLogger(__name__)

plan_llm_request_model = planner_ns.model(
    "PlannerLLMRequest",
    {
        "workspace_id": fields.String(required=False),
        "prompt": fields.String(required=True),
        "vertical": fields.String(required=False, default="generic"),
        "constraints": fields.Raw(required=False),
        "debug": fields.Boolean(required=False, default=False),
    },
)


@planner_ns.route("/plan_llm")
class PlannerPlanLLM(ForgeResource):
    @token_required
    @planner_ns.expect(plan_llm_request_model, validate=False)
    def post(self):
        if not QF_PLANNER_LLM_ENABLED:
            return {"error": "planner_llm route disabled"}, 404
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            header_workspace_id = extract_workspace_id()
            payload_workspace_id = str(body.get("workspace_id") or "").strip()
            if payload_workspace_id and payload_workspace_id != header_workspace_id:
                raise ForgeError("workspace_id must match X-Workspace-Id header", status_code=400)
            body["workspace_id"] = header_workspace_id
            result = PlannerLLMService().plan(body)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("planner llm failed")
            return {"error": "planner llm failed"}, 500

