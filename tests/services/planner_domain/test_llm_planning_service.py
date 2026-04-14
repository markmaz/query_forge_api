"""Unit tests for app.services.planner_domain.llm_planning_service."""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

from app.services.planner_domain.llm_planning_service import (
    LLMPlanningService,
    _looks_like_plan_v2,
    _looks_like_slot_payload,
)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_llm_planning_service_can_be_constructed() -> None:
    svc = LLMPlanningService(llm_client=MagicMock())
    assert svc is not None


# ---------------------------------------------------------------------------
# _looks_like_plan_v2
# ---------------------------------------------------------------------------


def test_looks_like_plan_v2_valid_minimal() -> None:
    payload = {"selects": {"dimensions": [], "metrics": []}}
    assert _looks_like_plan_v2(payload) is True


def test_looks_like_plan_v2_with_all_keys() -> None:
    payload = {
        "selects": {"dimensions": [{"column_key": "wt1.grade"}], "metrics": []},
        "filters": [],
        "time": {},
        "grouping": {"group_by": [], "limit": None, "order_by": []},
    }
    assert _looks_like_plan_v2(payload) is True


def test_looks_like_plan_v2_missing_selects() -> None:
    assert _looks_like_plan_v2({"filters": []}) is False


def test_looks_like_plan_v2_selects_not_dict() -> None:
    assert _looks_like_plan_v2({"selects": "bad"}) is False


def test_looks_like_plan_v2_dimensions_not_list() -> None:
    assert _looks_like_plan_v2({"selects": {"dimensions": "bad", "metrics": []}}) is False


def test_looks_like_plan_v2_filters_not_list() -> None:
    assert _looks_like_plan_v2({"selects": {"dimensions": []}, "filters": "bad"}) is False


def test_looks_like_plan_v2_rejects_non_dict() -> None:
    assert _looks_like_plan_v2("not a dict") is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _looks_like_slot_payload
# ---------------------------------------------------------------------------


def test_looks_like_slot_payload_valid() -> None:
    payload = {"intent": "list", "constraints": [], "time_phrases": []}
    assert _looks_like_slot_payload(payload) is True


def test_looks_like_slot_payload_valid_with_constraint() -> None:
    payload = {
        "intent": "list",
        "constraints": [{"kind": "demographic", "text": "Hispanic", "op": "eq"}],
        "time_phrases": [],
    }
    assert _looks_like_slot_payload(payload) is True


def test_looks_like_slot_payload_missing_required_key() -> None:
    payload = {"intent": "list", "time_phrases": []}
    assert _looks_like_slot_payload(payload) is False


def test_looks_like_slot_payload_constraints_not_list() -> None:
    payload = {"intent": "list", "constraints": "bad", "time_phrases": []}
    assert _looks_like_slot_payload(payload) is False


def test_looks_like_slot_payload_constraint_item_missing_keys() -> None:
    payload = {
        "intent": "list",
        "constraints": [{"kind": "demographic"}],  # missing text and op
        "time_phrases": [],
    }
    assert _looks_like_slot_payload(payload) is False


def test_looks_like_slot_payload_time_phrases_not_list() -> None:
    payload = {"intent": "list", "constraints": [], "time_phrases": "not a list"}
    assert _looks_like_slot_payload(payload) is False


# ---------------------------------------------------------------------------
# _normalize_llm_plan (static method)
# ---------------------------------------------------------------------------


def test_normalize_llm_plan_sets_required_fields() -> None:
    raw = {"selects": {"dimensions": [], "metrics": []}, "filters": []}
    result = LLMPlanningService._normalize_llm_plan(
        raw_plan=raw,
        trace_id="t1",
        workspace_id="ws-1",
        base_domain_id=42,
    )
    assert result["schema_version"] == 2
    assert result["trace_id"] == "t1"
    assert result["workspace_id"] == "ws-1"
    assert result["base_domain_id"] == 42


