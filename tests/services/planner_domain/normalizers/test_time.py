"""Unit tests for app.services.planner_domain.normalizers.time."""
from app.services.planner_domain.normalizers.time import (
    _normalize_relative_time_in_plan,
    _normalize_year_keyword_filters_in_plan,
    _normalize_school_year_filters_in_plan,
    _normalize_semester_filters_in_plan,
    _semester_bucket_from_text,
)


def test_normalize_relative_time_passthrough_no_relative_token():
    plan_in = {"filters": [], "time": {}}
    plan_out, issues, debug = _normalize_relative_time_in_plan(
        plan_json=plan_in, capabilities={}, prompt="show students"
    )
    assert plan_out["filters"] == []
    assert issues == []


def test_normalize_year_keyword_passthrough_empty_filters():
    plan_in = {"filters": []}
    plan_out, issues, debug = _normalize_year_keyword_filters_in_plan(
        plan_json=plan_in, capabilities={}, prompt=""
    )
    assert plan_out == plan_in
    assert issues == []


def test_normalize_school_year_passthrough_empty_filters():
    plan_in = {"filters": []}
    plan_out, issues, debug = _normalize_school_year_filters_in_plan(
        plan_json=plan_in, capabilities={}, prompt=""
    )
    assert plan_out == plan_in
    assert issues == []


def test_normalize_semester_passthrough_empty_filters():
    plan_in = {"filters": []}
    plan_out, issues, debug = _normalize_semester_filters_in_plan(
        plan_json=plan_in, capabilities={}, prompt=""
    )
    assert plan_out == plan_in
    assert issues == []


def test_semester_bucket_from_text_spring():
    assert _semester_bucket_from_text("spring") == "spring"


def test_semester_bucket_from_text_fall():
    assert _semester_bucket_from_text("fall") == "fall"
