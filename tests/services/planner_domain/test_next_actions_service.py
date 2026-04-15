"""Unit tests for app.services.planner_domain.next_actions_service."""
import pytest

from app.exceptions.forge_error import ForgeError
from app.services.planner_domain.next_actions_service import (
    NextActionsService,
    _normalize_next_actions,
)


def test_next_actions_service_can_be_constructed():
    svc = NextActionsService()
    assert svc is not None


def test_next_actions_service_accepts_llm_client():
    svc = NextActionsService(llm_client=None)
    assert svc is not None


def test_normalize_next_actions_empty_input():
    result = _normalize_next_actions(
        actions=[],
        original_prompt="",
        capabilities={
            "dimensions": [],
            "filter_columns": [],
            "time_columns": [],
            "domain_metrics": [],
            "user_metrics": [],
            "overlay_metrics": [],
        },
        max_items=5,
    )
    assert result == []


def test_normalize_next_actions_filters_invalid_items():
    """Items without required fields (label, prompt, reason) are dropped."""
    result = _normalize_next_actions(
        actions=[{"label": "Missing prompt and reason"}],
        original_prompt="test prompt",
        capabilities={
            "dimensions": [{"column_key": "d1.school_name"}],
            "filter_columns": [],
            "time_columns": [],
            "domain_metrics": [],
            "user_metrics": [],
            "overlay_metrics": [],
        },
        max_items=5,
    )
    assert result == []


def test_normalize_next_actions_valid_item():
    result = _normalize_next_actions(
        actions=[
            {
                "label": "By School",
                "prompt": "Show enrollment by school",
                "reason": "Groups by school.",
                "intent": "list",
                "dimensions": ["d1.school_name"],
                "metrics": [],
                "filters": [],
            }
        ],
        original_prompt="Show me enrollment",
        capabilities={
            "dimensions": [{"column_key": "d1.school_name"}],
            "filter_columns": [],
            "time_columns": [],
            "domain_metrics": [],
            "user_metrics": [],
            "overlay_metrics": [],
        },
        max_items=5,
    )
    assert len(result) == 1
    assert result[0]["label"] == "By School"
    assert result[0]["prompt"] == "Show enrollment by school"


def test_normalize_next_actions_respects_max_items():
    actions = [
        {
            "label": f"Option {i}",
            "prompt": f"Show data option {i}",
            "reason": f"Reason {i}.",
            "intent": "list",
            "dimensions": ["d1.school_name"],
            "metrics": [],
            "filters": [],
        }
        for i in range(10)
    ]
    result = _normalize_next_actions(
        actions=actions,
        original_prompt="Show me enrollment",
        capabilities={
            "dimensions": [{"column_key": "d1.school_name"}],
            "filter_columns": [],
            "time_columns": [],
            "domain_metrics": [],
            "user_metrics": [],
            "overlay_metrics": [],
        },
        max_items=3,
    )
    assert len(result) <= 3


def test_maybe_generate_returns_empty_when_disabled(monkeypatch):
    import app.services.planner_domain.next_actions_service as svc_module
    monkeypatch.setattr(svc_module, "QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED", False)
    svc = NextActionsService(llm_client=None)
    actions, trace = svc.maybe_generate(
        plan_json={},
        capabilities={},
        prompt="test",
        selected_domain_id=1,
        selected_domain_name="Test",
    )
    assert actions == []
    assert trace["enabled"] is False


def test_maybe_generate_tolerates_llm_provider_failures(monkeypatch):
    import app.services.planner_domain.next_actions_service as svc_module

    class _FailingLLM:
        def chat_json_with_trace(self, **kwargs):
            del kwargs
            raise ForgeError("LLM provider unavailable", status_code=503)

    monkeypatch.setattr(svc_module, "QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED", True)
    svc = NextActionsService(llm_client=_FailingLLM())
    actions, trace = svc.maybe_generate(
        plan_json={"intent": "list", "selects": {"dimensions": [{"column_key": "d1.school_name"}], "metrics": []}, "filters": []},
        capabilities={
            "dimensions": [{"column_key": "d1.school_name", "label": "School Name"}],
            "filter_columns": [],
            "time_columns": [],
            "domain_metrics": [],
            "user_metrics": [],
            "overlay_metrics": [],
            "domain_version": 1,
        },
        prompt="show schools",
        selected_domain_id=1,
        selected_domain_name="Test",
    )

    assert actions == []
    assert trace["enabled"] is True
    assert trace["used"] is False
    assert "LLM provider unavailable" in trace["error"]


def test_maybe_generate_surfaces_unexpected_llm_errors(monkeypatch):
    import app.services.planner_domain.next_actions_service as svc_module

    class _FailingLLM:
        def chat_json_with_trace(self, **kwargs):
            del kwargs
            raise AssertionError("unexpected llm failure")

    monkeypatch.setattr(svc_module, "QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED", True)
    svc = NextActionsService(llm_client=_FailingLLM())

    with pytest.raises(AssertionError, match="unexpected llm failure"):
        svc.maybe_generate(
            plan_json={"intent": "list", "selects": {"dimensions": [{"column_key": "d1.school_name"}], "metrics": []}, "filters": []},
            capabilities={
                "dimensions": [{"column_key": "d1.school_name", "label": "School Name"}],
                "filter_columns": [],
                "time_columns": [],
                "domain_metrics": [],
                "user_metrics": [],
                "overlay_metrics": [],
                "domain_version": 1,
            },
            prompt="show schools",
            selected_domain_id=1,
            selected_domain_name="Test",
        )
