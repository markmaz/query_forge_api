from __future__ import annotations

from app.services.planner_domain.normalizers.entity import _normalize_country_filters_in_plan
from app.services.planner_domain.validate_v2 import validate_and_repair_plan_v2


def test_apply_normalization_to_plan_filters() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt24.k_student"}], "metrics": []},
        "filters": [{"column_key": "wt24.birth_country", "op": "ne", "value": "United States"}],
        "time": {},
        "grouping": {"group_by": ["wt24.k_student"], "order_by": []},
    }
    capabilities = {
        "dimensions": [
            {
                "column_key": "wt24.k_student",
                "filterable": True,
                "column_name": "k_student",
                "data_type": "string",
            }
        ],
        "filter_columns": [
            {
                "column_key": "wt24.birth_country",
                "filterable": True,
                "column_name": "birth_country",
                "data_type": "string",
            }
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, _debug = _normalize_country_filters_in_plan(plan_json=plan, capabilities=capabilities)
    assert issues == []
    assert normalized["filters"][0]["column_key"] == "wt24.birth_country"
    assert normalized["filters"][0]["op"] == "ne"
    assert normalized["filters"][0]["value"] == "US"


def test_unresolved_country_marks_invalid() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt24.k_student"}], "metrics": []},
        "filters": [{"column_key": "wt24.birth_country", "op": "eq", "value": "Wakanda"}],
        "time": {},
        "grouping": {"group_by": ["wt24.k_student"], "order_by": []},
    }
    capabilities = {
        "dimensions": [
            {
                "column_key": "wt24.k_student",
                "filterable": True,
                "column_name": "k_student",
                "data_type": "string",
            }
        ],
        "filter_columns": [
            {
                "column_key": "wt24.birth_country",
                "filterable": True,
                "column_name": "birth_country",
                "data_type": "string",
            }
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    normalized, issues, _debug = _normalize_country_filters_in_plan(plan_json=plan, capabilities=capabilities)
    assert normalized["filters"] == []
    assert any(item["code"] == "unresolved_filter_value" for item in issues)

    validated = validate_and_repair_plan_v2(
        plan_json=normalized,
        capabilities=capabilities,
        prompt="students not born in wakanda",
        expected_base_domain_id=6,
        extra_issues=issues,
    )
    assert validated.is_valid is False
    assert any(item["code"] == "unresolved_filter_value" for item in validated.issues)
