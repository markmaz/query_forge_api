from __future__ import annotations

import logging

from flask_restx import Namespace, Resource, fields

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.services.feedback_learning import FailureAnalysisService

logger = logging.getLogger(__name__)

feedback_learning_ns = Namespace(
    "feedback-learning",
    description="Governed feedback-learning analysis endpoints",
)

_analyze_feedback_response_model = feedback_learning_ns.model(
    "FeedbackLearningAnalyzeResponse",
    {
        "analysis_id": fields.Integer(
            required=True,
            description="Persistent prompt failure analysis id for this prompt feedback row.",
        ),
        "status": fields.String(
            required=True,
            enum=["pending", "completed", "failed"],
            description="Current analysis state. Completed responses are idempotent on rerun.",
        ),
        "failure_verdict": fields.String(
            required=False,
            description="Evaluator verdict when available. May be null for a just-created pending or failed analysis.",
        ),
        "candidate_count": fields.Integer(
            required=True,
            description="Number of normalized candidate rows processed during this synchronous analysis run.",
        ),
    },
)


@feedback_learning_ns.route("/prompt-feedback/<int:prompt_feedback_id>/analyze")
class FeedbackLearningAnalyzePromptFeedback(Resource):
    @token_required
    @require_access("ai", role="admin")
    @feedback_learning_ns.response(
        200,
        "Feedback analysis completed or reused from an existing completed row.",
        _analyze_feedback_response_model,
    )
    @feedback_learning_ns.doc(
        summary="Analyze negative prompt feedback",
        description=(
            "Synchronously runs the feedback-learning analysis pipeline for a single persisted prompt feedback row. "
            "The endpoint is idempotent: if the feedback row already has a completed analysis, the existing analysis id "
            "and status are returned without rebuilding artifacts or re-calling the evaluator. The operation requires "
            "AI feature admin access in the target workspace and does not yet mutate live semantic runtime behavior; it "
            "only persists analysis rows and normalized candidate rows for later review."
        ),
        params={
            "prompt_feedback_id": "Prompt feedback row id to analyze. Must belong to a workspace the caller can access.",
        },
        responses={
            200: "Analysis completed or existing completed analysis returned.",
            401: "Authentication required.",
            403: "Caller lacks AI feature admin access in the active workspace.",
            404: "Prompt feedback row not found.",
            422: "Required artifacts for analysis could not be reconstructed from persisted prompt feedback state.",
            500: "Unexpected analysis orchestration failure.",
        },
    )
    def post(self, prompt_feedback_id: int):
        try:
            result = FailureAnalysisService().analyze_feedback(prompt_feedback_id=int(prompt_feedback_id))
            if hasattr(result, "model_dump"):
                return result.model_dump(mode="json"), 200
            return dict(result), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("feedback learning analysis failed prompt_feedback_id=%s", prompt_feedback_id)
            return {"error": "feedback learning analysis failed"}, 500
