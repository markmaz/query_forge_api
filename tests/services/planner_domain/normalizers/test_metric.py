"""Unit tests for app.services.planner_domain.normalizers.metric."""
import pytest

import app.services.planner_domain.normalizers.metric as metric_module
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


def test_normalize_top_bottom_passthrough_on_invalid_limit_token(monkeypatch):
    class _FakeMatch:
        def group(self, name):
            if name == "kind":
                return "top"
            if name == "limit":
                return "abc"
            raise AssertionError(f"unexpected group {name}")

    class _FakePattern:
        def search(self, text):
            del text
            return _FakeMatch()

    monkeypatch.setattr(metric_module, "_TOP_BOTTOM_LIMIT_RE", _FakePattern())
    plan_in = {"filters": []}
    plan_out, issues, debug = _normalize_top_bottom_ranking_in_plan(
        plan_json=plan_in, capabilities={}, prompt="show top stuff"
    )
    assert plan_out == plan_in
    assert issues == []
    assert debug == []


def test_normalize_top_bottom_surfaces_unexpected_match_errors(monkeypatch):
    class _FakeMatch:
        def group(self, name):
            del name
            raise AssertionError("unexpected regex match failure")

    class _FakePattern:
        def search(self, text):
            del text
            return _FakeMatch()

    monkeypatch.setattr(metric_module, "_TOP_BOTTOM_LIMIT_RE", _FakePattern())
    with pytest.raises(AssertionError, match="unexpected regex match failure"):
        _normalize_top_bottom_ranking_in_plan(
            plan_json={"filters": []},
            capabilities={},
            prompt="show top stuff",
        )
