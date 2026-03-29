"""Unit tests for app.services.planner_domain.normalizers.metric."""
from app.services.planner_domain.normalizers.metric import (
    _normalize_adm_default_filters_in_plan,
    _normalize_top_bottom_ranking_in_plan,
)


def test_normalize_adm_default_passthrough_no_adm_intent():
    plan_in = {"filters": [{"column_key": "wt1.first_name", "op": "eq", "value": "Alice"}]}
    plan_out, issues, debug = _normalize_adm_default_filters_in_plan(
        plan_json=plan_in, capabilities={}, prompt="show me student Alice"
    )
    assert plan_out == plan_in
    assert issues == []


def test_normalize_top_bottom_passthrough_no_top_bottom():
    plan_in = {"filters": []}
    plan_out, issues, debug = _normalize_top_bottom_ranking_in_plan(
        plan_json=plan_in, capabilities={}, prompt="list all students"
    )
    assert plan_out == plan_in
    assert issues == []
