from __future__ import annotations

from typing import Any, Tuple

from flask_restx import Resource

from app.features.domains import shared as domain_routes
from app.features.domains.common import qf_domains_ns


@qf_domains_ns.route("/<int:domain_id>/capabilities")
class DomainCapabilities(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            payload = domain_routes.DomainCapabilitiesService().get_domain_capabilities(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
                domain_id=domain_id,
            )
            return payload, 200

        return domain_routes.run(handler)


@qf_domains_ns.route("/<int:domain_id>/overlay-metrics")
class DomainOverlayMetrics(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            metrics = domain_routes.DomainCapabilitiesService().get_overlay_metrics(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
                domain_id=domain_id,
            )
            return {"domain_id": int(domain_id), "overlay_metrics": metrics}, 200

        return domain_routes.run(handler)


@qf_domains_ns.route("/<int:domain_id>/profile-metrics")
class DomainProfileMetrics(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            payload = domain_routes.DomainProfileMetricConfigService().get_profile_metrics(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
                domain_id=domain_id,
            )
            return payload, 200

        return domain_routes.run(handler)

    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def put(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            body = domain_routes.json_body_dict()
            payload = domain_routes.DomainProfileMetricConfigService().update_profile_metrics(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
                domain_id=domain_id,
                metrics_payload=body.get("metrics"),
            )
            return payload, 200

        return domain_routes.run(handler)


@qf_domains_ns.route("/<int:domain_id>/time-policy")
class DomainTimePolicy(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            payload = domain_routes.DomainTimePolicyService().get_policy(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
                domain_id=domain_id,
            )
            return payload, 200

        return domain_routes.run(handler)

    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def put(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            body = domain_routes.json_body_dict()
            policy_payload = body.get("policy", body)
            payload = domain_routes.DomainTimePolicyService().update_policy(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
                domain_id=domain_id,
                policy_payload=policy_payload,
            )
            return payload, 200

        return domain_routes.run(handler)
