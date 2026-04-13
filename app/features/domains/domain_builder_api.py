from __future__ import annotations

from typing import Any, Tuple

from flask_restx import Resource

from app.features.domains import shared as domain_routes
from app.features.domains.common import qf_domains_ns


@qf_domains_ns.route("/columns")
class BuilderColumns(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self):
        def handler() -> Tuple[Any, int]:
            domain_id_raw = domain_routes.request.args.get("domain_id")
            domain_id = int(domain_id_raw) if (domain_id_raw or "").strip() else None

            payload = domain_routes.BuilderColumnFeedService().list_available_columns(
                domain_routes.BuilderFeedQuery(
                    workspace_id=domain_routes.workspace_id(),
                    user_id=domain_routes.require_user_id(),
                    domain_id=domain_id,
                    table_q=(domain_routes.request.args.get("table_q") or "").strip() or None,
                    column_q=(domain_routes.request.args.get("column_q") or "").strip() or None,
                    variant_code=(domain_routes.request.args.get("variant_code") or "").strip() or None,
                    only_qe=domain_routes.bool_arg("only_qe", default=None),
                    limit=domain_routes.int_arg("limit", default=2000),
                    offset=domain_routes.int_arg("offset", default=0),
                )
            )
            return payload, 200

        return domain_routes.run(handler)
