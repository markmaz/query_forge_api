from __future__ import annotations

from flask import g, request
from flask_restx import Resource, fields

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.services.feedback_learning import CandidateReviewService

from .analysis_api import feedback_learning_ns


def _reviewed_by() -> str:
    return str(getattr(g, "user_id", "") or "").strip() or "unknown"

_override_row_model = feedback_learning_ns.model(
    "FeedbackLearningOverrideRow",
    {
        "id": fields.Integer(required=True),
        "status": fields.String(required=True),
        "workspace_id": fields.String(required=False),
        "concept_key": fields.String(required=False),
        "domain_key": fields.String(required=False),
        "override_type": fields.String(required=False),
        "override_key": fields.String(required=False),
        "override_value_json": fields.Raw(required=False),
        "approved_by": fields.String(required=False),
    },
)

_override_list_response_model = feedback_learning_ns.model(
    "FeedbackLearningOverrideListResponse",
    {"rows": fields.List(fields.Nested(_override_row_model), required=True)},
)

_promotion_audit_list_response_model = feedback_learning_ns.model(
    "FeedbackLearningPromotionAuditListResponse",
    {
        "rows": fields.List(fields.Raw, required=True),
        "total": fields.Integer(required=True),
        "limit": fields.Integer(required=True),
        "offset": fields.Integer(required=True),
    },
)


@feedback_learning_ns.route("/semantic-overrides")
class FeedbackLearningSemanticOverrides(Resource):
    @token_required
    @require_access("ai", role="admin")
    @feedback_learning_ns.response(200, "Active semantic overrides.", _override_list_response_model)
    @feedback_learning_ns.doc(
        summary="List active semantic overrides",
        description="Returns active semantic override rows for the active workspace. This is the reviewer-facing override visibility surface before runtime override resolution is enabled.",
    )
    def get(self):
        try:
            workspace_id = str(request.args.get("workspace_id") or request.headers.get("X-Workspace-Id") or "").strip()
            return {"rows": CandidateReviewService().list_semantic_overrides(workspace_id=workspace_id)}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@feedback_learning_ns.route("/domain-overrides")
class FeedbackLearningDomainOverrides(Resource):
    @token_required
    @require_access("ai", role="admin")
    @feedback_learning_ns.response(200, "Active domain overrides.", _override_list_response_model)
    @feedback_learning_ns.doc(
        summary="List active domain overrides",
        description="Returns active domain override rows for the active workspace.",
    )
    def get(self):
        try:
            workspace_id = str(request.args.get("workspace_id") or request.headers.get("X-Workspace-Id") or "").strip()
            return {"rows": CandidateReviewService().list_domain_overrides(workspace_id=workspace_id)}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@feedback_learning_ns.route("/semantic-overrides/<int:override_id>/deactivate")
class FeedbackLearningSemanticOverrideDeactivate(Resource):
    @token_required
    @require_access("ai", role="admin")
    @feedback_learning_ns.response(200, "Semantic override deactivated.", _override_row_model)
    @feedback_learning_ns.doc(
        summary="Deactivate a semantic override",
        description="Marks the selected semantic override inactive. The override row remains for audit and future promotion visibility.",
    )
    def post(self, override_id: int):
        try:
            return CandidateReviewService().deactivate_semantic_override(
                override_id=int(override_id),
                reviewed_by=_reviewed_by(),
            ), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@feedback_learning_ns.route("/domain-overrides/<int:override_id>/deactivate")
class FeedbackLearningDomainOverrideDeactivate(Resource):
    @token_required
    @require_access("ai", role="admin")
    @feedback_learning_ns.response(200, "Domain override deactivated.", _override_row_model)
    @feedback_learning_ns.doc(
        summary="Deactivate a domain override",
        description="Marks the selected domain override inactive. The override row remains persisted for review and promotion audit context.",
    )
    def post(self, override_id: int):
        try:
            return CandidateReviewService().deactivate_domain_override(
                override_id=int(override_id),
                reviewed_by=_reviewed_by(),
            ), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@feedback_learning_ns.route("/promotion-audits")
class FeedbackLearningPromotionAudits(Resource):
    @token_required
    @require_access("ai", role="admin")
    @feedback_learning_ns.response(200, "Promotion audit page.", _promotion_audit_list_response_model)
    @feedback_learning_ns.doc(
        summary="List catalog promotion audits",
        description="Returns recent promotion audit rows so reviewer/admin users can inspect override-to-curated-catalog promotion history.",
        params={
            "source_type": "Optional source type filter.",
            "promotion_status": "Optional promotion status filter.",
            "limit": "Page size. Defaults to 50, maximum 200.",
            "offset": "Offset for pagination. Defaults to 0.",
        },
    )
    def get(self):
        try:
            return CandidateReviewService().list_promotion_audits(
                source_type=request.args.get("source_type"),
                promotion_status=request.args.get("promotion_status"),
                limit=int(request.args.get("limit") or 50),
                offset=int(request.args.get("offset") or 0),
            ), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
