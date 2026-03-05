from __future__ import annotations

from app.services.planner_domain.service import _normalize_next_actions


def test_next_actions_remap_keys_by_unique_column_name() -> None:
    capabilities = {
        "dimensions": [
            {"column_key": "wt20.school_name"},
            {"column_key": "wt20.lea_name"},
            {"column_key": "wt24.first_name"},
        ],
        "filter_columns": [
            {"column_key": "wt20.school_name", "filterable": True},
            {"column_key": "wt20.lea_name", "filterable": True},
        ],
        "time_columns": [],
        "domain_metrics": [{"metric_key": "adm_total"}],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    actions = [
        {
            "label": "By District",
            "prompt": "Show ADM by district for this school",
            "reason": "Rolls up the same scope by LEA.",
            "intent": "aggregate",
            "dimensions": ["wt34.lea_name"],
            "filters": [
                {"column_key": "wt34.school_name", "op": "eq", "value": "Barksdale Elementary"},
                {"column_key": "wt999.unknown", "op": "eq", "value": "x"},
            ],
            "metrics": ["domain_metric:adm_total"],
        }
    ]

    out = _normalize_next_actions(
        actions=actions,
        original_prompt="Show me the ADM for the 2026 school year for Holden Black",
        capabilities=capabilities,
        max_items=3,
    )

    assert len(out) == 1
    assert out[0]["dimensions"] == ["wt20.lea_name"]
    assert out[0]["filters"] == [{"column_key": "wt20.school_name", "op": "eq", "value": "Barksdale Elementary"}]


def test_next_actions_drop_aggregate_item_with_no_valid_metric() -> None:
    capabilities = {
        "dimensions": [{"column_key": "wt20.school_name"}],
        "filter_columns": [{"column_key": "wt20.school_name", "filterable": True}],
        "time_columns": [],
        "domain_metrics": [{"metric_key": "adm_total"}],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    actions = [
        {
            "label": "Bad Aggregate",
            "prompt": "Aggregate with invalid metric",
            "reason": "Should be dropped because aggregate requires a valid metric.",
            "intent": "aggregate",
            "dimensions": ["wt20.school_name"],
            "filters": [{"column_key": "wt20.school_name", "op": "eq", "value": "Barksdale Elementary"}],
            "metrics": ["domain_metric:not_real"],
        }
    ]

    out = _normalize_next_actions(
        actions=actions,
        original_prompt="Show me ADM by school",
        capabilities=capabilities,
        max_items=3,
    )

    assert out == []
