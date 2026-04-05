"""Unit tests for app.services.planner_domain.normalizers.time."""
from datetime import date

import pytest

import app.services.planner_domain.normalizers._time_shared as time_shared_module
from app.services.planner_domain.normalizers.time import (
    _normalize_relative_time_in_plan,
    _normalize_year_keyword_filters_in_plan,
    _normalize_school_year_filters_in_plan,
    _normalize_semester_filters_in_plan,
    _semester_bucket_from_text,
)
from app.services.planner_domain.normalizers._time_shared import _policy_anchor_date


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


def test_policy_anchor_date_falls_back_to_today_for_invalid_timezone(monkeypatch):
    class _FakeDate:
        @staticmethod
        def today():
            return date(2026, 4, 4)

    monkeypatch.setattr(time_shared_module, "date", _FakeDate)
    assert _policy_anchor_date(today=None, timezone_name="Mars/Phobos") == date(2026, 4, 4)


def test_policy_anchor_date_surfaces_unexpected_datetime_failures(monkeypatch):
    class _FakeDateTime:
        @staticmethod
        def now(tz):
            del tz
            raise AssertionError("unexpected datetime failure")

    monkeypatch.setattr(time_shared_module, "datetime", _FakeDateTime)
    with pytest.raises(AssertionError, match="unexpected datetime failure"):
        _policy_anchor_date(today=None, timezone_name="UTC")
