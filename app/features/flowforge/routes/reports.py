from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.routes.common import _actor_user_id, _int_query_arg, _service, _workspace_id, flowforge_ns, models


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


@flowforge_ns.route("/reports/domains/sync/dry-run")
class FlowForgeReportingDomainSyncDryRun(Resource):
    @flowforge_ns.doc(
        summary="Dry-run FlowForge reporting domain sync",
        description=(
            "Validates the FlowForge Workflow Intelligence reporting manifest against the expected redacted "
            "read-model SQL without writing QueryForge semantic metadata. Admins can use this endpoint to "
            "detect pending migrations, missing read models, or sensitive-field drift before running a sync."
        ),
        responses={200: "Reporting domain sync dry-run completed.", 401: "Authentication required.", 403: "FlowForge admin access required."},
    )
    @flowforge_ns.marshal_with(models["reporting_domain_sync"])
    @token_required
    @require_access("flowforge", role="admin")
    def post(self):
        try:
            return (
                _service().dry_run_reporting_domain_sync(
                    workspace_id=_workspace_id(),
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/reports/domains/sync")
class FlowForgeReportingDomainSync(Resource):
    @flowforge_ns.doc(
        summary="Sync FlowForge reporting domains",
        description=(
            "Registers or updates system-managed FlowForge Workflow Intelligence domains for the active "
            "workspace after validating the manifest and redacted read models. The sync is designed to be "
            "idempotent and admin-triggered for recovery after migrations or semantic catalog drift."
        ),
        responses={200: "Reporting domain sync completed.", 401: "Authentication required.", 403: "FlowForge admin access required."},
    )
    @flowforge_ns.marshal_with(models["reporting_domain_sync"])
    @token_required
    @require_access("flowforge", role="admin")
    def post(self):
        try:
            return (
                _service().sync_reporting_domains(
                    workspace_id=_workspace_id(),
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
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


@flowforge_ns.route("/reports/intake-review")
class FlowForgeIntakeReviewTimeline(Resource):
    @flowforge_ns.doc(
        summary="Get rolling FlowForge intake review timeline",
        description=(
            "Returns a rolling day-by-day intake count with per-intake acceptance outcomes for operator review. "
            "The timeline remains redacted: raw intake forms are not included and must be fetched through the "
            "separate raw-form review endpoint."
        ),
        params={
            "mode": "Optional mode filter. Defaults to production; pass mode=test for test-mode reporting.",
            "days": "Rolling window size from 1 to 31 days. Defaults to 7.",
        },
        responses={200: "Intake review timeline returned.", 401: "Authentication required.", 403: "FlowForge access required."},
    )
    @flowforge_ns.marshal_with(models["intake_review_timeline"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self):
        try:
            return (
                _service().get_intake_review_timeline(
                    workspace_id=_workspace_id(),
                    mode=request.args.get("mode"),
                    days=_int_query_arg("days", 7),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/reports/intake-review/<int:intake_event_id>/raw")
class FlowForgeIntakeRawForm(Resource):
    @flowforge_ns.doc(
        summary="Get a raw FlowForge intake form for review",
        description=(
            "Returns the retained raw and normalized intake form for a workspace-scoped intake event. This endpoint "
            "is intentionally separate from the default reporting dashboard because raw forms can contain sensitive "
            "patient information and are only available to FlowForge operators or admins."
        ),
        responses={
            200: "Raw intake form returned.",
            401: "Authentication required.",
            403: "FlowForge operator access required.",
            404: "Intake event not found.",
        },
    )
    @flowforge_ns.marshal_with(models["intake_raw_form"])
    @token_required
    @require_access("flowforge", role="operator")
    def get(self, intake_event_id: int):
        try:
            return (
                _service().get_intake_raw_form(
                    workspace_id=_workspace_id(),
                    intake_event_id=intake_event_id,
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
