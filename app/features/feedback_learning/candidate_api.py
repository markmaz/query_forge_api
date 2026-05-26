from __future__ import annotations

import logging
from typing import Any, Dict

from flask import g, request
from flask_restx import Resource, fields
from pydantic import ValidationError

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.services.feedback_learning import CandidateReviewService

from .analysis_api import feedback_learning_ns
from .schemas import CandidateBulkDecisionRequest, CandidateRejectRequest

logger = logging.getLogger(__name__)


def _reviewed_by() -> str:
    return str(getattr(g, "user_id", "") or "").strip() or "unknown"

_candidate_row_model = feedback_learning_ns.model(
    "FeedbackLearningCandidateRow",
    {
        "id": fields.Integer(required=True),
        "failure_analysis_id": fields.Integer(required=True),
        "target_type": fields.String(required=True),
        "concept_key": fields.String(required=False),
        "domain_key": fields.String(required=False),
        "change_type": fields.String(required=True),
        "payload_json": fields.Raw(required=True),
        "payload_hash": fields.String(required=True),
        "risk_level": fields.String(required=True),
        "evidence_count": fields.Integer(required=True),
        "confidence": fields.Float(required=True),
        "governance_status": fields.String(required=True),
        "auto_apply_eligible": fields.Boolean(required=True),
        "governance_reason_code": fields.String(required=False),
        "review_notes": fields.String(required=False),
        "workspace_id": fields.String(required=False),
        "source_scope": fields.String(required=True),
        "workspace_scope_key": fields.String(required=True),
    },
)

_analysis_summary_model = feedback_learning_ns.model(
    "FeedbackLearningAnalysisSummary",
    {
        "analysis_id": fields.Integer(required=False),
        "prompt_feedback_id": fields.Integer(required=False),
        "status": fields.String(required=False),
        "failure_verdict": fields.String(required=False),
        "confidence": fields.Float(required=False),
        "analysis_json": fields.Raw(required=False),
    },
)

_feedback_summary_model = feedback_learning_ns.model(
    "FeedbackLearningSourceFeedbackSummary",
    {
        "prompt_feedback_id": fields.Integer(required=False),
        "workspace_id": fields.String(required=False),
        "user_id": fields.String(required=False),
        "vote": fields.String(required=False),
        "normalized_prompt": fields.String(required=False),
        "prompt_text": fields.String(required=False),
    },
)

_candidate_list_response_model = feedback_learning_ns.model(
    "FeedbackLearningCandidateListResponse",
    {
        "rows": fields.List(fields.Raw, required=True),
        "total": fields.Integer(required=True),
        "page": fields.Integer(required=True),
        "page_size": fields.Integer(required=True),
    },
)

_candidate_detail_response_model = feedback_learning_ns.model(
    "FeedbackLearningCandidateDetailResponse",
    {
        "candidate": fields.Nested(_candidate_row_model, required=True),
        "analysis_summary": fields.Nested(_analysis_summary_model, required=False),
        "source_feedback": fields.Nested(_feedback_summary_model, required=False),
        "effective_target_key": fields.String(required=False),
    },
)

_candidate_decision_response_model = feedback_learning_ns.model(
    "FeedbackLearningCandidateDecisionResponse",
    {
        "candidate": fields.Nested(_candidate_row_model, required=True),
        "candidate_status": fields.String(required=False),
        "override": fields.Raw(required=False),
    },
)

_bulk_decision_response_model = feedback_learning_ns.model(
    "FeedbackLearningBulkDecisionResponse",
    {
        "processed": fields.Integer(required=True),
        "results": fields.List(fields.Raw, required=True),
    },
)

_candidate_reject_request_model = feedback_learning_ns.model(
    "FeedbackLearningCandidateRejectRequest",
    {"reason": fields.String(required=True, description="Required reviewer rejection reason stored with the candidate review metadata.")},
)

_candidate_bulk_request_model = feedback_learning_ns.model(
    "FeedbackLearningCandidateBulkDecisionRequest",
    {
        "candidate_ids": fields.List(fields.Integer, required=True, description="Candidate ids to process in this bulk review action."),
        "reason": fields.String(required=False, description="Required for bulk reject. Ignored for bulk approve."),
    },
)


@feedback_learning_ns.route("/candidates")
class FeedbackLearningCandidates(Resource):
    @token_required
    @require_access("ai", role="admin")
    @feedback_learning_ns.response(200, "Candidate page.", _candidate_list_response_model)
    @feedback_learning_ns.doc(
        summary="List feedback-learning candidates",
        description=(
            "Returns a filtered page of feedback-learning candidates enriched with source feedback and analysis summaries. "
            "This is the primary reviewer list endpoint for the admin UI. Results are sorted by creation time descending. "
            "In v1 this surface is admin-only because analysis payloads can contain sensitive prompt context."
        ),
        params={
            "governance_status": "Optional governance status filter.",
            "risk_level": "Optional risk level filter.",
            "target_type": "Optional target type filter.",
            "workspace_id": "Optional workspace filter. Defaults to the active workspace header.",
            "change_type": "Optional change type filter.",
            "concept_key": "Optional semantic concept key filter.",
            "domain_key": "Optional domain key filter.",
            "page": "1-based page number. Defaults to 1.",
            "page_size": "Page size. Defaults to 50, maximum 200.",
        },
    )
    def get(self):
        try:
            page = CandidateReviewService().list_candidates(
                governance_status=request.args.get("governance_status"),
                risk_level=request.args.get("risk_level"),
                target_type=request.args.get("target_type"),
                workspace_id=request.args.get("workspace_id") or request.headers.get("X-Workspace-Id"),
                change_type=request.args.get("change_type"),
                concept_key=request.args.get("concept_key"),
                domain_key=request.args.get("domain_key"),
                page=int(request.args.get("page") or 1),
                page_size=int(request.args.get("page_size") or 50),
            )
            return page, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@feedback_learning_ns.route("/candidates/<int:candidate_id>")
