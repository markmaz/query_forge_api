from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.routes.common import _service, _workspace_id, flowforge_ns, models


@flowforge_ns.route("/reports/domains")
class FlowForgeReportingDomainList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge reporting domains",
        description=(
            "Returns the governed FlowForge reporting domain catalog for QueryForge-native reporting and Query "
            "Studio semantic registration. Each domain names its redacted read model, default production-mode "
            "filter, metrics, dimensions, sensitive fields excluded from default NL/query use, and starter Query "
            "Studio prompts. The catalog intentionally describes workspace-scoped read models rather than raw "
            "provider payloads."
        ),
        responses={200: "Reporting domains returned.", 401: "Authentication required.", 403: "FlowForge access required."},
    )
    @flowforge_ns.marshal_list_with(models["reporting_domain"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self):
        try:
            return _service().list_reporting_domains(workspace_id=_workspace_id()), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/reports/summary")
class FlowForgeReportSummary(Resource):
    @flowforge_ns.doc(
        summary="Get FlowForge operational report summary",
        description=(
            "Returns workspace-scoped run summary metrics for the reports dashboard and future semantic read "
            "model registration. The default mode is production so test-mode records are excluded unless "
            "mode=test is explicitly requested."
        ),
        params={"mode": "Optional mode filter. Supported values today are production and test."},
        responses={200: "Report summary returned.", 401: "Authentication required.", 403: "FlowForge access required."},
    )
    @flowforge_ns.marshal_with(models["report_summary"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self):
        try:
            return (
                _service().get_report_summary(
                    workspace_id=_workspace_id(),
                    mode=request.args.get("mode"),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/reports/dashboard")
class FlowForgeReportDashboard(Resource):
    @flowforge_ns.doc(
        summary="Get FlowForge reporting dashboard data",
        description=(
            "Returns production-default operational metrics across FlowForge read models, plus the governed "
            "semantic domain catalog used for Query Studio handoff. Sensitive fields such as raw intake payloads, "
            "headers, recipient addresses, signed token data, and provider payload summaries are excluded from "
            "the default read-model contract."
        ),
        params={"mode": "Optional mode filter. Defaults to production; pass mode=test for test-mode reporting."},
        responses={200: "Report dashboard returned.", 401: "Authentication required.", 403: "FlowForge access required."},
    )
    @flowforge_ns.marshal_with(models["report_dashboard"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self):
        try:
            return (
                _service().get_report_dashboard(
                    workspace_id=_workspace_id(),
                    mode=request.args.get("mode"),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
