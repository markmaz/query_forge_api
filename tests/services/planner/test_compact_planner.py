from __future__ import annotations

import json

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.planner.compact_planner import build_compact_plan_and_project
from app.services.planner.semantic_candidate_models import (
    SemanticCandidatePayload,
    SemanticConceptCandidate,
    SemanticValueCandidate,
)


class _FakeLLM:
    def __init__(self, traces):
        self._traces = list(traces)
        self.calls = 0

    def chat_json_with_trace(self, **kwargs):
        del kwargs
        idx = self.calls if self.calls < len(self._traces) else len(self._traces) - 1
        self.calls += 1
        return dict(self._traces[idx])


class _FakeRetrieval:
    def __init__(self, payload: SemanticCandidatePayload):
        self._payload = payload

    def retrieve(self, **kwargs):
        del kwargs
        return self._payload


def _capabilities() -> dict:
    return {
        "dimensions": [
            {"column_key": "wt178.account_name", "column_name": "account_name", "label": "Account Name", "model_column_id": 10},
            {"column_key": "wt187.territory_name", "column_name": "territory_name", "label": "Territory Name", "model_column_id": 11},
        ],
        "filter_columns": [
            {"column_key": "wt187.territory_region", "column_name": "territory_region", "label": "Territory Region", "model_column_id": 12},
        ],
        "time_columns": [
            {"column_key": "wt179.order_date", "column_name": "order_date", "label": "Order Date", "model_column_id": 13},
        ],
        "domain_metrics": [
            {"metric_key": "sales_revenue", "label": "Sales Revenue"},
            {"metric_key": "quota_attainment_pct", "label": "Quota Attainment %"},
        ],
        "user_metrics": [],
        "overlay_metrics": [],
    }


def _semantic_candidates() -> SemanticCandidatePayload:
    return SemanticCandidatePayload(
        prompt="Show total sales by account and territory in the NE this quarter",
        normalized_prompt="show total sales by account and territory in the ne this quarter",
        workspace_id="ws-1",
        vertical_norm="generic",
        base_domain_id=3,
        base_domain_key="SALES_PERFORMANCE",
        domain=SemanticConceptCandidate(concept_key="SALES_PERFORMANCE", label="Sales Performance", score=0.99, semantic_type="domain"),
        domain_candidates=[
            SemanticConceptCandidate(concept_key="SALES_PERFORMANCE", label="Sales Performance", score=0.99, semantic_type="domain"),
        ],
        metric_candidates=[
            SemanticConceptCandidate(
                concept_key="SALES_AMOUNT",
                label="Sales Amount",
                metric_ref="domain_metric:sales_revenue",
                score=0.98,
                semantic_type="metric",
                aliases=["revenue", "sales"],
                domain_key="SALES_PERFORMANCE",
            ),
        ],
        dimension_candidates=[
            SemanticConceptCandidate(
                concept_key="ACCOUNT_NAME",
                label="Account Name",
                source_column_key="wt178.account_name",
                score=0.97,
                semantic_type="dimension",
                aliases=["account"],
                domain_key="SALES_PERFORMANCE",
            ),
            SemanticConceptCandidate(
                concept_key="TERRITORY_NAME",
                label="Territory Name",
                source_column_key="wt187.territory_name",
                score=0.96,
                semantic_type="dimension",
                aliases=["territory"],
                domain_key="SALES_PERFORMANCE",
            ),
        ],
        filter_candidates=[
            SemanticConceptCandidate(
                concept_key="TERRITORY_REGION",
                label="Territory Region",
                source_column_key="wt187.territory_region",
                score=0.95,
                semantic_type="filter",
                aliases=["region", "territory region"],
                domain_key="SALES_PERFORMANCE",
            ),
        ],
        time_candidates=[
            SemanticConceptCandidate(
                concept_key="ORDER_DATE",
                label="Order Date",
                source_column_key="wt179.order_date",
                score=0.9,
                semantic_type="time_field",
                aliases=["date", "order date"],
                domain_key="SALES_PERFORMANCE",
            ),
        ],
        value_candidates=[
            SemanticValueCandidate(
                field_concept_key="TERRITORY_REGION",
                alias_value="ne",
                canonical_value="Northeast",
                score=0.95,
            ),
        ],
        lexical_hints={"sales": ["SALES_AMOUNT"]},
        planning_rules=["use only candidate concepts"],
        metadata={
            "semantic_source": "semantic_catalog",
            "domain_members": ["SALES_PERFORMANCE", "SALES_AMOUNT", "ACCOUNT_NAME", "TERRITORY_NAME", "TERRITORY_REGION", "ORDER_DATE"],
            "default_time_by_metric": {"SALES_AMOUNT": "ORDER_DATE"},
        },
    )


