from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.domain_resolver import DomainPlan, DomainPlanTable
from app.services.sqljson.validate_derived import validate_and_normalize_derived_sqljson


def _plan() -> DomainPlan:
    t0 = DomainPlanTable(20, "main.asset.dim_school", "t0", None, True, 0, "AUTO", "ONE")
    t1 = DomainPlanTable(30, "main.asset.fct_staff", "t1", None, False, 1, "AUTO", "MANY")
    t2 = DomainPlanTable(61, "main.asset.fct_student", "t2", None, False, 2, "AUTO", "MANY")
    return DomainPlan(
        primary=t0,
        tables=[t0, t1, t2],
        joins=[],
        alias_by_workspace_table_id={20: "t0", 30: "t1", 61: "t2"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )


def test_validate_and_normalize_selects_with_derived_ratio() -> None:
    q = {
        "domainId": 6,
        "selects": {
            "dimensions": ["wt20.county_fips_code"],
            "metrics": [{"metricRef": "derived:students_per_teacher_ratio"}],
        },
        "derived_metrics": [
            {
                "kind": "ratio",
                "name": "students_per_teacher_ratio",
                "numerator": {"columnKey": "wt61.k_student", "agg": "count_distinct"},
                "denominator": {"columnKey": "wt30.k_staff_school_association", "agg": "count_distinct"},
                "safeDivide": True,
            }
        ],
    }

    normalized, issues, meta = validate_and_normalize_derived_sqljson(q, plan=_plan(), strict=False)
    assert issues == []
    assert normalized["aggs"]["enabled"] is True
    assert normalized["aggs"]["groupBy"][0]["workspaceTableId"] == 20
    metric = normalized["aggs"]["metrics"][0]
    assert metric["fn"] == "expr"
    assert metric["expr"]["kind"] == "ratio"
    assert metric["expr"]["numerator"]["field"]["workspaceTableId"] == 61
    assert metric["expr"]["denominator"]["field"]["workspaceTableId"] == 30
    assert "students_per_teacher_ratio" in meta["derived_registry"]


def test_validate_and_normalize_reports_unknown_column_key() -> None:
    q = {
        "derived_metrics": [
            {
                "kind": "ratio",
                "name": "bad_ratio",
                "numerator": {"columnKey": "wt999.k_student", "agg": "count_distinct"},
                "denominator": {"columnKey": "wt30.k_staff_school_association", "agg": "count_distinct"},
            }
        ],
    }
    _, issues, _ = validate_and_normalize_derived_sqljson(q, plan=_plan(), strict=False)
    assert any(i["code"] == "unknown_column_key" for i in issues)


def test_validate_and_normalize_invalid_metric_type_raises_when_strict() -> None:
    q = {
        "derived_metrics": [
            {
                "kind": "ratio",
                "name": "bad_ratio",
                "numerator": {"columnKey": "wt61.k_student", "agg": "avg"},
                "denominator": {"columnKey": "wt30.k_staff_school_association", "agg": "count_distinct"},
            }
        ],
    }
    with pytest.raises(ServiceError, match="derived_validation_failed: invalid_metric_type"):
        validate_and_normalize_derived_sqljson(q, plan=_plan(), strict=True)
