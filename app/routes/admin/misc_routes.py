from __future__ import annotations

from flask import g, request
from flask_restx import Resource

from app.decorators.rbac import public, require_admin, require_role
from app.decorators.security import token_required
from app.routes.request_helpers import extract_workspace_id

from .base import admin_ns
from .deps import admin_health_service, prompt_feedback_service
from .helpers import _require_admin


@admin_ns.route("/healthz")
class ShowHealth(Resource):
    @public
    def get(self):
        return "OK", 200


@admin_ns.route("/health/detailed")
class DetailedHealth(Resource):
    @token_required
    @require_admin()
    def get(self):
        _require_admin()
        result = admin_health_service().check_all()
        return result, 200


@admin_ns.route("/health/broker")
class BrokerHealth(Resource):
    @token_required
    @require_role("system:admin")
    def get(self):
        _require_admin()
        result = admin_health_service().check_broker()
        return result, 200


@admin_ns.route("/pipeline-profiles")
class PipelineProfileList(Resource):
    @token_required
    @require_admin()
    def get(self):
        from app.services.planner_domain import PlannerDomainService

        limit = request.args.get("limit", 50, type=int)
        result = PlannerDomainService().list_pipeline_profiles(limit=limit)
        return {"profiles": result, "count": len(result)}, 200


@admin_ns.route("/pipeline-profiles/<string:trace_id>")
class PipelineProfileDetail(Resource):
    @token_required
    @require_admin()
    def get(self, trace_id: str):
        from app.services.planner_domain import PlannerDomainService

        workspace_id = extract_workspace_id()
        user_id = str(getattr(g, "user_id", "") or "")
        result = PlannerDomainService().get_pipeline_profile(
            trace_id=trace_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        return result, 200


@admin_ns.route("/prompt-feedback")
class AdminPromptFeedbackList(Resource):
    @token_required
    @require_admin()
    def get(self):
        workspace_id = extract_workspace_id()
        limit = request.args.get("limit", default=100, type=int) or 100
        offset = request.args.get("offset", default=0, type=int) or 0
        vote = str(request.args.get("vote") or "").strip() or None
        user_id = str(request.args.get("user_id") or "").strip() or None
        trace_id = str(request.args.get("trace_id") or "").strip() or None
        include_payload = str(
            request.args.get("include_payload") or ""
        ).strip().lower() in {"1", "true", "yes", "y", "on"}

        result = prompt_feedback_service().list_feedback(
            workspace_id=workspace_id,
            limit=limit,
            offset=offset,
            vote=vote,
            user_id=user_id,
            trace_id=trace_id,
            include_payload=include_payload,
        )
        return result, 200


@admin_ns.route("/prompt-feedback/<int:feedback_id>")
class AdminPromptFeedbackDelete(Resource):
    @token_required
    @require_admin()
    def delete(self, feedback_id: int):
        workspace_id = extract_workspace_id()
        result = prompt_feedback_service().delete_feedback(
            workspace_id=workspace_id,
            feedback_id=feedback_id,
        )
        return {"id": result.id, "deleted": result.deleted}, 200
