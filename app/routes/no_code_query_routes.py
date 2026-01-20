# app/routes/nocode_query_routes.py
from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace, Resource

from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.routes._route_utils import get_workspace_id_from_header, int_arg
from app.services.domain_resolver import DomainResolver
from app.services.exports.export_policy import build_export_policy, make_rowcount_signature, set_cached_rowcount
from app.services.no_code_query_service import NoCodeQueryService
from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder

logger = logging.getLogger(__name__)
nocode_ns = Namespace("query", description="No code query")

def _handle_service_error(e: ServiceError):
    return {"error": str(e)}, getattr(e, "status_code", 400) or 400

@nocode_ns.route("/")
class NoCodeRun(Resource):
    @token_required
    def post(self):
        try:
            workspace_id = get_workspace_id_from_header()

            mode = (request.args.get("mode") or "preview").strip().lower()
            limit = int_arg("limit", 200)
            offset = int_arg("offset", 0)

            raw = request.get_json(silent=True) or {}
            if not isinstance(raw, dict):
                raise ServiceError("Invalid JSON body", status_code=400)

            ctx = WorkspaceContextBuilder().build(workspace_id)
            domain_resolver = DomainResolver(workspace_id=workspace_id)

            svc = NoCodeQueryService(executor=ctx.sql_exec, domain_resolver=domain_resolver)
            out = svc.run(raw_query=raw, mode=mode, limit=limit, offset=offset)
            signature = make_rowcount_signature(out.sql, out.params)
            set_cached_rowcount(signature, out.total)

            return {
                "sql": out.sql,
                "sqlRendered": out.sql_rendered,
                "params": out.params,
                "rows": out.rows,
                "columns": out.columns,
                "total": out.total,
                "totalRowCount": out.total,
                "export": build_export_policy(out.total),
                "rowCountSignature": signature,
                "limit": out.limit,
                "offset": out.offset,
            }, 200

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("No-code query run failed")
            return {"error": "No-code query run failed"}, 500
