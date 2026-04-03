from __future__ import annotations

from datetime import date

from app.services.planner_domain.normalizers.time import _normalize_semester_filters_in_plan, _semester_bucket_from_text


def test_semester_filter_normalizes_current_semester_to_spring() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 7,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt24.grade_level"}], "metrics": []},
        "filters": [{"column_key": "wt24.term_name", "op": "=", "value": "current semester"}],
        "time": {},
        "grouping": {"group_by": ["wt24.grade_level"], "order_by": []},
    }
    capabilities = {
        "dimensions": [
            {
                "column_key": "wt24.grade_level",
                "filterable": True,
                "column_name": "grade_level",
                "data_type": "string",
            }
        ],
        "filter_columns": [
            {
                "column_key": "wt24.term_name",
                "filterable": True,
                "column_name": "term_name",
                "data_type": "string",
            }
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, debug_rows = _normalize_semester_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        today=date(2026, 2, 27),
    )
    assert issues == []
    assert normalized["filters"][0]["op"] == "eq"
    assert normalized["filters"][0]["value"] == "Spring"
    assert debug_rows[0]["normalized"] == ["Spring"]


def test_semester_filter_normalizes_current_semester_to_fall() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 7,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt24.grade_level"}], "metrics": []},
        "filters": [{"column_key": "wt24.term_name", "op": "=", "value": "current semester"}],
        "time": {},
        "grouping": {"group_by": ["wt24.grade_level"], "order_by": []},
    }
    capabilities = {
        "dimensions": [],
        "filter_columns": [
            {
                "column_key": "wt24.term_name",
                "filterable": True,
                "column_name": "term_name",
                "data_type": "string",
            }
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, _debug_rows = _normalize_semester_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        today=date(2026, 10, 1),
    )
    assert issues == []
    assert normalized["filters"][0]["value"] == "Fall"


def test_semester_filter_rewrites_to_indicator_column_when_available() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 7,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt24.grade_level"}], "metrics": []},
        "filters": [{"column_key": "wt24.term_name", "op": "=", "value": "current semester"}],
        "time": {},
        "grouping": {"group_by": ["wt24.grade_level"], "order_by": []},
    }
    capabilities = {
        "dimensions": [],
        "filter_columns": [
            {
                "column_key": "wt24.term_name",
                "filterable": True,
                "column_name": "term_name",
                "data_type": "string",
            },
            {
                "column_key": "wt24.is_spring_block",
                "filterable": True,
                "column_name": "is_spring_block",
                "data_type": "boolean",
                "semantic_type": "flag",
            },
            {
                "column_key": "wt24.is_fall_block",
                "filterable": True,
                "column_name": "is_fall_block",
                "data_type": "boolean",
                "semantic_type": "flag",
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, debug_rows = _normalize_semester_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        today=date(2026, 2, 27),
    )
    assert issues == []
    assert normalized["filters"][0]["column_key"] == "wt24.is_spring_block"
    assert normalized["filters"][0]["op"] == "eq"
    assert normalized["filters"][0]["value"] is True
    assert debug_rows[0]["rewritten_to_indicator"] is True


def test_semester_filter_not_equals_rewrites_to_indicator_column() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 7,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt24.grade_level"}], "metrics": []},
        "filters": [{"column_key": "wt24.term_name", "op": "!=", "value": "fall semester"}],
        "time": {},
        "grouping": {"group_by": ["wt24.grade_level"], "order_by": []},
    }
    capabilities = {
        "dimensions": [],
        "filter_columns": [
            {
                "column_key": "wt24.term_name",
                "filterable": True,
                "column_name": "term_name",
                "data_type": "string",
            },
            {
                "column_key": "wt24.is_fall_block",
                "filterable": True,
                "column_name": "is_fall_block",
                "data_type": "boolean",
                "semantic_type": "flag",
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, debug_rows = _normalize_semester_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        today=date(2026, 2, 27),
    )
    assert issues == []
    assert normalized["filters"][0]["column_key"] == "wt24.is_fall_block"
    assert normalized["filters"][0]["op"] == "ne"
    assert normalized["filters"][0]["value"] is True
    assert debug_rows[0]["rewritten_to_indicator"] is True


def test_semester_bucket_recognizes_explicit_semantic_concept_keys() -> None:
    assert _semester_bucket_from_text("SEMESTER_SPRING_FLAG") == "spring"
    assert _semester_bucket_from_text("SEMESTER_FALL_FLAG") == "fall"
    assert _semester_bucket_from_text("SEMESTER_YEAR_ROUND_FLAG") == "year_round"


def test_semester_filter_uses_domain_time_policy_labels_and_ranges() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 7,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt24.grade_level"}], "metrics": []},
        "filters": [{"column_key": "wt24.term_name", "op": "=", "value": "current semester"}],
        "time": {},
        "grouping": {"group_by": ["wt24.grade_level"], "order_by": []},
    }
    capabilities = {
        "dimensions": [],
        "filter_columns": [
            {
                "column_key": "wt24.term_name",
                "filterable": True,
                "column_name": "term_name",
                "data_type": "string",
            }
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, _debug_rows = _normalize_semester_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        today=date(2026, 6, 20),
        domain_time_policy={
            "semester": {
                "labels": {
                    "spring": "Spring Term",
                    "fall": "Fall Term",
                    "year_round": "Summer Session",
                },
                "month_ranges": {
                    "spring": [1, 4],
                    "fall": [8, 12],
                    "year_round": [5, 7],
                },
            }
        },
    )
    assert issues == []
    assert normalized["filters"][0]["value"] == "Summer Session"


def test_semester_filter_uses_domain_time_policy_indicator_columns() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 7,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt24.grade_level"}], "metrics": []},
        "filters": [{"column_key": "wt24.term_name", "op": "=", "value": "fall semester"}],
        "time": {},
        "grouping": {"group_by": ["wt24.grade_level"], "order_by": []},
    }
    capabilities = {
        "dimensions": [],
        "filter_columns": [
            {
                "column_key": "wt24.term_name",
                "filterable": True,
                "column_name": "term_name",
                "data_type": "string",
            }
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, debug_rows = _normalize_semester_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        today=date(2026, 2, 27),
        domain_time_policy={
            "semester": {
                "indicator_columns": {
                    "fall": "wt24.policy_fall_term",
                }
            }
        },
    )
    assert issues == []
    assert normalized["filters"][0]["column_key"] == "wt24.policy_fall_term"
    assert normalized["filters"][0]["value"] is True
    assert debug_rows[0]["indicator_column_key"] == "wt24.policy_fall_term"
