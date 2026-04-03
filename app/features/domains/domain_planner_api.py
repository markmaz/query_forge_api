from __future__ import annotations

from typing import Any, Tuple

from flask_restx import Resource

from app.features.domains import shared as domain_routes
from app.features.domains.common import qf_domains_ns


@qf_domains_ns.route("/planner-rerank-policies")
class DomainPlannerRerankPolicies(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self):
        def handler() -> Tuple[Any, int]:
            domain_id_raw = domain_routes.request.args.get("base_domain_id")
            domain_id = int(domain_id_raw) if (domain_id_raw or "").strip() else None
            vertical_norm = (domain_routes.request.args.get("vertical_norm") or "generic").strip().lower() or "generic"
            payload = domain_routes.PlannerRerankPolicyService().list_policies(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
                base_domain_id=domain_id,
                vertical_norm=vertical_norm,
                include_inactive=bool(domain_routes.bool_arg("include_inactive", default=False)),
            )
            return payload, 200

        return domain_routes.run(
            handler,
            log_message="Planner rerank policy fetch failed",
            client_error="Planner rerank policy fetch failed",
        )

    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def put(self):
        def handler() -> Tuple[Any, int]:
            body = domain_routes.json_body_dict()
            policy_payload = body.get("policy", body)
            payload = domain_routes.PlannerRerankPolicyService().upsert_policy(
                workspace_id=domain_routes.workspace_id(),
                actor_user_id=domain_routes.require_user_id(),
                payload=policy_payload,
            )
            return payload, 200

        return domain_routes.run(
            handler,
            log_message="Planner rerank policy update failed",
            client_error="Planner rerank policy update failed",
        )


