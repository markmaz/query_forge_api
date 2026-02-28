from __future__ import annotations

from app.services.planner_llm.validate import validate_and_repair


def _candidates():
    return {
        "columns": [
            {
                "column_key": "wt1.school_name",
                "column_name": "school_name",
                "data_type": "varchar",
                "semantic_type_strict": "dimension",
                "pii_flag": False,
            },
            {
                "column_key": "wt1.student_name",
                "column_name": "student_name",
                "data_type": "varchar",
                "semantic_type_strict": "dimension",
                "pii_flag": True,
            },
            {
                "column_key": "wt2.enrollment_count",
                "column_name": "enrollment_count",
                "data_type": "int",
                "semantic_type_strict": "metric",
                "pii_flag": False,
            },
            {
                "column_key": "wt2.school_year",
                "column_name": "school_year",
                "data_type": "date",
                "semantic_type_strict": "time",
                "pii_flag": False,
            },
        ]
    }


def test_validate_repairs_prompt_as_filter_value() -> None:
    prompt = "show students in montgomery county"
    plan = {
        "intent": "list",
        "grain": {"entity": "student", "time_grain": None},
        "selects": {"metrics": [], "dimensions": [{"column_key": "wt1.school_name"}]},
        "filters": [{"column_key": "wt1.school_name", "op": "equals", "value": prompt}],
        "domains": [1],
        "aggregation": {"group_by": [], "metrics": []},
        "derived_metrics": [],
    }
    out = validate_and_repair(
        plan_json=plan,
        candidates=_candidates(),
        normalized_prompt=prompt,
        allow_pii=True,
    )
    assert any("prompt" in err for err in out.errors)
    assert out.plan_json["filters"] == []


def test_validate_rejects_and_repairs_pii_when_disallowed() -> None:
    plan = {
        "intent": "list",
        "grain": {"entity": "student", "time_grain": None},
        "selects": {"metrics": [], "dimensions": [{"column_key": "wt1.student_name"}]},
        "filters": [{"column_key": "wt1.student_name", "op": "equals", "value": "Alice"}],
        "domains": [1],
        "aggregation": {"group_by": ["wt1.student_name"], "metrics": []},
        "derived_metrics": [],
    }
    out = validate_and_repair(
        plan_json=plan,
        candidates=_candidates(),
        normalized_prompt="list students named alice",
        allow_pii=False,
    )
    assert "dropped_pii_columns" in out.repairs_applied
    assert any("pii" in err for err in out.errors)
    assert out.plan_json["selects"]["dimensions"] == []


def test_validate_repairs_bad_avg_aggregate() -> None:
    plan = {
        "intent": "aggregate",
        "grain": {"entity": "student", "time_grain": None},
        "selects": {"metrics": [], "dimensions": [{"column_key": "wt1.school_name"}]},
        "filters": [],
        "domains": [1],
        "aggregation": {
            "group_by": ["wt1.school_name"],
            "metrics": [{"column_key": "wt1.school_name", "agg": "avg", "label": "bad"}],
        },
        "derived_metrics": [],
    }
    out = validate_and_repair(
        plan_json=plan,
        candidates=_candidates(),
        normalized_prompt="average school name",
        allow_pii=True,
    )
    assert out.plan_json["aggregation"]["metrics"][0]["agg"] == "count"
    assert "repaired_bad_aggregate_types" in out.repairs_applied


def test_validate_promotes_existing_derived_metric_when_not_referenced() -> None:
    plan = {
        "intent": "aggregate",
        "grain": {"entity": "student", "time_grain": None},
        "selects": {"metrics": [], "dimensions": [{"column_key": "wt1.school_name"}]},
        "filters": [],
        "domains": [1],
        "aggregation": {"group_by": ["wt1.school_name"], "metrics": []},
        "derived_metrics": [
            {
                "name": "students_per_teacher_ratio",
                "kind": "ratio",
                "numerator": {"column_key": "wt2.enrollment_count", "agg": "count_distinct"},
                "denominator": {"column_key": "wt2.enrollment_count", "agg": "count_distinct"},
                "safe_divide": True,
            }
        ],
    }
    out = validate_and_repair(
        plan_json=plan,
        candidates=_candidates(),
        normalized_prompt="students per teacher by school",
        allow_pii=True,
    )
    assert out.is_valid is True
    assert out.plan_json["selects"]["metrics"][0]["metric_ref"] == "derived:students_per_teacher_ratio"
    assert out.plan_json["aggregation"]["metrics"][0]["metric_ref"] == "derived:students_per_teacher_ratio"
    assert "promoted_derived_metric_to_selected" in out.repairs_applied
