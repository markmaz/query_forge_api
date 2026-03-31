from __future__ import annotations

import logging
from typing import Any, Dict

from flask import g, request
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import extract_workspace_id, require_user_id

from .planner_extract_api import planner_ns
from .schemas import register_planner_models
from .service import PlannerFeatureService

logger = logging.getLogger(__name__)
_planner_models = register_planner_models(planner_ns)
plan_domain_request_model = _planner_models["plan_domain_request_model"]
next_actions_request_model = _planner_models["next_actions_request_model"]
PlannerDomainService = None


def _planner_domain_service_factory():
    if PlannerDomainService is not None:
        return PlannerDomainService
    from app.services.planner_domain import PlannerDomainService as _PlannerDomainService

    return _PlannerDomainService


@planner_ns.route("/plan_domain")
class PlannerPlanDomain(ForgeResource):
    @token_required
    @require_access("planner")
    @planner_ns.expect(plan_domain_request_model, validate=False)
    def post(self):
        body: Dict[str, Any] = {}
        planner_service = PlannerFeatureService(planner_domain_service_factory=_planner_domain_service_factory())
        try:
            body = request.get_json(silent=True) or {}
            header_workspace_id = extract_workspace_id()
            payload_workspace_id = str(body.get("workspace_id") or "").strip()
            if payload_workspace_id and payload_workspace_id != header_workspace_id:
                raise ForgeError("workspace_id must match X-Workspace-Id header", status_code=400)

            body["workspace_id"] = header_workspace_id
            user_id = require_user_id()
            result = planner_service.plan_domain(body, user_id=user_id)
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
    @require_access("planner")
    def get(self, trace_id: str):
        try:
            workspace_id = extract_workspace_id()
            user_id = require_user_id()
            result = PlannerFeatureService(
                planner_domain_service_factory=_planner_domain_service_factory(),
            ).get_pipeline_profile(
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
    @require_access("planner")
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
            result = PlannerFeatureService(
                planner_domain_service_factory=_planner_domain_service_factory(),
            ).generate_next_actions(body, user_id=user_id)
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("planner domain next actions failed")
            return {"error": "planner domain next actions failed"}, 500
