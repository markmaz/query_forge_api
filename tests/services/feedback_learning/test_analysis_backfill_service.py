from __future__ import annotations

from app.services.feedback_learning.analysis_backfill_service import AnalysisBackfillService


class _PromptFeedbackRepository:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def list_negative_feedback_without_analysis(self, *, limit=None, workspace_id=None, date_from=None, date_to=None):
        self.calls.append(
            {
                "limit": limit,
                "workspace_id": workspace_id,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
        return list(self.rows)


class _FailureAnalysisService:
    def __init__(self):
        self.calls = []

    def analyze_feedback(self, prompt_feedback_id: int):
        self.calls.append(prompt_feedback_id)
        return {
            "analysis_id": prompt_feedback_id + 1000,
            "status": "completed",
        }


def test_analysis_backfill_service_dry_run_only_identifies_rows() -> None:
    repo = _PromptFeedbackRepository(
        [
            {"id": 4, "workspace_id": "ws-1"},
            {"id": 9, "workspace_id": "ws-1"},
        ]
    )
    analysis = _FailureAnalysisService()
    service = AnalysisBackfillService(
        prompt_feedback_repository=repo,
        failure_analysis_service=analysis,
    )

    result = service.backfill_negative_feedback(
        limit=25,
        dry_run=True,
        workspace_id="ws-1",
        date_from="2026-04-01",
        date_to="2026-04-30",
    )

    assert result == {
        "dry_run": True,
        "identified_count": 2,
        "analyzed_count": 0,
        "feedback_ids": [4, 9],
    }
    assert analysis.calls == []


def test_analysis_backfill_service_live_mode_analyzes_each_feedback_row() -> None:
    repo = _PromptFeedbackRepository(
        [
            {"id": 4, "workspace_id": "ws-1"},
            {"id": 9, "workspace_id": "ws-1"},
        ]
    )
    analysis = _FailureAnalysisService()
    service = AnalysisBackfillService(
        prompt_feedback_repository=repo,
        failure_analysis_service=analysis,
    )

    result = service.backfill_negative_feedback(limit=10, dry_run=False)

    assert result == {
        "dry_run": False,
        "identified_count": 2,
        "analyzed_count": 2,
        "feedback_ids": [4, 9],
    }
    assert analysis.calls == [4, 9]

