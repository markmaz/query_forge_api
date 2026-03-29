"""Unit tests for app.services.planner_domain.normalizers.entity."""
from app.services.planner_domain.normalizers.entity import (
    _normalize_country_filters_in_plan,
    _normalize_school_name_filters_in_plan,
    _normalize_staff_role_filters_in_plan,
)


def test_normalize_country_passthrough_empty_filters():
    plan_in = {"filters": []}
    plan_out, issues, debug = _normalize_country_filters_in_plan(
        plan_json=plan_in, capabilities={}, prompt=""
    )
    assert plan_out == plan_in
    assert issues == []
    assert debug == []


def test_normalize_school_name_passthrough_empty_filters():
    plan_in = {"filters": []}
    plan_out, issues, debug = _normalize_school_name_filters_in_plan(
        plan_json=plan_in, capabilities={}, prompt=""
    )
    assert plan_out == plan_in
    assert issues == []
    assert debug == []


def test_normalize_staff_role_passthrough_no_role_hint():
    plan_in = {"filters": []}
    plan_out, issues, debug = _normalize_staff_role_filters_in_plan(
        plan_json=plan_in, capabilities={}, prompt="list students"
    )
    assert plan_out["filters"] == []
    assert issues == []
