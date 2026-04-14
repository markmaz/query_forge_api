from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Namespace, Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import extract_workspace_id
from app.services.semantic.plan_service import PlanService

from .schemas import register_plan_models
from .service import semantic_feature_service

logger = logging.getLogger(__name__)

semantic_ns = Namespace("semantic", description="Semantic query planning")
plan_request_model = register_plan_models(semantic_ns)


@semantic_ns.route("/plan")
class SemanticPlan(Resource):
    @token_required
    @require_access("semantic")
    @semantic_ns.expect(plan_request_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            body["workspace_id"] = extract_workspace_id()
            result = semantic_feature_service.build_plan_service(plan_service_factory=PlanService).plan(
                body, include_llm=True
            )
            return _shape_plan_response(result), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic plan failed")
            return {"error": "semantic plan failed"}, 500


@semantic_ns.route("/suggest-columns")
class SemanticSuggestColumns(Resource):
    @token_required
    @require_access("semantic")
    @semantic_ns.expect(plan_request_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            body["workspace_id"] = extract_workspace_id()
            result = semantic_feature_service.build_plan_service(plan_service_factory=PlanService).plan(
                body, include_llm=False
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("semantic suggest-columns failed")
            return {"error": "semantic suggest-columns failed"}, 500


def _shape_plan_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    out: Dict[str, Any] = dict(payload)
    llm_plan = out.get("llm_plan")
    if not isinstance(llm_plan, dict):
        return out

    llm_out: Dict[str, Any] = dict(llm_plan)
    sql_json = llm_out.get("sql_json")
    if isinstance(sql_json, dict):
        llm_out.setdefault("sqlJson", sql_json)
        out.setdefault("sqlJson", sql_json)
    out["llm_plan"] = llm_out
    return out
