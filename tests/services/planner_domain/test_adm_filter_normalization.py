from __future__ import annotations

from app.services.planner_domain.service import _normalize_adm_default_filters_in_plan


def test_adm_defaults_are_dropped_for_person_specific_prompt() -> None:
    plan = {
        "filters": [
            {"column_key": "wt24.first_name", "op": "=", "value": "Holden"},
            {"column_key": "wt24.last_name", "op": "=", "value": "Black"},
            {"column_key": "wt34.school_year", "op": "eq", "value": 2026},
            {"column_key": "wt34.is_primary_school", "op": "=", "value": True},
            {"column_key": "wt34.grade_level_adm", "op": "not_in", "values": ["P3", "P4"]},
        ]
    }
    capabilities = {
        "filter_columns": [
            {"column_key": "wt24.first_name", "column_name": "first_name", "filterable": True},
            {"column_key": "wt24.last_name", "column_name": "last_name", "filterable": True},
            {"column_key": "wt34.school_year", "column_name": "school_year", "filterable": True},
            {"column_key": "wt34.is_primary_school", "column_name": "is_primary_school", "filterable": True},
            {"column_key": "wt34.grade_level_adm", "column_name": "grade_level_adm", "filterable": True},
        ],
        "dimensions": [],
        "time_columns": [],
    }

    normalized, issues, debug_rows = _normalize_adm_default_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show me the ADM for the 2026 school year for Holden Black",
    )

    assert issues == []
    keys = [item.get("column_key") for item in normalized["filters"]]
    assert "wt24.first_name" in keys
    assert "wt24.last_name" in keys
    assert "wt34.school_year" in keys
    assert "wt34.is_primary_school" not in keys
    assert "wt34.grade_level_adm" not in keys
    assert len(debug_rows) == 2
    assert all(row.get("action") == "dropped_default_filter" for row in debug_rows)


def test_adm_defaults_are_kept_when_user_explicitly_requests_them() -> None:
    plan = {
        "filters": [
            {"column_key": "wt24.first_name", "op": "=", "value": "Holden"},
            {"column_key": "wt24.last_name", "op": "=", "value": "Black"},
            {"column_key": "wt34.is_primary_school", "op": "=", "value": True},
            {"column_key": "wt34.grade_level_adm", "op": "not_in", "values": ["P3", "P4"]},
        ]
    }
    capabilities = {
        "filter_columns": [
            {"column_key": "wt24.first_name", "column_name": "first_name", "filterable": True},
            {"column_key": "wt24.last_name", "column_name": "last_name", "filterable": True},
            {"column_key": "wt34.is_primary_school", "column_name": "is_primary_school", "filterable": True},
            {"column_key": "wt34.grade_level_adm", "column_name": "grade_level_adm", "filterable": True},
        ],
        "dimensions": [],
        "time_columns": [],
    }

    normalized, issues, debug_rows = _normalize_adm_default_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show ADM for Holden Black, primary school only and include pre-k",
    )

    assert issues == []
    keys = [item.get("column_key") for item in normalized["filters"]]
    assert "wt34.is_primary_school" in keys
    assert "wt34.grade_level_adm" in keys
    assert debug_rows == []
