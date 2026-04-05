from __future__ import annotations

from flask import g, request
from flask_restx import Resource

from app.decorators.rbac import require_admin
from app.decorators.security import token_required
from app.routes.request_helpers import extract_workspace_id

from .base import admin_ns
from .deps import (
    planner_domain_selection_policy_service,
    planner_projection_policy_service,
    planner_prompt_intent_policy_service,
    planner_retrieval_policy_service,
    planner_signal_policy_service,
)
from .helpers import _as_bool
from .models import (
    planner_domain_selection_policy_model,
    planner_projection_policy_model,
    planner_prompt_intent_policy_model,
    planner_retrieval_policy_model,
    planner_signal_policy_model,
)


@admin_ns.route("/planner-projection-policies")
class AdminPlannerProjectionPolicies(Resource):
    @token_required
    @require_admin()
    def get(self):
        workspace_id = extract_workspace_id()
        base_domain_id_raw = request.args.get("base_domain_id")
        base_domain_id = (
            int(base_domain_id_raw)
            if (base_domain_id_raw or "").strip()
            else None
        )
        vertical_norm = (
            (request.args.get("vertical_norm") or "generic").strip().lower()
            or "generic"
        )
        include_inactive = _as_bool(
            request.args.get("include_inactive"),
            default=False,
        )
        include_seeded = _as_bool(
            request.args.get("include_seeded"),
            default=True,
        )
        result = planner_projection_policy_service().list_policies(
            workspace_id=workspace_id,
            base_domain_id=base_domain_id,
            vertical_norm=vertical_norm,
            include_inactive=include_inactive,
            include_seeded=include_seeded,
        )
        return result, 200

    @token_required
    @require_admin()
    @admin_ns.expect(planner_projection_policy_model, validate=False)
    def put(self):
        workspace_id = extract_workspace_id()
        result = planner_projection_policy_service().upsert_policy(
            workspace_id=workspace_id,
            actor_user_id=str(getattr(g, "user_id", "") or ""),
            payload=request.get_json(silent=True) or {},
        )
        return result, 200


@admin_ns.route("/planner-projection-policies/<int:policy_id>")
class AdminPlannerProjectionPolicyDetail(Resource):
    @token_required
    @require_admin()
    def delete(self, policy_id: int):
        workspace_id = extract_workspace_id()
        result = planner_projection_policy_service().delete_policy(
            workspace_id=workspace_id,
            actor_user_id=str(getattr(g, "user_id", "") or ""),
            policy_id=policy_id,
        )
        return result, 200


@admin_ns.route("/planner-signal-policies")
class AdminPlannerSignalPolicies(Resource):
    @token_required
    @require_admin()
    def get(self):
        workspace_id = extract_workspace_id()
        include_inactive = _as_bool(
            request.args.get("include_inactive"),
            default=False,
        )
        include_seeded = _as_bool(
            request.args.get("include_seeded"),
            default=True,
        )
        result = planner_signal_policy_service().list_policies(
            workspace_id=workspace_id,
            include_inactive=include_inactive,
            include_seeded=include_seeded,
        )
        return result, 200

    @token_required
    @require_admin()
    @admin_ns.expect(planner_signal_policy_model, validate=False)
    def put(self):
        workspace_id = extract_workspace_id()
        result = planner_signal_policy_service().upsert_policy(
            workspace_id=workspace_id,
            actor_user_id=str(getattr(g, "user_id", "") or ""),
            payload=request.get_json(silent=True) or {},
        )
        return result, 200


@admin_ns.route("/planner-signal-policies/<int:policy_id>")
class AdminPlannerSignalPolicyDetail(Resource):
    @token_required
    @require_admin()
    def delete(self, policy_id: int):
        workspace_id = extract_workspace_id()
        result = planner_signal_policy_service().delete_policy(
            workspace_id=workspace_id,
            actor_user_id=str(getattr(g, "user_id", "") or ""),
            policy_id=policy_id,
        )
        return result, 200