@qf_domains_ns.route("/planner-rerank-policies/<int:policy_id>")
class DomainPlannerRerankPolicyDetail(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def delete(self, policy_id: int):
        def handler() -> Tuple[Any, int]:
            payload = domain_routes.PlannerRerankPolicyService().delete_policy(
                workspace_id=domain_routes.workspace_id(),
                actor_user_id=domain_routes.require_user_id(),
                policy_id=policy_id,
            )
            return payload, 200

        return domain_routes.run(
            handler,
            log_message=f"Planner rerank policy delete failed policy_id={policy_id}",
            client_error="Planner rerank policy delete failed",
        )


@qf_domains_ns.route("/planner-domain-capabilities")
class DomainPlannerCapabilities(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self):
        def handler() -> Tuple[Any, int]:
            domain_id_raw = domain_routes.request.args.get("base_domain_id")
            if not (domain_id_raw or "").strip():
                raise domain_routes.ForgeError("base_domain_id is required", status_code=400)
            vertical_norm = (domain_routes.request.args.get("vertical_norm") or "generic").strip().lower() or "generic"
            payload = domain_routes.PlannerDomainCapabilityService().list_capabilities(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
                base_domain_id=int(domain_id_raw),
                vertical_norm=vertical_norm,
                include_inactive=bool(domain_routes.bool_arg("include_inactive", default=False)),
            )
            return payload, 200

        return domain_routes.run(
            handler,
            log_message="Planner domain capability fetch failed",
            client_error="Planner domain capability fetch failed",
        )

    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def put(self):
        def handler() -> Tuple[Any, int]:
            body = domain_routes.json_body_dict()
            capability_payload = body.get("capability", body)
            payload = domain_routes.PlannerDomainCapabilityService().upsert_capability(
                workspace_id=domain_routes.workspace_id(),
                actor_user_id=domain_routes.require_user_id(),
                payload=capability_payload,
            )
            return payload, 200

        return domain_routes.run(
            handler,
            log_message="Planner domain capability update failed",
            client_error="Planner domain capability update failed",
        )


@qf_domains_ns.route("/planner-domain-capabilities/<int:capability_id>")
class DomainPlannerCapabilityDetail(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def delete(self, capability_id: int):
        def handler() -> Tuple[Any, int]:
            payload = domain_routes.PlannerDomainCapabilityService().delete_capability(
                workspace_id=domain_routes.workspace_id(),
                actor_user_id=domain_routes.require_user_id(),
                capability_id=capability_id,
            )
            return payload, 200

        return domain_routes.run(
            handler,
            log_message=f"Planner domain capability delete failed capability_id={capability_id}",
            client_error="Planner domain capability delete failed",
        )


@qf_domains_ns.route("/planner-rerank-policy-candidates")
class DomainPlannerRerankPolicyCandidates(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self):
        def handler() -> Tuple[Any, int]:
            payload = domain_routes.PlannerRerankPolicyCandidateService().list_candidates(
                workspace_id=domain_routes.workspace_id(),
                review_status=(domain_routes.request.args.get("review_status") or "").strip() or None,
                vertical_norm=(domain_routes.request.args.get("vertical_norm") or "").strip().lower() or None,
            )
            return payload, 200

        return domain_routes.run(
            handler,
            log_message="Planner rerank policy candidate fetch failed",
            client_error="Planner rerank policy candidate fetch failed",
        )

    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def post(self):
        def handler() -> Tuple[Any, int]:
            body = domain_routes.json_body_dict()
            candidate_payload = body.get("candidate", body)
            payload = domain_routes.PlannerRerankPolicyCandidateService().create_candidate(
                workspace_id=domain_routes.workspace_id(),
                payload=candidate_payload,
            )
            return payload, 201

        return domain_routes.run(
            handler,
            log_message="Planner rerank policy candidate create failed",
            client_error="Planner rerank policy candidate create failed",
        )

    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def put(self):
        def handler() -> Tuple[Any, int]:
            body = domain_routes.json_body_dict()
            candidate_payload = body.get("candidate", body)
            payload = domain_routes.PlannerRerankPolicyCandidateService().create_candidate(
                workspace_id=domain_routes.workspace_id(),
                payload=candidate_payload,
            )
            return payload, 200

        return domain_routes.run(
            handler,
            log_message="Planner rerank policy candidate update failed",
            client_error="Planner rerank policy candidate update failed",
        )


@qf_domains_ns.route("/planner-rerank-policy-candidates/<int:candidate_id>")
class DomainPlannerRerankPolicyCandidateDetail(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def delete(self, candidate_id: int):
        def handler() -> Tuple[Any, int]:
            payload = domain_routes.PlannerRerankPolicyCandidateService().delete_candidate(
                workspace_id=domain_routes.workspace_id(),
                candidate_id=candidate_id,
            )
            return payload, 200

        return domain_routes.run(
            handler,
            log_message=f"Planner rerank policy candidate delete failed candidate_id={candidate_id}",
            client_error="Planner rerank policy candidate delete failed",
        )


@qf_domains_ns.route("/planner-rerank-policy-candidates/<int:candidate_id>/approve")
class DomainPlannerRerankPolicyCandidateApprove(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def post(self, candidate_id: int):
        def handler() -> Tuple[Any, int]:
            body = domain_routes.json_body_dict()
            approval_payload = body.get("approval", body)
            payload = domain_routes.PlannerRerankPolicyCandidateService().approve_candidate(
                workspace_id=domain_routes.workspace_id(),
                actor_user_id=domain_routes.require_user_id(),
                candidate_id=candidate_id,
                payload=approval_payload,
            )
            return payload, 200

        return domain_routes.run(
            handler,
            log_message=f"Planner rerank policy candidate approve failed candidate_id={candidate_id}",
            client_error="Planner rerank policy candidate approve failed",
        )


@qf_domains_ns.route("/planner-rerank-policy-candidates/suggest")
class DomainPlannerRerankPolicyCandidateSuggest(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def post(self):
        def handler() -> Tuple[Any, int]:
            body = domain_routes.json_body_dict()
            suggestion_payload = body.get("suggestion", body)
            payload = domain_routes.PlannerRerankPolicyCandidateSuggestionService().suggest_candidate(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
                payload=suggestion_payload,
            )
            return payload, 201

        return domain_routes.run(
            handler,
            log_message="Planner rerank policy candidate suggestion failed",
            client_error="Planner rerank policy candidate suggestion failed",
        )
