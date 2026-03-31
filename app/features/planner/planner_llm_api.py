from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Resource

from app.config import QF_PLANNER_LLM_ENABLED
from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import extract_workspace_id

from .planner_extract_api import planner_ns
from .schemas import register_planner_models
from .service import PlannerFeatureService

logger = logging.getLogger(__name__)
plan_llm_request_model = register_planner_models(planner_ns)["plan_llm_request_model"]
PlannerLLMService = None


def _planner_llm_service_factory():
    if PlannerLLMService is not None:
        return PlannerLLMService
    from app.services.planner_llm import PlannerLLMService as _PlannerLLMService

    return _PlannerLLMService


@planner_ns.route("/plan_llm")
class PlannerPlanLLM(Resource):
    @token_required
    @require_access("planner")
    @planner_ns.expect(plan_llm_request_model, validate=False)
    def post(self):
        planner_service = PlannerFeatureService(
            planner_llm_service_factory=_planner_llm_service_factory(),
            planner_llm_enabled=QF_PLANNER_LLM_ENABLED,
        )
        if not planner_service.planner_llm_enabled:
            return {"error": "planner_llm route disabled"}, 404
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            header_workspace_id = extract_workspace_id()
            payload_workspace_id = str(body.get("workspace_id") or "").strip()
            if payload_workspace_id and payload_workspace_id != header_workspace_id:
                raise ForgeError("workspace_id must match X-Workspace-Id header", status_code=400)
            body["workspace_id"] = header_workspace_id
            result = planner_service.plan_llm(body)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("planner llm failed")
            return {"error": "planner llm failed"}, 500
