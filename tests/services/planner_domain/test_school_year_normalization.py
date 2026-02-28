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
