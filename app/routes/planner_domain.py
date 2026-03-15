from __future__ import annotations

import logging
from typing import Any, Dict

from flask import g, request
from flask_restx import fields
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import require_user_id, extract_workspace_id
from app.routes.planner_extract import planner_ns
from app.services.planner_domain import PlannerDomainService

logger = logging.getLogger(__name__)

plan_domain_request_model = planner_ns.model(
    "PlannerDomainRequest",
    {
        "workspace_id": fields.String(required=False),
        "vertical_norm": fields.String(required=False, default="generic"),
        "prompt": fields.String(required=True),
        "conversation_id": fields.String(required=False),
        "context_seed_plan_json_v2": fields.Raw(required=False),
        "context_seed_last_prompt": fields.String(required=False),
        "base_domain_id": fields.Integer(required=False),
        "debug": fields.Boolean(required=False, default=False),
        "profile_pipeline": fields.Boolean(required=False, default=False),
        "profile_pipeline_data": fields.Boolean(required=False, default=False),
        "fast_mode": fields.Boolean(required=False),
        "next_actions_async": fields.Boolean(required=False),
        "llm_id": fields.Integer(required=False, description="Optional workspace LLM override id"),
    },
)

next_actions_request_model = planner_ns.model(
    "PlannerDomainNextActionsRequest",
    {
        "workspace_id": fields.String(required=False),
        "prompt": fields.String(required=True),
        "plan_json_v2": fields.Raw(required=True),
        "vertical_norm": fields.String(required=False, default="generic"),
        "base_domain_id": fields.Integer(required=False),
        "conversation_id": fields.String(required=False),
        "trace_id": fields.String(required=False),
        "llm_id": fields.Integer(required=False, description="Optional workspace LLM override id"),
    },
)


@planner_ns.route("/plan_domain")
class PlannerPlanDomain(ForgeResource):
    @token_required
    @planner_ns.expect(plan_domain_request_model, validate=False)
    def post(self):
        body: Dict[str, Any] = {}
        planner_service = PlannerDomainService()
        try:
            body = request.get_json(silent=True) or {}
            header_workspace_id = extract_workspace_id()
            payload_workspace_id = str(body.get("workspace_id") or "").strip()
            if payload_workspace_id and payload_workspace_id != header_workspace_id:
                raise ForgeError("workspace_id must match X-Workspace-Id header", status_code=400)

            body["workspace_id"] = header_workspace_id
            user_id = require_user_id()
            result = planner_service.plan(body, user_id=user_id)
            return result, 200
        except ForgeError as exc:
            trace_id = planner_service.emit_failed_plan_trace(
                payload=body,
                user_id=str(getattr(g, "user_id", "") or ""),
                error=exc,
            )
            response = exc.to_dict()
            if trace_id:
                details = response.get("details")
                if not isinstance(details, dict):
                    details = {}
                details.setdefault("trace_id", trace_id)
                response["details"] = details
            return response, exc.status_code
        except Exception as exc:
            trace_id = planner_service.emit_failed_plan_trace(
                payload=body,
                user_id=str(getattr(g, "user_id", "") or ""),
                error=exc,
            )
            logger.exception("planner domain failed")
            response: Dict[str, Any] = {"error": "planner domain failed"}
            if trace_id:
                response["details"] = {"trace_id": trace_id}
            return response, 500


@planner_ns.route("/plan_domain/profile/<string:trace_id>")
class PlannerPlanDomainProfile(ForgeResource):
    @token_required
    def get(self, trace_id: str):
        try:
            workspace_id = extract_workspace_id()
            user_id = require_user_id()
            result = PlannerDomainService().get_pipeline_profile(
                trace_id=trace_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("planner domain profile lookup failed")
            return {"error": "planner domain profile lookup failed"}, 500


@planner_ns.route("/plan_domain/next_actions")
class PlannerPlanDomainNextActions(ForgeResource):
    @token_required
    @planner_ns.expect(next_actions_request_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            header_workspace_id = extract_workspace_id()
            payload_workspace_id = str(body.get("workspace_id") or "").strip()
            if payload_workspace_id and payload_workspace_id != header_workspace_id:
                raise ForgeError("workspace_id must match X-Workspace-Id header", status_code=400)

            body["workspace_id"] = header_workspace_id
            user_id = require_user_id()
            result = PlannerDomainService().generate_next_actions(body, user_id=user_id)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("planner domain next actions failed")
            return {"error": "planner domain next actions failed"}, 500
