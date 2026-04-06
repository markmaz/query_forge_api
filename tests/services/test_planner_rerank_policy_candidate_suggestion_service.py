from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app.exceptions.forge_error import ForgeError
import app.services.domain.planner_rerank_policy_candidate_suggestion_service as suggestion_service
from app.services.domain.planner_rerank_policy_candidate_suggestion_service import (
    PlannerRerankPolicyCandidateSuggestionService,
    _is_valid_llm_payload,
)


class _FakeSQL:
    def execute_query_mappings(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if "FROM domain" in query:
            domain_id = int((params or {}).get("domain_id") or 0)
            if domain_id == 9:
                return [{"name": "Student Enrollment And Attendance"}]
            if domain_id == 15:
                return [{"name": "Student Programs And Services"}]
        return []


class _FakePromptSignals:
    def extract_signals(self, *, prompt: str) -> List[str]:
        assert "Barksdale" in prompt
        return ["needs_school_filter", "school_literal_present", "student_listing", "status_enrolled"]


class _TimeOnlyPromptSignals:
    def extract_signals(self, *, prompt: str) -> List[str]:
        assert "December" in prompt
        return ["time_constraint_present"]


class _FakeDomainCapabilities:
    def get_domain_capabilities(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        vertical_norm: str = "generic",
    ) -> Dict[str, Any]:
        del workspace_id, user_id, vertical_norm
        if domain_id == 9:
            return {
                "dimensions": [{"column_key": "wt552.school_name"}, {"column_key": "wt570.student_name"}],
                "domain_metrics": [{"metric_key": "ENROLLMENT_COUNT"}],
            }
        return {
            "dimensions": [{"column_key": "wt590.k_student_xyear"}],
            "domain_metrics": [{"metric_key": "PROGRAM_MEMBERSHIP_COUNT"}],
        }


class _FakePlannerCapabilities:
    def resolve_capabilities(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        base_domain_id: int,
        capabilities: Dict[str, Any],
        shortlisted_columns: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        del workspace_id, vertical_norm, capabilities, shortlisted_columns
        if base_domain_id == 9:
            present = ["ENROLLMENT_STATUS", "SCHOOL_NAME", "STUDENT_IDENTITY"]
        else:
            present = ["PROGRAM_MEMBERSHIP", "STUDENT_IDENTITY"]
        return {
            "present": present,
            "records": [{"capability_key": key, "support_level": "direct", "source_type": "dimension"} for key in present],
        }


class _FakeLLM:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self.payload = payload
        self.calls: List[Dict[str, Any]] = []

    def chat_json(self, **kwargs) -> Dict[str, Any]:
        self.calls.append(dict(kwargs))
        return dict(self.payload)


class _ExplodingLLM:
    def chat_json(self, **kwargs) -> Dict[str, Any]:
        del kwargs
        raise ForgeError("Invalid model response JSON", status_code=500)


class _RuntimeErrorLLM:
    def chat_json(self, **kwargs) -> Dict[str, Any]:
        del kwargs
        raise RuntimeError("temporary llm outage")


class _AssertionErrorLLM:
    def chat_json(self, **kwargs) -> Dict[str, Any]:
        del kwargs
        raise AssertionError("unexpected llm bug")


class _FakeCandidateService:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def create_candidate(self, *, workspace_id: str, payload: Any) -> Dict[str, Any]:
        self.calls.append({"workspace_id": workspace_id, "payload": dict(payload)})
        return {
            "candidate_id": 41,
            "candidate_key": payload["candidate_key"],
            "source_type": payload["source_type"],
            "workspace_id": payload["workspace_id"],
            "vertical_norm": payload["vertical_norm"],
            "candidate_json": dict(payload["candidate_policy"]),
            "rationale_json": dict(payload["rationale_json"]),
            "confidence": payload["confidence"],
            "review_status": "pending",
            "approved_policy_id": None,
        }


def test_suggest_candidate_persists_ai_candidate() -> None:
    llm = _FakeLLM(
        {
            "candidate_key": "student_school_enrollment_bias",
            "confidence": 0.88,
            "candidate_policy": {
                "version": 1,
                "when_signals_all": ["student_listing", "school_literal_present", "status_enrolled"],
                "when_signals_any": [],
                "exclude_signals_any": [],
                "prefer_capabilities": ["SCHOOL_NAME", "STUDENT_IDENTITY", "ENROLLMENT_STATUS"],
                "penalize_missing": ["SCHOOL_NAME", "ENROLLMENT_STATUS"],
                "require_for_bonus": ["STUDENT_IDENTITY"],
                "boost": 0.2,
                "penalty": 0.25,
                "max_effect": 0.3,
            },
            "rationale": {
                "winning_domain": "Student Programs And Services",
                "expected_domain": "Student Enrollment And Attendance",
            },
        }
    )
    candidates = _FakeCandidateService()
    svc = PlannerRerankPolicyCandidateSuggestionService(
        sql=_FakeSQL(),
        prompt_signal_service=_FakePromptSignals(),
        capability_service=_FakePlannerCapabilities(),
        domain_capabilities_service=_FakeDomainCapabilities(),
        candidate_service=candidates,
        llm_client=llm,
    )

    out = svc.suggest_candidate(
        workspace_id="ws-1",
        user_id="user-1",
        payload={
            "prompt": "Show me all the students enrolled at Barksdale Elementary",
            "vertical_norm": "generic",
            "expected_base_domain_id": 9,
            "observed_base_domain_id": 15,
        },
    )

    assert out["candidate"]["candidate_id"] == 41
    assert out["candidate"]["candidate_key"] == "student_school_enrollment_bias"
    assert out["prompt_signals"] == [
        "needs_school_filter",
        "school_literal_present",
        "student_listing",
        "status_enrolled",
    ]
    persisted = candidates.calls[0]["payload"]
    assert persisted["source_type"] == "ai_recommendation"
    assert persisted["workspace_id"] == "ws-1"
    assert persisted["vertical_norm"] == "generic"
    assert persisted["candidate_policy"]["prefer_capabilities"] == [
        "SCHOOL_NAME",
        "STUDENT_IDENTITY",
        "ENROLLMENT_STATUS",
    ]
    assert persisted["rationale_json"]["observed_failure_prompt"] == "Show me all the students enrolled at Barksdale Elementary"
    assert persisted["rationale_json"]["missing_capabilities_on_observed"] == ["ENROLLMENT_STATUS", "SCHOOL_NAME"]


def test_suggest_candidate_rejects_invalid_ai_payload() -> None:
    svc = PlannerRerankPolicyCandidateSuggestionService(
        sql=_FakeSQL(),
        prompt_signal_service=_FakePromptSignals(),
        capability_service=_FakePlannerCapabilities(),
        domain_capabilities_service=_FakeDomainCapabilities(),
        candidate_service=_FakeCandidateService(),
        llm_client=_FakeLLM({"candidate_key": "bad", "rationale": {}}),
    )

    out = svc.suggest_candidate(
        workspace_id="ws-1",
        user_id="user-1",
        payload={
            "prompt": "Show me all the students enrolled at Barksdale Elementary",
            "expected_base_domain_id": 9,
        },
    )

    assert out["candidate"]["source_type"] == "trace_review"
    assert out["generation_mode"] == "fallback_heuristic"
    assert out["candidate"]["candidate_json"]["when_signals_all"] == [
        "needs_school_filter",
        "school_literal_present",
        "student_listing",
    ][: len(out["candidate"]["candidate_json"]["when_signals_all"])]


def test_suggest_candidate_falls_back_when_llm_response_is_invalid_json() -> None:
    svc = PlannerRerankPolicyCandidateSuggestionService(
        sql=_FakeSQL(),
        prompt_signal_service=_FakePromptSignals(),
        capability_service=_FakePlannerCapabilities(),
        domain_capabilities_service=_FakeDomainCapabilities(),
        candidate_service=_FakeCandidateService(),
        llm_client=_ExplodingLLM(),
    )

    out = svc.suggest_candidate(
        workspace_id="ws-1",
        user_id="user-1",
        payload={
            "prompt": "Show me all the students enrolled at Barksdale Elementary",
            "expected_base_domain_id": 9,
            "observed_base_domain_id": 15,
        },
    )

    assert out["candidate"]["source_type"] == "trace_review"
    assert out["candidate"]["review_status"] == "pending"
    assert out["generation_mode"] == "fallback_heuristic"
    assert out["candidate"]["rationale_json"]["fallback_reason"] == "llm_response_invalid_or_unavailable"


def test_suggest_candidate_rejects_time_only_prompt_without_capability_grounding() -> None:
    svc = PlannerRerankPolicyCandidateSuggestionService(
        sql=_FakeSQL(),
        prompt_signal_service=_TimeOnlyPromptSignals(),
        capability_service=_FakePlannerCapabilities(),
        domain_capabilities_service=_FakeDomainCapabilities(),
        candidate_service=_FakeCandidateService(),
        llm_client=_ExplodingLLM(),
    )

    with pytest.raises(ForgeError) as exc_info:
        svc.suggest_candidate(
            workspace_id="ws-1",
            user_id="user-1",
            payload={
                "prompt": "How many days off are there in December?",
                "expected_base_domain_id": 9,
                "vertical_norm": "education",
            },
        )

    assert exc_info.value.status_code == 422
    assert "capability-grounded suggestion" in str(exc_info.value)


def test_suggest_candidate_falls_back_on_expected_runtime_llm_errors() -> None:
    svc = PlannerRerankPolicyCandidateSuggestionService(
        sql=_FakeSQL(),
        prompt_signal_service=_FakePromptSignals(),
        capability_service=_FakePlannerCapabilities(),
        domain_capabilities_service=_FakeDomainCapabilities(),
        candidate_service=_FakeCandidateService(),
        llm_client=_RuntimeErrorLLM(),
    )

    out = svc.suggest_candidate(
        workspace_id="ws-1",
        user_id="user-1",
        payload={
            "prompt": "Show me all the students enrolled at Barksdale Elementary",
            "expected_base_domain_id": 9,
            "observed_base_domain_id": 15,
        },
    )

    assert out["candidate"]["source_type"] == "trace_review"
    assert out["generation_mode"] == "fallback_heuristic"


def test_suggest_candidate_surfaces_unexpected_llm_errors() -> None:
    svc = PlannerRerankPolicyCandidateSuggestionService(
        sql=_FakeSQL(),
        prompt_signal_service=_FakePromptSignals(),
        capability_service=_FakePlannerCapabilities(),
        domain_capabilities_service=_FakeDomainCapabilities(),
        candidate_service=_FakeCandidateService(),
        llm_client=_AssertionErrorLLM(),
    )

    with pytest.raises(AssertionError, match="unexpected llm bug"):
        svc.suggest_candidate(
            workspace_id="ws-1",
            user_id="user-1",
            payload={
                "prompt": "Show me all the students enrolled at Barksdale Elementary",
                "expected_base_domain_id": 9,
                "observed_base_domain_id": 15,
            },
        )


def test_is_valid_llm_payload_surfaces_unexpected_validation_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_payload):
        raise AssertionError("unexpected validation bug")

    monkeypatch.setattr(
        suggestion_service.PlannerRerankPolicyCandidateSuggestionLLMResponse,
        "model_validate",
        _boom,
    )

    with pytest.raises(AssertionError, match="unexpected validation bug"):
        _is_valid_llm_payload({})
