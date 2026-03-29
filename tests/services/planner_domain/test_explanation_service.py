"""Unit tests for app.services.planner_domain.explanation_service."""
import app.services.planner_domain.explanation_service as explanation_service_module
from app.services.planner_domain.explanation_service import ExplanationService


def test_explanation_service_can_be_constructed():
    svc = ExplanationService()
    assert svc is not None


def test_build_explanation_returns_dict_with_expected_keys():
    svc = ExplanationService()
    result = svc.build_explanation(
        selected_domain_id=1,
        plan_json={"domain_name": "Test Domain", "selects": {}, "filters": []},
        capabilities={},
        domain_candidates=[{"domain_id": 1, "name": "Test Domain"}],
        ranking_debug=[{"domain_id": 1, "score": 0.9, "vector_score": 0.85, "column_shortlist_count": 5}],
        shortlisted_columns=[],
        norm_debug={},
    )
    assert isinstance(result, dict)
    assert result is not None


def test_build_explanation_has_domain_and_summary_keys():
    svc = ExplanationService()
    result = svc.build_explanation(
        selected_domain_id=1,
        plan_json={"domain_name": "Test Domain", "selects": {}, "filters": []},
        capabilities={},
        domain_candidates=[{"domain_id": 1, "name": "Test Domain"}],
        ranking_debug=[{"domain_id": 1, "score": 0.9, "vector_score": 0.85, "column_shortlist_count": 5}],
        shortlisted_columns=[],
        norm_debug={},
    )
    assert "summary" in result
    assert "domain" in result
    assert "dimensions" in result
    assert "metrics" in result
    assert "filters" in result


def test_build_explanation_domain_name_from_plan_json():
    svc = ExplanationService()
    result = svc.build_explanation(
        selected_domain_id=1,
        plan_json={"domain_name": "My Domain", "selects": {}, "filters": []},
        capabilities={},
        domain_candidates=[],
        ranking_debug=[],
        shortlisted_columns=[],
        norm_debug={},
    )
    assert result["domain"]["selected_domain_name"] == "My Domain"


def test_build_explanation_norm_debug_country_note():
    svc = ExplanationService()
    result = svc.build_explanation(
        selected_domain_id=1,
        plan_json={"domain_name": "Domain", "selects": {}, "filters": []},
        capabilities={},
        domain_candidates=[],
        ranking_debug=[],
        shortlisted_columns=[],
        norm_debug={"country": [{"rewritten": True}]},
    )
    assert "Country" in result["summary"]


def test_build_explanation_norm_debug_school_year_note():
    svc = ExplanationService()
    result = svc.build_explanation(
        selected_domain_id=1,
        plan_json={"domain_name": "Domain", "selects": {}, "filters": []},
        capabilities={},
        domain_candidates=[],
        ranking_debug=[],
        shortlisted_columns=[],
        norm_debug={"school_year": [{"rewritten": True}]},
    )
    assert "school" in result["summary"].lower() or "year" in result["summary"].lower()


def test_build_explanation_norm_debug_empty_does_not_add_notes():
    svc = ExplanationService()
    result = svc.build_explanation(
        selected_domain_id=1,
        plan_json={"domain_name": "Domain", "selects": {}, "filters": []},
        capabilities={},
        domain_candidates=[],
        ranking_debug=[],
        shortlisted_columns=[],
        norm_debug={},
    )
    assert "Country" not in result["summary"]


def test_maybe_polish_summary_returns_reason_when_llm_missing(monkeypatch):
    monkeypatch.setattr(explanation_service_module, "QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED", True)
    svc = ExplanationService(llm_client=None)
    out, trace = svc.maybe_polish_summary(
        prompt="show me the students",
        explanation={"summary": "Fallback summary", "domain": {"selected_domain_name": "Domain"}},
    )
    assert out["summary"] == "Fallback summary"
    assert out["summary_source"] == "deterministic"
    assert trace == {"enabled": True, "used": False, "reason": "missing_llm_client"}


def test_maybe_polish_summary_uses_llm_result(monkeypatch):
    monkeypatch.setattr(explanation_service_module, "QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED", True)

    class _FakeLLM:
        def chat_json_with_trace(self, **kwargs):
            del kwargs
            return {
                "parsed": {"summary": "Friendly polished summary."},
                "content": "{\"summary\":\"Friendly polished summary.\"}",
                "finish_reason": "stop",
            }

    svc = ExplanationService(llm_client=_FakeLLM())
    out, trace = svc.maybe_polish_summary(
        prompt="show me the students",
        explanation={
            "summary": "Fallback summary",
            "domain": {"selected_domain_name": "Domain"},
            "dimensions": [{"label": "Student Name"}],
            "metrics": [],
            "filters": [],
        },
    )
    assert out["summary"] == "Friendly polished summary."
    assert out["summary_source"] == "llm"
    assert trace["enabled"] is True
    assert trace["used"] is True
