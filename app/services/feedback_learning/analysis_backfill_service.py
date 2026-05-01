from __future__ import annotations

from typing import Any, Dict, Optional

from app.repositories.feedback_learning import PromptFeedbackRepository
from app.services.feedback_learning.failure_analysis_service import FailureAnalysisService


class AnalysisBackfillService:
    def __init__(
        self,
        *,
        prompt_feedback_repository: Optional[PromptFeedbackRepository] = None,
        failure_analysis_service: Optional[FailureAnalysisService] = None,
    ) -> None:
        self._prompt_feedback_repository = (
            prompt_feedback_repository or PromptFeedbackRepository()
        )
        self._failure_analysis_service = (
            failure_analysis_service or FailureAnalysisService()
        )

    def backfill_negative_feedback(
        self,
        *,
        limit: Optional[int] = None,
        dry_run: bool = True,
        workspace_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows = self._prompt_feedback_repository.list_negative_feedback_without_analysis(
            limit=limit,
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
        )
        feedback_ids = [int(row["id"]) for row in rows]
        if dry_run:
            return {
                "dry_run": True,
                "identified_count": len(feedback_ids),
                "analyzed_count": 0,
                "feedback_ids": feedback_ids,
            }

        analyzed_count = 0
        for feedback_id in feedback_ids:
            self._failure_analysis_service.analyze_feedback(feedback_id)
            analyzed_count += 1
        return {
            "dry_run": False,
            "identified_count": len(feedback_ids),
            "analyzed_count": analyzed_count,
            "feedback_ids": feedback_ids,
        }


__all__ = ["AnalysisBackfillService"]
