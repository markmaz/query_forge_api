from __future__ import annotations

from app.services.planner_domain.service import _normalize_school_name_filters_in_plan


def test_school_name_filter_rewrites_k_school_to_school_name() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 5,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt30.position_title"}], "metrics": []},
        "filters": [
            {"column_key": "wt30.position_title", "op": "=", "value": "Principal"},
            {"column_key": "wt30.k_school", "op": "=", "value": "Barksdale Elementary"},
        ],
        "time": {},
        "grouping": {"group_by": ["wt30.position_title"], "order_by": []},
    }
    capabilities = {
        "dimensions": [
            {"column_key": "wt30.position_title", "column_name": "position_title", "filterable": True},
            {"column_key": "wt30.k_school", "column_name": "k_school", "filterable": True},
            {"column_key": "wt20.school_name", "column_name": "school_name", "filterable": True},
        ],
        "filter_columns": [
            {"column_key": "wt30.position_title", "column_name": "position_title", "filterable": True},
            {"column_key": "wt30.k_school", "column_name": "k_school", "filterable": True},
            {"column_key": "wt20.school_name", "column_name": "school_name", "filterable": True},
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, debug_rows = _normalize_school_name_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show me the principal for Barksdale Elementary",
    )

    assert issues == []
    assert normalized["filters"][1]["column_key"] == "wt20.school_name"
    assert debug_rows[0]["rewritten"] is True


def test_school_name_filter_does_not_rewrite_when_prompt_requests_school_id() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 5,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt30.position_title"}], "metrics": []},
        "filters": [{"column_key": "wt30.k_school", "op": "=", "value": "123456"}],
        "time": {},
        "grouping": {"group_by": ["wt30.position_title"], "order_by": []},
    }
    capabilities = {
        "dimensions": [
            {"column_key": "wt30.k_school", "column_name": "k_school", "filterable": True},
            {"column_key": "wt20.school_name", "column_name": "school_name", "filterable": True},
        ],
        "filter_columns": [
            {"column_key": "wt30.k_school", "column_name": "k_school", "filterable": True},
            {"column_key": "wt20.school_name", "column_name": "school_name", "filterable": True},
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, debug_rows = _normalize_school_name_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show me the principal and school id for Barksdale Elementary",
    )

    assert issues == []
    assert normalized["filters"][0]["column_key"] == "wt30.k_school"
    assert debug_rows == []
