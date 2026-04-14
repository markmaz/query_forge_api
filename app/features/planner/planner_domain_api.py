from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from typing import Any, Dict

from flask import g, request
from flask_restx import Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
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


class _PlanFailureTraceContext(AbstractContextManager[None]):
    def __init__(self, *, planner_service: PlannerFeatureService, payload: Dict[str, Any]) -> None:
        self._planner_service = planner_service
        self._payload = payload

    def __exit__(self, exc_type, exc, exc_tb) -> bool:
        del exc_type, exc_tb
        if exc is None:
            return False
        trace_id = self._planner_service.emit_failed_plan_trace(
            payload=self._payload,
            user_id=str(getattr(g, "user_id", "") or ""),
            error=exc,
        )
        if trace_id:
            g.failed_trace_id = trace_id
        return False


_PLAN_DOMAIN_FIELDS = frozenset(plan_domain_request_model.keys())
_NEXT_ACTION_FIELDS = frozenset(next_actions_request_model.keys())


def _reject_unknown_fields(body: Dict[str, Any], *, allowed_fields: frozenset[str]) -> None:
    unknown_fields = sorted(set(body) - allowed_fields)
    if not unknown_fields:
        return
    if len(unknown_fields) == 1:
        raise ForgeError(f"Unsupported field: {unknown_fields[0]}", status_code=400)
    raise ForgeError(f"Unsupported fields: {', '.join(unknown_fields)}", status_code=400)


@planner_ns.route("/plan_domain")
class PlannerPlanDomain(Resource):
    @token_required
    @require_access("planner")
    @planner_ns.expect(plan_domain_request_model, validate=False)
    def post(self):
        body: Dict[str, Any] = {}
        planner_service = PlannerFeatureService(planner_domain_service_factory=_planner_domain_service_factory())
        with _PlanFailureTraceContext(planner_service=planner_service, payload=body):
            body = request.get_json(silent=True) or {}
            _reject_unknown_fields(body, allowed_fields=_PLAN_DOMAIN_FIELDS)
            header_workspace_id = extract_workspace_id()
            payload_workspace_id = str(body.get("workspace_id") or "").strip()
            if payload_workspace_id and payload_workspace_id != header_workspace_id:
                raise ForgeError("workspace_id must match X-Workspace-Id header", status_code=400)

            body["workspace_id"] = header_workspace_id
            user_id = require_user_id()
            result = planner_service.plan_domain(body, user_id=user_id)
            return result, 200


@planner_ns.route("/plan_domain/profile/<string:trace_id>")
class PlannerPlanDomainProfile(Resource):
    @token_required
    @require_access("planner")
    def get(self, trace_id: str):
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


@planner_ns.route("/plan_domain/next_actions")
class PlannerPlanDomainNextActions(Resource):
    @token_required
    @require_access("planner")
    @planner_ns.expect(next_actions_request_model, validate=False)
    def post(self):
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        _reject_unknown_fields(body, allowed_fields=_NEXT_ACTION_FIELDS)
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
