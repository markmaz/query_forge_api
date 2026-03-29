"""Unit tests for app.services.planner_domain.normalization_pipeline."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.services.planner_domain.normalization_pipeline import (
    NormalizationPipeline,
    NormalizationPipelineResult,
)


# ---------------------------------------------------------------------------
# Helpers — simple test normalizers
# ---------------------------------------------------------------------------


def _noop(*, plan_json, capabilities, prompt="", **_extra):
    """Normalizer that passes through unchanged."""
    return dict(plan_json), [], {}


def _add_issue(issue: str):
    """Return a normalizer that appends a fixed issue string."""
    def _fn(*, plan_json, capabilities, prompt="", **_extra):
        return dict(plan_json), [issue], {"applied": 1}
    return _fn


def _append_to_plan(key: str, value: Any):
    """Return a normalizer that adds a key to the plan."""
    def _fn(*, plan_json, capabilities, prompt="", **_extra):
        out = dict(plan_json)
        out[key] = value
        return out, [], {}
    return _fn


def _capture_extra_params():
    """Return a normalizer that records the extra params it received."""
    captured: Dict[str, Any] = {}

    def _fn(*, plan_json, capabilities, prompt="", **kwargs):
        captured.update(kwargs)
        return dict(plan_json), [], {}

    return _fn, captured


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_normalization_pipeline_can_be_constructed() -> None:
    pipeline = NormalizationPipeline(normalizers=[])
    assert pipeline is not None


def test_normalization_pipeline_result_is_dataclass() -> None:
    result = NormalizationPipelineResult(plan={}, all_issues=[], debug={})
    assert result.plan == {}
    assert result.all_issues == []
    assert result.debug == {}


# ---------------------------------------------------------------------------
# Empty pipeline
# ---------------------------------------------------------------------------


def test_empty_pipeline_returns_plan_unchanged() -> None:
    pipeline = NormalizationPipeline(normalizers=[])
    plan = {"intent": "list", "filters": []}
    result = pipeline.run(plan=plan, capabilities={}, prompt="test")
    assert result.plan == plan
    assert result.all_issues == []
    assert result.debug == {}


# ---------------------------------------------------------------------------
# Threading plan through normalizers
# ---------------------------------------------------------------------------


def test_pipeline_threads_plan_through_normalizers_in_order() -> None:
    pipeline = NormalizationPipeline(
        normalizers=[
            ("step_a", _append_to_plan("a", 1)),
            ("step_b", _append_to_plan("b", 2)),
        ]
    )
    result = pipeline.run(plan={}, capabilities={}, prompt="test")
    assert result.plan["a"] == 1
    assert result.plan["b"] == 2


def test_pipeline_normalizers_see_output_of_previous_step() -> None:
    """Each normalizer receives the plan returned by the previous one."""
    seen_plans: List[Dict[str, Any]] = []

    def _capture(*, plan_json, capabilities, prompt="", **_extra):
        seen_plans.append(dict(plan_json))
        out = dict(plan_json)
        out["step_count"] = out.get("step_count", 0) + 1
        return out, [], {}

    pipeline = NormalizationPipeline(
        normalizers=[("s1", _capture), ("s2", _capture), ("s3", _capture)]
    )
    result = pipeline.run(plan={}, capabilities={}, prompt="test")
    assert result.plan["step_count"] == 3
    assert seen_plans[0].get("step_count", 0) == 0
    assert seen_plans[1]["step_count"] == 1
    assert seen_plans[2]["step_count"] == 2


# ---------------------------------------------------------------------------
# Issue aggregation
# ---------------------------------------------------------------------------


def test_pipeline_aggregates_issues_from_all_normalizers() -> None:
    pipeline = NormalizationPipeline(
        normalizers=[
            ("country", _add_issue("country_normalized:wt1.country_code")),
            ("school_year", _add_issue("school_year_normalized")),
        ]
    )
    result = pipeline.run(plan={}, capabilities={}, prompt="test")
    assert "country_normalized:wt1.country_code" in result.all_issues
    assert "school_year_normalized" in result.all_issues


def test_pipeline_noop_normalizer_contributes_no_issues() -> None:
    pipeline = NormalizationPipeline(normalizers=[("noop", _noop)])
    result = pipeline.run(plan={"filters": []}, capabilities={}, prompt="test")
    assert result.all_issues == []


# ---------------------------------------------------------------------------
# Debug collection
# ---------------------------------------------------------------------------


def test_pipeline_collects_debug_by_normalizer_name() -> None:
    pipeline = NormalizationPipeline(
        normalizers=[
            ("country", _add_issue("country_normalized")),
            ("noop", _noop),
        ]
    )
    result = pipeline.run(plan={}, capabilities={}, prompt="test")
    assert "country" in result.debug
    assert result.debug["country"]["applied"] == 1
    assert "noop" not in result.debug  # empty debug not included


# ---------------------------------------------------------------------------
# Extra parameter forwarding
# ---------------------------------------------------------------------------


def test_pipeline_passes_semester_indicator_columns_to_normalizers() -> None:
    fn, captured = _capture_extra_params()
    pipeline = NormalizationPipeline(normalizers=[("semester", fn)])
    semester_cols = {"spring": "wt1.is_spring", "fall": "wt1.is_fall"}
    pipeline.run(
        plan={},
        capabilities={},
        prompt="test",
        semester_indicator_columns=semester_cols,
    )
    assert captured.get("semester_indicator_columns") == semester_cols


def test_pipeline_passes_domain_time_policy_to_normalizers() -> None:
    fn, captured = _capture_extra_params()
    pipeline = NormalizationPipeline(normalizers=[("time", fn)])
    policy = {"anchor_date": "2026-01-01"}
    pipeline.run(
        plan={},
        capabilities={},
        prompt="test",
        domain_time_policy=policy,
    )
    assert captured.get("domain_time_policy") == policy


def test_pipeline_passes_today_to_normalizers() -> None:
    fn, captured = _capture_extra_params()
    pipeline = NormalizationPipeline(normalizers=[("time", fn)])
    today = date(2026, 3, 28)
    pipeline.run(plan={}, capabilities={}, prompt="test", today=today)
    assert captured.get("today") == today


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


def test_pipeline_run_returns_normalization_pipeline_result() -> None:
    pipeline = NormalizationPipeline(normalizers=[("step", _noop)])
    result = pipeline.run(plan={"intent": "list"}, capabilities={}, prompt="")
    assert isinstance(result, NormalizationPipelineResult)
    assert result.plan["intent"] == "list"
