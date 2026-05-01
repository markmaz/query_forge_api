from __future__ import annotations

from typing import Optional

from app.exceptions.forge_error import ForgeError
from app.repositories.feedback_learning import PromptFailureAnalysisRepository, PromptFeedbackRepository, SemanticUpdateCandidateRepository
from app.schemas.feedback_learning import AnalyzeFeedbackResult
from app.services.feedback_learning.candidate_normalizer import CandidateNormalizer
from app.services.feedback_learning.candidate_writer_service import CandidateWriterService
from app.services.feedback_learning.evaluator_client import EvaluatorClient, EvaluatorClientResult
from app.services.feedback_learning.governor_service import GovernorService
from app.services.feedback_learning.prompt_artifact_bundle_service import PromptArtifactBundleService


class FailureAnalysisService:
    def __init__(
        self,
        *,
        prompt_feedback_repository: Optional[PromptFeedbackRepository] = None,
        analysis_repository: Optional[PromptFailureAnalysisRepository] = None,
        prompt_artifact_bundle_service: Optional[PromptArtifactBundleService] = None,
        evaluator_client: Optional[EvaluatorClient] = None,
        candidate_normalizer: Optional[CandidateNormalizer] = None,
        candidate_writer_service: Optional[CandidateWriterService] = None,
        governor_service: Optional[GovernorService] = None,
        candidate_repository: Optional[SemanticUpdateCandidateRepository] = None,
    ) -> None:
        self._prompt_feedback_repository = prompt_feedback_repository or PromptFeedbackRepository()
        self._analysis_repository = analysis_repository or PromptFailureAnalysisRepository()
        self._prompt_artifact_bundle_service = prompt_artifact_bundle_service or PromptArtifactBundleService()
        self._evaluator_client = evaluator_client or EvaluatorClient()
        self._candidate_normalizer = candidate_normalizer or CandidateNormalizer()
        self._candidate_writer_service = candidate_writer_service or CandidateWriterService()
        self._governor_service = governor_service or GovernorService()
        self._candidate_repository = candidate_repository or SemanticUpdateCandidateRepository()

    def analyze_feedback(self, prompt_feedback_id: int) -> AnalyzeFeedbackResult:
        feedback_id = int(prompt_feedback_id)
        if not self._prompt_feedback_repository.feedback_exists(prompt_feedback_id=feedback_id):
            raise ForgeError("Prompt feedback not found", status_code=404, details={"prompt_feedback_id": feedback_id})

        existing = self._analysis_repository.get_by_feedback_id(prompt_feedback_id=feedback_id)
        if existing is not None and str(existing.get("status") or "").strip() == "completed":
            return AnalyzeFeedbackResult.model_validate(
                {
                    "analysis_id": int(existing["id"]),
                    "status": "completed",
                    "failure_verdict": existing.get("failure_verdict"),
                    "candidate_count": 0,
                }
            )

        analysis_id = self._ensure_pending_analysis(prompt_feedback_id=feedback_id, existing=existing)
        evaluator_result: Optional[EvaluatorClientResult] = None

        try:
            bundle = self._prompt_artifact_bundle_service.build_bundle(feedback_id)
            evaluator_result = self._evaluator_client.analyze_failure_with_trace(bundle)
            analysis = evaluator_result.analysis

            self._analysis_repository.mark_completed(
                analysis_id=analysis_id,
                failure_verdict=analysis.verdict,
                confidence=analysis.confidence,
                analysis_json=analysis.model_dump(mode="json"),
                raw_llm_output=evaluator_result.raw_output,
            )

            if analysis.verdict in {"inconclusive", "no_action"} or not list(analysis.proposed_changes or []):
                return AnalyzeFeedbackResult.model_validate(
                    {
                        "analysis_id": analysis_id,
                        "status": "completed",
                        "failure_verdict": analysis.verdict,
                        "candidate_count": 0,
                    }
                )

            candidate_count = 0
            for proposed_change in analysis.proposed_changes:
                normalized = self._candidate_normalizer.normalize(
                    failure_analysis_id=analysis_id,
                    workspace_id=bundle.workspace_id,
                    proposed_change=proposed_change,
                )
                candidate = self._candidate_writer_service.upsert_candidate(normalized)
                decision = self._governor_service.evaluate_candidate(normalized)
                candidate_id = int(candidate.get("id") or 0)
                if candidate_id <= 0:
                    raise ForgeError("candidate persistence failed", status_code=500, details={"prompt_feedback_id": feedback_id})
                self._candidate_repository.update_review(
                    candidate_id=candidate_id,
                    governance_status=decision.governance_status,
                    reviewed_by=None,
                    reviewed_at=None,
                    auto_apply_eligible=decision.auto_apply_eligible,
                )
                candidate_count += 1

            return AnalyzeFeedbackResult.model_validate(
                {
                    "analysis_id": analysis_id,
                    "status": "completed",
                    "failure_verdict": analysis.verdict,
                    "candidate_count": candidate_count,
                }
            )
        except Exception as exc:
            self._analysis_repository.mark_failed(
                analysis_id=analysis_id,
                error_message=str(exc),
                raw_llm_output=(evaluator_result.raw_output if evaluator_result is not None else None),
            )
            raise

    def _ensure_pending_analysis(self, *, prompt_feedback_id: int, existing) -> int:
        if existing is not None:
            return int(existing["id"])
        try:
            return int(
                self._analysis_repository.create_pending(
                    prompt_feedback_id=prompt_feedback_id,
                    evaluator_model=_resolve_evaluator_model(self._evaluator_client),
                    evaluator_version=None,
                )
            )
        except Exception:
            race_row = self._analysis_repository.get_by_feedback_id(prompt_feedback_id=prompt_feedback_id)
            if race_row is not None:
                return int(race_row["id"])
            raise


def _resolve_evaluator_model(evaluator_client: EvaluatorClient) -> Optional[str]:
    llm_client = getattr(evaluator_client, "_llm_client", None)
    model = getattr(llm_client, "_model", None)
    if model is None:
        return None
    text = str(model).strip()
    return text or None


__all__ = ["FailureAnalysisService"]
