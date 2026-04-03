from __future__ import annotations

from typing import Any, Tuple

from flask_restx import Resource

from app.features.domains import shared as domain_routes
from app.features.domains.common import qf_domains_ns


@qf_domains_ns.route("/")
class DomainsRoot(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self):
        def handler() -> Tuple[Any, int]:
            rows = domain_routes.UserDomainReadService().list_user_domains(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
            )
            return {"rows": rows}, 200

        return domain_routes.run(handler, log_message="Domains fetch failed", client_error="Domains fetch failed")

    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def post(self):
        def handler() -> Tuple[Any, int]:
            workspace_id = domain_routes.workspace_id()
            body = domain_routes.json_body_dict()
            row = domain_routes.DomainAdminWriteService().create_domain(
                workspace_id=workspace_id,
                user_id=domain_routes.require_user_id(),
                name=(body.get("name") or "").strip(),
                kind=body.get("kind"),
                description=body.get("description"),
                column_name_policy=body.get("column_name_policy"),
            )
            return {"row": row}, 201

        return domain_routes.run(handler, log_message="Domain create failed", client_error="Domain create failed")


@qf_domains_ns.route("/recommendations/generate")
class DomainRecommendationsGenerate(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def post(self):
        def handler() -> Tuple[Any, int]:
            body = domain_routes.json_body_dict()
            max_domains = body.get("max_domains", 10)
            max_tables = body.get("max_tables", 200)
            llm_id_raw = body.get("llm_id")
            llm_id = None
            if llm_id_raw not in (None, ""):
                try:
                    llm_id = int(llm_id_raw)
                except Exception as exc:
                    raise domain_routes.ForgeError("llm_id must be an integer", status_code=400) from exc
                if llm_id <= 0:
                    raise domain_routes.ForgeError("llm_id must be greater than 0", status_code=400)

            payload = domain_routes.DomainRecommendationService().generate_recommendations(
                workspace_id=domain_routes.workspace_id(),
                max_domains=max_domains,
                max_tables=max_tables,
                llm_id=llm_id,
            )
            return payload, 200

        return domain_routes.run(
            handler,
            log_message="Domain recommendations generate failed",
            client_error="Domain recommendations generate failed",
        )


@qf_domains_ns.route("/recommendations/apply")
class DomainRecommendationsApply(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def post(self):
        def handler() -> Tuple[Any, int]:
            body = domain_routes.json_body_dict()
            recommendations = body.get("recommendations")
            mode = body.get("mode", "create_only")
            column_name_policy = body.get("column_name_policy")

            payload = domain_routes.DomainRecommendationService().apply_recommendations(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
                recommendations=recommendations,
                mode=mode,
                column_name_policy=column_name_policy,
            )
            return payload, 200

        return domain_routes.run(
            handler,
            log_message="Domain recommendations apply failed",
            client_error="Domain recommendations apply failed",
        )


@qf_domains_ns.route("/<int:domain_id>")
class DomainById(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def patch(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            body = domain_routes.json_body_dict()
            row = domain_routes.DomainAdminWriteService().patch_domain(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
                domain_id=domain_id,
                name=body.get("name") if "name" in body else None,
                kind=body.get("kind") if "kind" in body else None,
                description=body.get("description") if "description" in body else None,
                is_active=body.get("is_active") if "is_active" in body else None,
                column_name_policy=body.get("column_name_policy") if "column_name_policy" in body else None,
            )
            return {"row": row}, 200

        return domain_routes.run(
            handler,
            log_message=f"Domain patch failed id={domain_id}",
            client_error="Domain patch failed",
        )

    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def delete(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            res = domain_routes.DomainAdminWriteService().delete_domain(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
                domain_id=domain_id,
            )
            return res, 200

        return domain_routes.run(
            handler,
            log_message=f"Domain delete failed id={domain_id}",
            client_error="Domain delete failed",
        )


@qf_domains_ns.route("/summary")
class DomainSummary(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self):
        def handler() -> Tuple[Any, int]:
            sample_size_raw = domain_routes.request.args.get("sample_size") or "2"
            try:
                sample_size = int(sample_size_raw)
            except ValueError as exc:
                raise domain_routes.ForgeError("sample_size must be an integer", status_code=400) from exc

            rows = domain_routes.DomainSummaryReadService().list_domain_summaries(
                workspace_id=domain_routes.workspace_id(),
                sample_size=sample_size,
            )
            return {"rows": rows}, 200

        return domain_routes.run(
            handler,
            log_message="Domain summary fetch failed",
            client_error="Domain summary fetch failed",
        )
