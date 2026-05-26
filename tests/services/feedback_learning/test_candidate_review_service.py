from __future__ import annotations

from app.exceptions.forge_error import ForgeError
from app.services.feedback_learning.candidate_review_service import CandidateReviewService


class _CandidateRepository:
    def __init__(self, *, row=None, page=None):
        self.row = row
        self.page = page or {"rows": [], "total": 0, "page": 1, "page_size": 50}
        self.list_calls = []
        self.get_calls = []
        self.update_calls = []

    def list_candidates(self, **kwargs):
        self.list_calls.append(kwargs)
        return self.page

    def get_by_id(self, *, candidate_id: int):
        self.get_calls.append(candidate_id)
        return self.row

    def update_review(self, *, candidate_id: int, governance_status: str, reviewed_by=None, reviewed_at=None, auto_apply_eligible=None, governance_reason_code=None, review_notes=None):
        self.update_calls.append(
            {
                "candidate_id": candidate_id,
                "governance_status": governance_status,
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at,
                "auto_apply_eligible": auto_apply_eligible,
                "governance_reason_code": governance_reason_code,
                "review_notes": review_notes,
            }
        )
        return 1


class _AnalysisRepository:
    def __init__(self, row=None):
        self.row = row or {
            "id": 55,
            "prompt_feedback_id": 41,
            "status": "completed",
            "failure_verdict": "domain_error",
            "confidence": 0.91,
            "analysis_json": {"verdict": "domain_error"},
        }
        self.calls = []

    def get_by_id(self, *, analysis_id: int):
        self.calls.append(analysis_id)
        return self.row


class _PromptFeedbackRepository:
    def __init__(self, row=None):
        self.row = row or {
            "id": 41,
            "workspace_id": "ws-1",
            "user_id": "user-1",
            "vote": "down",
            "normalized_prompt": "show attendance exceptions",
            "prompt_text": "Show attendance exceptions",
        }
        self.calls = []

    def get_feedback(self, *, prompt_feedback_id: int):
        self.calls.append(prompt_feedback_id)
        return self.row


class _OverrideManagerService:
    def __init__(self, result=None):
        self.result = result or {"candidate_status": "approved", "override": {"id": 21}}
        self.calls = []

    def apply_candidate(self, candidate, approved_by=None):
        self.calls.append({"candidate": candidate, "approved_by": approved_by})
        return self.result


def _candidate_row():
    return {
        "id": 88,
        "failure_analysis_id": 55,
        "target_type": "semantic_override",
        "concept_key": "student_name",
        "domain_key": None,
        "change_type": "add_alias",
        "payload_json": {"alias_key": "preferred_name", "match_kind": "exact", "aliases": ["Preferred Name"]},
        "payload_hash": "hash-55",
        "risk_level": "low",
        "evidence_count": 3,
        "confidence": 0.95,
        "governance_status": "pending",
        "auto_apply_eligible": True,
        "source_scope": "workspace",
        "workspace_id": "ws-1",
        "workspace_scope_key": "workspace:ws-1",
        "governance_reason_code": "AUTO_APPLY_ELIGIBLE",
        "review_notes": None,
    }


def test_candidate_review_service_list_candidates_enriches_rows() -> None:
    repository = _CandidateRepository(page={"rows": [_candidate_row()], "total": 1, "page": 1, "page_size": 50})
    service = CandidateReviewService(
        candidate_repository=repository,
        analysis_repository=_AnalysisRepository(),
        prompt_feedback_repository=_PromptFeedbackRepository(),
        override_manager_service=_OverrideManagerService(),
    )

    page = service.list_candidates(workspace_id="ws-1")

    assert page["total"] == 1
    assert page["rows"][0]["analysis_summary"]["failure_verdict"] == "domain_error"
    assert page["rows"][0]["source_feedback"]["prompt_feedback_id"] == 41


def test_candidate_review_service_approve_candidate_delegates_to_override_manager() -> None:
    override_manager = _OverrideManagerService()
    service = CandidateReviewService(
        candidate_repository=_CandidateRepository(row=_candidate_row()),
        analysis_repository=_AnalysisRepository(),
        prompt_feedback_repository=_PromptFeedbackRepository(),
        override_manager_service=override_manager,
    )

    result = service.approve_candidate(candidate_id=88, reviewed_by="admin-1")

    assert result["candidate"]["id"] == 88
    assert result["candidate_status"] == "approved"
    assert override_manager.calls[0]["approved_by"] == "admin-1"


def test_candidate_review_service_reject_requires_reason() -> None:
    service = CandidateReviewService(
        candidate_repository=_CandidateRepository(row=_candidate_row()),
        analysis_repository=_AnalysisRepository(),
        prompt_feedback_repository=_PromptFeedbackRepository(),
        override_manager_service=_OverrideManagerService(),
    )

    try:
        service.reject_candidate(candidate_id=88, reviewed_by="admin-1", reason=" ")
        assert False, "expected rejection reason failure"
    except ForgeError as exc:
        assert exc.status_code == 400


def test_candidate_review_service_reject_updates_candidate_review_fields() -> None:
    repository = _CandidateRepository(row=_candidate_row())
    service = CandidateReviewService(
        candidate_repository=repository,
        analysis_repository=_AnalysisRepository(),
        prompt_feedback_repository=_PromptFeedbackRepository(),
        override_manager_service=_OverrideManagerService(),
    )

    result = service.reject_candidate(candidate_id=88, reviewed_by="admin-1", reason="Alias should not be applied")

    assert result["candidate"]["id"] == 88
    assert repository.update_calls[0]["governance_status"] == "rejected"
    assert repository.update_calls[0]["review_notes"] == "Alias should not be applied"