def test_normalize_llm_plan_adds_domain_name_when_provided() -> None:
    result = LLMPlanningService._normalize_llm_plan(
        raw_plan={},
        trace_id="t1",
        workspace_id="ws-1",
        base_domain_id=1,
        base_domain_name="Student Demographics",
    )
    assert result["domain_name"] == "Student Demographics"


def test_normalize_llm_plan_omits_domain_name_when_blank() -> None:
    result = LLMPlanningService._normalize_llm_plan(
        raw_plan={},
        trace_id="t1",
        workspace_id="ws-1",
        base_domain_id=1,
        base_domain_name="",
    )
    assert "domain_name" not in result


def test_normalize_llm_plan_normalizes_camel_case_column_key() -> None:
    raw = {
        "selects": {
            "dimensions": [{"columnKey": "wt1.grade"}],
            "metrics": [],
        }
    }
    result = LLMPlanningService._normalize_llm_plan(
        raw_plan=raw,
        trace_id="t1",
        workspace_id="ws-1",
        base_domain_id=1,
    )
    assert result["selects"]["dimensions"][0]["column_key"] == "wt1.grade"


def test_normalize_llm_plan_normalizes_camel_case_metric_ref() -> None:
    raw = {
        "selects": {
            "dimensions": [],
            "metrics": [{"metricRef": "count"}],
        }
    }
    result = LLMPlanningService._normalize_llm_plan(
        raw_plan=raw,
        trace_id="t1",
        workspace_id="ws-1",
        base_domain_id=1,
    )
    assert result["selects"]["metrics"][0]["metric_ref"] == "count"


def test_normalize_llm_plan_drops_empty_column_keys() -> None:
    raw = {
        "selects": {
            "dimensions": [{"column_key": ""}, {"column_key": "wt1.grade"}],
            "metrics": [],
        }
    }
    result = LLMPlanningService._normalize_llm_plan(
        raw_plan=raw,
        trace_id="t1",
        workspace_id="ws-1",
        base_domain_id=1,
    )
    assert len(result["selects"]["dimensions"]) == 1
    assert result["selects"]["dimensions"][0]["column_key"] == "wt1.grade"


def test_normalize_llm_plan_sets_defaults_for_missing_keys() -> None:
    result = LLMPlanningService._normalize_llm_plan(
        raw_plan={},
        trace_id="t1",
        workspace_id="ws-1",
        base_domain_id=1,
    )
    assert result["intent"] == "list"
    assert result["filters"] == []
    assert result["time"] == {}
    assert result["grouping"] == {"group_by": [], "limit": None, "order_by": []}


# ---------------------------------------------------------------------------
# _merge_slot_hints (no LLM dependency)
# ---------------------------------------------------------------------------


def test_merge_slot_hints_basic_passthrough() -> None:
    svc = LLMPlanningService(llm_client=MagicMock())
    result = svc._merge_slot_hints(  # noqa: SLF001
        prompt="show students",
        slot_payload={"intent": "list", "entity": "students", "constraints": [], "time_phrases": []},
    )
    assert result["intent"] == "list"
    assert result["entity"] == "students"
    assert result["constraints"] == []
    assert result["time_phrases"] == []


def test_merge_slot_hints_merges_semantic_constraints() -> None:
    svc = LLMPlanningService(llm_client=MagicMock())
    semantic = [{"kind": "value", "text": "United States", "op": "eq", "value_hint": "United States", "notes": None}]
    result = svc._merge_slot_hints(  # noqa: SLF001
        prompt="students born in US",
        slot_payload={"intent": "list", "entity": "students", "constraints": [], "time_phrases": []},
        semantic_constraints=semantic,
    )
    assert any(c["value_hint"] == "United States" for c in result["constraints"])


