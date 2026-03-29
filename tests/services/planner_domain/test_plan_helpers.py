"""Unit tests for app.services.planner_domain.plan_helpers."""
from app.services.planner_domain.plan_helpers import (
    _dedupe_constraints,
    _format_validation_feedback,
    _norm_key,
    _serialize_domain_candidates_for_debug,
    _should_retry_after_validation,
    _to_int,
)


def test_norm_key_lowercases_and_strips():
    assert _norm_key("  School_Name  ") == "school_name"


def test_to_int_valid():
    assert _to_int("42") == 42


def test_to_int_invalid():
    assert _to_int("abc") is None


def test_should_retry_after_validation_empty_plan():
    issues = [{"code": "empty_plan", "message": ""}]
    assert _should_retry_after_validation(issues) is True


def test_should_retry_after_validation_unretryable():
    issues = [{"code": "some_other_code", "message": ""}]
    assert _should_retry_after_validation(issues) is False


def test_format_validation_feedback_empty():
    assert _format_validation_feedback([]) == ""


def test_serialize_domain_candidates_empty():
    result = _serialize_domain_candidates_for_debug([])
    assert result == []


def test_dedupe_constraints_removes_duplicates():
    constraints = [
        {"kind": "filter", "text": "school year", "op": "eq"},
        {"kind": "filter", "text": "school year", "op": "eq"},
    ]
    result = _dedupe_constraints(constraints)
    assert len(result) == 1