@admin_ns.route("/planner-prompt-intent-policies")
class AdminPlannerPromptIntentPolicies(Resource):
    @token_required
    @require_admin()
    def get(self):
        workspace_id = extract_workspace_id()
        include_inactive = _as_bool(
            request.args.get("include_inactive"),
            default=False,
        )
        include_seeded = _as_bool(
            request.args.get("include_seeded"),
            default=True,
        )
        result = planner_prompt_intent_policy_service().list_policies(
            workspace_id=workspace_id,
            include_inactive=include_inactive,
            include_seeded=include_seeded,
        )
        return result, 200

    @token_required
    @require_admin()
    @admin_ns.expect(planner_prompt_intent_policy_model, validate=False)
    def put(self):
        workspace_id = extract_workspace_id()
        result = planner_prompt_intent_policy_service().upsert_policy(
            workspace_id=workspace_id,
            actor_user_id=str(getattr(g, "user_id", "") or ""),
            payload=request.get_json(silent=True) or {},
        )
        return result, 200


@admin_ns.route("/planner-prompt-intent-policies/<int:policy_id>")
class AdminPlannerPromptIntentPolicyDetail(Resource):
    @token_required
    @require_admin()
    def delete(self, policy_id: int):
        workspace_id = extract_workspace_id()
        result = planner_prompt_intent_policy_service().delete_policy(
            workspace_id=workspace_id,
            actor_user_id=str(getattr(g, "user_id", "") or ""),
            policy_id=policy_id,
        )
        return result, 200


@admin_ns.route("/planner-retrieval-policies")
class AdminPlannerRetrievalPolicies(Resource):
    @token_required
    @require_admin()
    def get(self):
        workspace_id = extract_workspace_id()
        include_inactive = _as_bool(
            request.args.get("include_inactive"),
            default=False,
        )
        include_seeded = _as_bool(
            request.args.get("include_seeded"),
            default=True,
        )
        result = planner_retrieval_policy_service().list_policies(
            workspace_id=workspace_id,
            include_inactive=include_inactive,
            include_seeded=include_seeded,
        )
        return result, 200

    @token_required
    @require_admin()
    @admin_ns.expect(planner_retrieval_policy_model, validate=False)
    def put(self):
        workspace_id = extract_workspace_id()
        result = planner_retrieval_policy_service().upsert_policy(
            workspace_id=workspace_id,
            actor_user_id=str(getattr(g, "user_id", "") or ""),
            payload=request.get_json(silent=True) or {},
        )
        return result, 200


@admin_ns.route("/planner-retrieval-policies/<int:policy_id>")
class AdminPlannerRetrievalPolicyDetail(Resource):
    @token_required
    @require_admin()
    def delete(self, policy_id: int):
        workspace_id = extract_workspace_id()
        result = planner_retrieval_policy_service().delete_policy(
            workspace_id=workspace_id,
            actor_user_id=str(getattr(g, "user_id", "") or ""),
            policy_id=policy_id,
        )
        return result, 200


@admin_ns.route("/planner-domain-selection-policies")
class AdminPlannerDomainSelectionPolicies(Resource):
    @token_required
    @require_admin()
    def get(self):
        workspace_id = extract_workspace_id()
        include_inactive = _as_bool(
            request.args.get("include_inactive"),
            default=False,
        )
        include_seeded = _as_bool(
            request.args.get("include_seeded"),
            default=True,
        )
        result = planner_domain_selection_policy_service().list_policies(
            workspace_id=workspace_id,
            include_inactive=include_inactive,
            include_seeded=include_seeded,
        )
        return result, 200

    @token_required
    @require_admin()
    @admin_ns.expect(planner_domain_selection_policy_model, validate=False)
    def put(self):
        workspace_id = extract_workspace_id()
        result = planner_domain_selection_policy_service().upsert_policy(
            workspace_id=workspace_id,
            actor_user_id=str(getattr(g, "user_id", "") or ""),
            payload=request.get_json(silent=True) or {},
        )
        return result, 200


@admin_ns.route("/planner-domain-selection-policies/<int:policy_id>")
class AdminPlannerDomainSelectionPolicyDetail(Resource):
    @token_required
    @require_admin()
    def delete(self, policy_id: int):
        workspace_id = extract_workspace_id()
        result = planner_domain_selection_policy_service().delete_policy(
            workspace_id=workspace_id,
            actor_user_id=str(getattr(g, "user_id", "") or ""),
            policy_id=policy_id,
        )
        return result, 200