def test_merge_slot_hints_deduplicates_constraints() -> None:
    svc = LLMPlanningService(llm_client=MagicMock())
    constraint = {"kind": "value", "text": "United States", "op": "eq", "value_hint": "United States", "notes": None}
    result = svc._merge_slot_hints(  # noqa: SLF001
        prompt="students born in US",
        slot_payload={"intent": "list", "entity": "students", "constraints": [constraint], "time_phrases": []},
        semantic_constraints=[constraint],  # same constraint again
    )
    country_constraints = [c for c in result["constraints"] if c.get("value_hint") == "United States"]
    assert len(country_constraints) == 1


def test_merge_slot_hints_infers_list_intent_from_prompt() -> None:
    svc = LLMPlanningService(llm_client=MagicMock())
    result = svc._merge_slot_hints(  # noqa: SLF001
        prompt="show me a list of students at Barksdale",
        slot_payload={"intent": "unknown", "entity": "", "constraints": [], "time_phrases": []},
    )
    assert result["intent"] == "list"


def test_merge_slot_hints_extracts_time_phrases_from_prompt() -> None:
    svc = LLMPlanningService(llm_client=MagicMock())
    result = svc._merge_slot_hints(  # noqa: SLF001
        prompt="students enrolled last year",
        slot_payload={"intent": "list", "entity": "students", "constraints": [], "time_phrases": []},
    )
    assert len(result["time_phrases"]) > 0


# ---------------------------------------------------------------------------
# _call_llm_slots (with mock LLM)
# ---------------------------------------------------------------------------


def _make_slot_llm(parsed: Dict[str, Any]) -> MagicMock:
    """Return a mock LLM that returns a valid slot payload."""
    mock_llm = MagicMock()
    mock_llm.chat_json_with_trace.return_value = {"parsed": parsed, "content": "{}"}
    return mock_llm


def test_call_llm_slots_returns_slot_extraction_result_on_valid_response() -> None:
    valid_slots = {
        "intent": "list",
        "entity": "students",
        "constraints": [],
        "time_phrases": [],
    }
    svc = LLMPlanningService(llm_client=_make_slot_llm(valid_slots))
    result = svc._call_llm_slots(  # noqa: SLF001
        normalized_prompt="show students",
        workspace_id="ws-1",
        base_domain_id=6,
    )
    assert result.payload["intent"] == "list"
    assert result.repaired is False
    assert result.attempts >= 1


def test_call_llm_slots_falls_back_gracefully_on_invalid_response() -> None:
    mock_llm = MagicMock()
    mock_llm.chat_json_with_trace.return_value = {"parsed": None, "content": "not valid json"}
    svc = LLMPlanningService(llm_client=mock_llm)
    result = svc._call_llm_slots(  # noqa: SLF001
        normalized_prompt="show students",
        workspace_id="ws-1",
        base_domain_id=6,
        fast_mode=True,
    )
    # Fast mode: should return a fallback result, not raise
    assert result is not None
    assert isinstance(result.payload, dict)


# ---------------------------------------------------------------------------
# _call_llm_plan (with mock LLM)
# ---------------------------------------------------------------------------


def _make_plan_llm(parsed: Dict[str, Any]) -> MagicMock:
    mock_llm = MagicMock()
    mock_llm.chat_json_with_trace.return_value = {"parsed": parsed, "content": "{}"}
    return mock_llm


def test_call_llm_plan_returns_llm_plan_result_on_valid_response() -> None:
    valid_plan = {
        "selects": {"dimensions": [{"column_key": "wt1.grade"}], "metrics": []},
        "filters": [],
    }
    svc = LLMPlanningService(llm_client=_make_plan_llm(valid_plan))
    result = svc._call_llm_plan(  # noqa: SLF001
        normalized_prompt="show grades",
        workspace_id="ws-1",
        base_domain_id=6,
        capabilities={"dimensions": [{"column_key": "wt1.grade", "column_name": "grade"}]},
        schema={"type": "object"},
        slot_hints={"intent": "list", "entity": "students", "constraints": [], "time_phrases": []},
    )
    assert result.plan_json["selects"]["dimensions"][0]["column_key"] == "wt1.grade"
    assert result.repaired is False
    assert result.attempts >= 1
