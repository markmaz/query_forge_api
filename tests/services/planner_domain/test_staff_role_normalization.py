from __future__ import annotations

from app.services.planner_domain.normalizers.entity import _normalize_staff_role_filters_in_plan


def test_staff_role_filter_is_appended_when_prompt_mentions_single_role() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 5,
        "intent": "list",
        "selects": {
            "dimensions": [
                {"column_key": "wt20.school_name"},
                {"column_key": "wt23.first_name"},
                {"column_key": "wt23.last_name"},
                {"column_key": "wt30.position_title"},
            ],
            "metrics": [],
        },
        "filters": [{"column_key": "wt20.school_name", "op": "=", "value": "Barksdale Elementary"}],
        "time": {},
        "grouping": {
            "group_by": ["wt20.school_name", "wt23.first_name", "wt23.last_name", "wt30.position_title"],
            "order_by": [],
        },
    }
    capabilities = {
        "dimensions": [
            {"column_key": "wt30.position_title", "column_name": "position_title", "filterable": True},
            {"column_key": "wt20.school_name", "column_name": "school_name", "filterable": True},
        ],
        "filter_columns": [
            {"column_key": "wt30.position_title", "column_name": "position_title", "filterable": True},
            {"column_key": "wt20.school_name", "column_name": "school_name", "filterable": True},
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, debug_rows = _normalize_staff_role_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show me the principal for Barksdale Elementary",
    )

    assert issues == []
    assert any(item.get("column_key") == "wt30.position_title" and item.get("value") == "Principal" for item in normalized["filters"])
    assert debug_rows[0]["action"] == "appended_role_filter"


def test_staff_role_filter_is_not_duplicated_when_it_already_exists() -> None:
    plan = {
        "filters": [
            {"column_key": "wt20.school_name", "op": "=", "value": "Barksdale Elementary"},
            {"column_key": "wt30.position_title", "op": "=", "value": "Principal"},
        ]
    }
    capabilities = {
        "dimensions": [
            {"column_key": "wt30.position_title", "column_name": "position_title", "filterable": True},
            {"column_key": "wt20.school_name", "column_name": "school_name", "filterable": True},
        ],
        "filter_columns": [
            {"column_key": "wt30.position_title", "column_name": "position_title", "filterable": True},
            {"column_key": "wt20.school_name", "column_name": "school_name", "filterable": True},
        ],
        "time_columns": [],
    }

    normalized, issues, debug_rows = _normalize_staff_role_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show me the principal for Barksdale Elementary",
    )

    assert issues == []
    role_filters = [item for item in normalized["filters"] if item.get("column_key") == "wt30.position_title"]
    assert len(role_filters) == 1
    assert debug_rows[0]["action"] == "skip_existing_role_filter"

