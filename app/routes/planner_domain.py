from __future__ import annotations

import logging
from typing import Any, Dict

from flask import request
from flask_restx import Resource, fields

from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.routes._route_utils import get_user_id, get_workspace_id_from_header
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
    },
)


@planner_ns.route("/plan_domain")
class PlannerPlanDomain(Resource):
    @token_required
    @planner_ns.expect(plan_domain_request_model, validate=False)
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            header_workspace_id = get_workspace_id_from_header()
            payload_workspace_id = str(body.get("workspace_id") or "").strip()
            if payload_workspace_id and payload_workspace_id != header_workspace_id:
                raise ServiceError("workspace_id must match X-Workspace-Id header", status_code=400)

            body["workspace_id"] = header_workspace_id
            user_id = get_user_id()
            result = PlannerDomainService().plan(body, user_id=user_id)
            return result, 200
        except ServiceError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("planner domain failed")
            return {"error": "planner domain failed"}, 500
