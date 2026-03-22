from __future__ import annotations

from datetime import date

from app.services.planner_domain.service import _normalize_school_year_filters_in_plan


def test_school_year_filter_normalizes_current_school_year() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 7,
        "intent": "aggregate",
        "selects": {"dimensions": [{"column_key": "wt24.grade_level"}], "metrics": []},
        "filters": [{"column_key": "wt24.school_year", "op": "=", "value": "current school year"}],
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
                "column_key": "wt24.school_year",
                "filterable": True,
                "column_name": "school_year",
                "data_type": "int",
            }
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, debug_rows = _normalize_school_year_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        today=date(2026, 2, 27),
    )
    assert issues == []
    assert normalized["filters"][0]["op"] == "eq"
    assert normalized["filters"][0]["value"] == 2026
    assert debug_rows[0]["normalized"] == [2026]


def test_school_year_filter_rolls_to_next_year_in_august() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 7,
        "intent": "aggregate",
        "selects": {"dimensions": [{"column_key": "wt24.grade_level"}], "metrics": []},
        "filters": [{"column_key": "wt24.school_year", "op": "=", "value": "current school year"}],
        "time": {},
        "grouping": {"group_by": ["wt24.grade_level"], "order_by": []},
    }
    capabilities = {
        "dimensions": [],
        "filter_columns": [
            {
                "column_key": "wt24.school_year",
                "filterable": True,
                "column_name": "school_year",
                "data_type": "int",
            }
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, _debug_rows = _normalize_school_year_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        today=date(2026, 8, 1),
    )
    assert issues == []
    assert normalized["filters"][0]["value"] == 2027


def test_school_year_filter_synthesized_from_time_block_when_missing() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t2",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 7,
        "intent": "aggregate",
        "selects": {"dimensions": [{"column_key": "wt24.grade_level"}], "metrics": []},
        "filters": [],
        "time": {"time_grain": "school_year", "time_column_key": "wt24.school_year"},
        "grouping": {"group_by": ["wt24.grade_level"], "order_by": []},
    }
    capabilities = {
        "dimensions": [],
        "filter_columns": [
            {
                "column_key": "wt24.school_year",
                "filterable": True,
                "column_name": "school_year",
                "data_type": "int",
                "semantic_type": "time.school_year",
            }
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, debug_rows = _normalize_school_year_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Which students have more than 10 absences this school year?",
        today=date(2026, 2, 27),
    )
    assert issues == []
    assert normalized["filters"][0]["column_key"] == "wt24.school_year"
    assert normalized["filters"][0]["op"] == "eq"
    assert normalized["filters"][0]["value"] == 2026
    assert debug_rows[0]["normalized"] == [2026]


def test_school_year_filter_synthesized_alongside_existing_non_time_filter() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t3",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 7,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt24.student_name"}], "metrics": []},
        "filters": [{"column_key": "wt30.days_absent", "op": ">", "value": 10}],
        "time": {"time_grain": "school_year", "time_column_key": "wt24.school_year"},
        "grouping": {"group_by": ["wt24.student_name"], "order_by": []},
    }
    capabilities = {
        "dimensions": [
            {
                "column_key": "wt24.student_name",
                "filterable": True,
                "column_name": "student_name",
                "data_type": "string",
            }
        ],
        "filter_columns": [
            {
                "column_key": "wt30.days_absent",
                "filterable": True,
                "column_name": "days_absent",
                "data_type": "int",
            },
            {
                "column_key": "wt24.school_year",
                "filterable": True,
                "column_name": "school_year",
                "data_type": "int",
                "semantic_type": "time.school_year",
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, debug_rows = _normalize_school_year_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Which students have more than 10 absences this school year?",
        today=date(2026, 2, 27),
    )

    assert issues == []
    assert len(normalized["filters"]) == 2
    assert normalized["filters"][0]["column_key"] == "wt30.days_absent"
    assert normalized["filters"][1]["column_key"] == "wt24.school_year"
    assert normalized["filters"][1]["op"] == "eq"
    assert normalized["filters"][1]["value"] == 2026
    assert debug_rows[0]["column_key"] == "wt24.school_year"
    assert debug_rows[0]["normalized"] == [2026]