def test_compact_planner_returns_projected_plan_v2() -> None:
    payload = {
        "base_domain_key": "sales_performance",
        "intent": "aggregate",
        "metrics": ["sales_amount"],
        "dimensions": ["account_name", "territory_name"],
        "filters": [{"field_concept_key": "territory_region", "operator": "=", "value": "NE"}],
        "time": {
            "time_concept_key": "order_date",
            "time_range": "current_quarter",
            "time_grain": None,
            "start_date": None,
            "end_date": None,
        },
        "needs_clarification": False,
        "clarification_question": None,
        "confidence": 0.93,
    }
    llm = _FakeLLM(
        [
            {
                "parsed": payload,
                "content": json.dumps(payload),
                "raw_text": json.dumps({"model": "gpt-5", "usage": {"prompt_tokens": 120, "completion_tokens": 90}}),
                "finish_reason": "stop",
            }
        ]
    )
    out = build_compact_plan_and_project(
        prompt="Show total sales by account and territory in the NE this quarter",
        normalized_prompt="Show total sales by account and territory in the NE this quarter",
        workspace_id="ws-1",
        vertical_norm="generic",
        base_domain_id=3,
        domain_name="Sales Performance",
        capabilities_compact=_capabilities(),
        conversation_context={},
        trace_id="trace-compact-1",
        llm_client=llm,
        retrieval_service=_FakeRetrieval(_semantic_candidates()),
        max_tokens=500,
        fast_mode=False,
    )
    assert out["planner_mode"] == "compact_semantic_v2"
    assert out["plan_json_v2"]["intent"] == "aggregate"
    assert out["plan_json_v2"]["selects"]["metrics"][0]["metric_ref"] == "domain_metric:sales_revenue"
    assert out["plan_json_v2"]["selects"]["dimensions"][0]["column_key"] == "wt178.account_name"
    assert out["plan_json_v2"]["filters"][0]["column_key"] == "wt187.territory_region"
    assert out["plan_json_v2"]["filters"][0]["value"] == "Northeast"
    assert out["plan_json_v2"]["time"]["time_column_key"] == "wt179.order_date"
    assert out["attempts"] == 1


def test_compact_planner_truncation_retries_once() -> None:
    payload = {
        "base_domain_key": "sales_performance",
        "intent": "aggregate",
        "metrics": ["sales_amount"],
        "dimensions": ["account_name"],
        "filters": [],
        "time": {
            "time_concept_key": "order_date",
            "time_range": "current_quarter",
            "time_grain": None,
            "start_date": None,
            "end_date": None,
        },
        "needs_clarification": False,
        "clarification_question": None,
        "confidence": 0.8,
    }
    llm = _FakeLLM(
        [
            {"parsed": None, "content": "", "raw_text": '{"choices":[{"finish_reason":"length"}]}', "finish_reason": "length"},
            {"parsed": payload, "content": json.dumps(payload), "raw_text": json.dumps(payload), "finish_reason": "stop"},
        ]
    )
    out = build_compact_plan_and_project(
        prompt="Show quota attainment by sales rep this quarter",
        normalized_prompt="Show quota attainment by sales rep this quarter",
        workspace_id="ws-1",
        vertical_norm="generic",
        base_domain_id=3,
        domain_name="Sales Performance",
        capabilities_compact=_capabilities(),
        conversation_context={},
        trace_id="trace-compact-2",
        llm_client=llm,
        retrieval_service=_FakeRetrieval(_semantic_candidates()),
        max_tokens=500,
        fast_mode=False,
    )
    assert out["attempts"] == 2
    assert out["repaired"] is True