class FeedbackLearningCandidateDetail(Resource):
    @token_required
    @require_access("ai", role="admin")
    @feedback_learning_ns.response(200, "Candidate detail.", _candidate_detail_response_model)
    @feedback_learning_ns.doc(
        summary="Get feedback-learning candidate detail",
        description="Returns the candidate payload plus the related analysis summary, source feedback summary, and effective target key for reviewer inspection.",
    )
    def get(self, candidate_id: int):
        try:
            return CandidateReviewService().get_candidate_detail(candidate_id=int(candidate_id)), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@feedback_learning_ns.route("/candidates/<int:candidate_id>/approve")
class FeedbackLearningCandidateApprove(Resource):
    @token_required
    @require_access("ai", role="admin")
    @feedback_learning_ns.response(200, "Candidate approved.", _candidate_decision_response_model)
    @feedback_learning_ns.doc(
        summary="Approve a feedback-learning candidate",
        description=(
            "Approves a supported candidate and persists the corresponding semantic or domain override row. "
            "Review-only target types are rejected with an explicit unsupported-target response instead of being silently approved."
        ),
    )
    def post(self, candidate_id: int):
        try:
            return CandidateReviewService().approve_candidate(
                candidate_id=int(candidate_id),
                reviewed_by=_reviewed_by(),
            ), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@feedback_learning_ns.route("/candidates/<int:candidate_id>/reject")
class FeedbackLearningCandidateReject(Resource):
    @token_required
    @require_access("ai", role="admin")
    @feedback_learning_ns.expect(_candidate_reject_request_model, validate=False)
    @feedback_learning_ns.response(200, "Candidate rejected.", _candidate_decision_response_model)
    @feedback_learning_ns.doc(
        summary="Reject a feedback-learning candidate",
        description="Rejects a candidate and records the required reviewer rejection reason in candidate review metadata.",
    )
    def post(self, candidate_id: int):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            parsed = CandidateRejectRequest.model_validate(body)
            return CandidateReviewService().reject_candidate(
                candidate_id=int(candidate_id),
                reviewed_by=_reviewed_by(),
                reason=parsed.reason,
            ), 200
        except ValidationError as exc:
            return {"error": "Invalid request", "details": exc.errors(include_url=False, include_context=False, include_input=False)}, 400
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@feedback_learning_ns.route("/candidates/bulk-approve")
class FeedbackLearningCandidateBulkApprove(Resource):
    @token_required
    @require_access("ai", role="admin")
    @feedback_learning_ns.expect(_candidate_bulk_request_model, validate=False)
    @feedback_learning_ns.response(200, "Bulk approval processed.", _bulk_decision_response_model)
    @feedback_learning_ns.doc(
        summary="Bulk-approve feedback-learning candidates",
        description="Applies approval to each listed candidate id and returns a per-item result payload.",
    )
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            parsed = CandidateBulkDecisionRequest.model_validate(body)
            return CandidateReviewService().bulk_approve(
                candidate_ids=parsed.candidate_ids,
                reviewed_by=_reviewed_by(),
            ), 200
        except ValidationError as exc:
            return {"error": "Invalid request", "details": exc.errors(include_url=False, include_context=False, include_input=False)}, 400
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@feedback_learning_ns.route("/candidates/bulk-reject")
class FeedbackLearningCandidateBulkReject(Resource):
    @token_required
    @require_access("ai", role="admin")
    @feedback_learning_ns.expect(_candidate_bulk_request_model, validate=False)
    @feedback_learning_ns.response(200, "Bulk rejection processed.", _bulk_decision_response_model)
    @feedback_learning_ns.doc(
        summary="Bulk-reject feedback-learning candidates",
        description="Rejects each listed candidate id using the same required reviewer reason.",
    )
    def post(self):
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            parsed = CandidateBulkDecisionRequest.model_validate(body)
            if not parsed.reason:
                raise ForgeError("reason is required", status_code=400)
            return CandidateReviewService().bulk_reject(
                candidate_ids=parsed.candidate_ids,
                reviewed_by=_reviewed_by(),
                reason=parsed.reason,
            ), 200
        except ValidationError as exc:
            return {"error": "Invalid request", "details": exc.errors(include_url=False, include_context=False, include_input=False)}, 400
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