def test_compact_planner_rejects_invented_metric_ids() -> None:
    payload = {
        "base_domain_key": "sales_performance",
        "intent": "aggregate",
        "metrics": ["not_real_metric"],
        "dimensions": ["account_name"],
        "filters": [],
        "time": {
            "time_concept_key": None,
            "time_range": None,
            "time_grain": None,
            "start_date": None,
            "end_date": None,
        },
        "needs_clarification": False,
        "clarification_question": None,
        "confidence": 0.7,
    }
    llm = _FakeLLM(
        [
            {
                "parsed": payload,
                "content": json.dumps(payload),
                "raw_text": json.dumps(payload),
                "finish_reason": "stop",
            }
        ]
    )
    with pytest.raises(ForgeError) as exc:
        build_compact_plan_and_project(
            prompt="Show fake metric",
            normalized_prompt="Show fake metric",
            workspace_id="ws-1",
            vertical_norm="generic",
            base_domain_id=3,
            domain_name="Sales Performance",
            capabilities_compact=_capabilities(),
            conversation_context={},
            trace_id="trace-compact-3",
            llm_client=llm,
            retrieval_service=_FakeRetrieval(_semantic_candidates()),
            max_tokens=500,
            fast_mode=False,
        )
    assert str(exc.value.message) == "planner_compact_validation_failed"
    assert exc.value.status_code == 422


def test_compact_planner_raises_specific_truncation_error_when_both_attempts_truncate() -> None:
    llm = _FakeLLM(
        [
            {"parsed": None, "content": "", "raw_text": '{"choices":[{"finish_reason":"length"}]}', "finish_reason": "length"},
            {"parsed": None, "content": "", "raw_text": '{"choices":[{"finish_reason":"length"}]}', "finish_reason": "length"},
        ]
    )
    with pytest.raises(ForgeError) as exc:
        build_compact_plan_and_project(
            prompt="Show quota attainment by sales rep this quarter",
            normalized_prompt="Show quota attainment by sales rep this quarter",
            workspace_id="ws-1",
            vertical_norm="generic",
            base_domain_id=3,
            domain_name="Sales Performance",
            capabilities_compact=_capabilities(),
            conversation_context={},
            trace_id="trace-compact-4",
            llm_client=llm,
            retrieval_service=_FakeRetrieval(_semantic_candidates()),
            max_tokens=500,
            fast_mode=False,
        )
    assert str(exc.value.message) == "planner_compact_truncation"
    assert exc.value.status_code == 502


def test_compact_planner_coerces_relative_time_when_time_key_not_candidate() -> None:
    payload = {
        "base_domain_key": "sales_performance",
        "intent": "aggregate",
        "metrics": ["sales_amount"],
        "dimensions": ["account_name"],
        "filters": [],
        "time": {
            "time_concept_key": "fiscal_quarter",
            "time_range": None,
            "time_grain": None,
            "start_date": None,
            "end_date": None,
        },
        "needs_clarification": False,
        "clarification_question": None,
        "confidence": 0.9,
    }
    llm = _FakeLLM(
        [
            {
                "parsed": payload,
                "content": json.dumps(payload),
                "raw_text": json.dumps(payload),
                "finish_reason": "stop",
            }
        ]
    )
    candidates = _semantic_candidates().model_copy(
        update={
            "time_candidates": [],
            "filter_candidates": [
                SemanticConceptCandidate(
                    concept_key="FISCAL_QUARTER",
                    label="Fiscal Quarter",
                    source_column_key="wt179.fiscal_quarter",
                    score=0.2,
                    semantic_type="filter",
                    aliases=["fiscal quarter"],
                    domain_key="SALES_PERFORMANCE",
                )
            ],
        }
    )
    out = build_compact_plan_and_project(
        prompt="Show total sales by account this quarter",
        normalized_prompt="Show total sales by account this quarter",
        workspace_id="ws-1",
        vertical_norm="generic",
        base_domain_id=3,
        domain_name="Sales Performance",
        capabilities_compact=_capabilities(),
        conversation_context={},
        trace_id="trace-compact-5",
        llm_client=llm,
        retrieval_service=_FakeRetrieval(candidates),
        max_tokens=500,
        fast_mode=False,
    )
    assert out["compact_plan"]["time"]["time_range"] == "this_quarter"
    assert out["compact_plan"]["time"]["time_grain"] == "quarter"
    assert out["compact_plan"]["time"].get("time_concept_key") in {None, ""}
