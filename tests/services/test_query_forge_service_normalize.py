from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.domain_resolver import DomainPlan, DomainPlanTable
from app.services.query_forge_service import QueryForgeService
from tests._support.fakes import FakeDomainResolver, FakeForgeQueryPort


def _svc() -> QueryForgeService:
    return QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeDomainResolver())


def test_normalize_requires_domain() -> None:
    svc = _svc()
    with pytest.raises(ForgeError):
        svc.normalize({})
    with pytest.raises(ForgeError, match="domainId is required"):
        svc.normalize({"domainId": None, "columns": [{"columnName": "id"}]})


def test_normalize_validates_distinct_type() -> None:
    svc = _svc()
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "distinct": "yes"})


def test_normalize_columns_type() -> None:
    svc = _svc()
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": "bad"})
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": ["bad"]})
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{}]})
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id", "alias": 123}]})
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id", "exprId": 123}]})
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id", "workspaceTableId": "x"}]})


def test_normalize_columns_accepts_field_and_col_shapes() -> None:
    svc = _svc()
    q = svc.normalize(
        {
            "domainId": 1,
            "columns": [
                {
                    "field": {
                        "modelColumnId": 101,
                        "columnName": "first_name",
                        "workspaceTableId": 24,
                        "exprId": None,
                    },
                    "alias": "first_name",
                },
                {
                    "col": {
                        "modelColumnId": 102,
                        "columnName": "last_name",
                        "workspaceTableId": 24,
                        "exprId": None,
                    },
                    "alias": "last_name",
                },
            ],
        }
    )
    assert q["columns"][0]["columnName"] == "first_name"
    assert q["columns"][0]["modelColumnId"] == 101
    assert q["columns"][0]["workspaceTableId"] == 24
    assert q["columns"][0]["alias"] == "first_name"
    assert q["columns"][1]["columnName"] == "last_name"
    assert q["columns"][1]["modelColumnId"] == 102
    assert q["columns"][1]["workspaceTableId"] == 24
    assert q["columns"][1]["alias"] == "last_name"


def test_normalize_columns_field_shape_validation() -> None:
    svc = _svc()
    with pytest.raises(ForgeError, match="columns\\[0\\]\\.field must be an object"):
        svc.normalize({"domainId": 1, "columns": [{"field": "bad"}]})
    with pytest.raises(ForgeError, match="columns\\[0\\]\\.col must be an object"):
        svc.normalize({"domainId": 1, "columns": [{"col": "bad"}]})


def test_normalize_rejects_qualified_column() -> None:
    svc = _svc()
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "t.id"}]})


def test_normalize_aggs_validations() -> None:
    svc = _svc()
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "aggs": {"groupBy": "bad"}})
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "aggs": {"metrics": "bad"}})
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "aggs": "bad"})
    with pytest.raises(ForgeError):
        svc.normalize(
            {
                "domainId": 1,
                "columns": [{"columnName": "id"}],
                "aggs": {"metrics": [{"fn": "count", "label": 12}], "groupBy": []},
            }
        )
    with pytest.raises(ForgeError):
        svc.normalize(
            {
                "domainId": 1,
                "columns": [{"columnName": "id"}],
                "aggs": {"metrics": [{"fn": "count", "id": 12}], "groupBy": []},
            }
        )


def test_normalize_aggs_defaults_and_metrics_column_field() -> None:
    svc = _svc()
    q = svc.normalize(
        {
            "domainId": 1,
            "columns": [{"columnName": "id"}],
            "aggs": None,
            "sorting": [],
        }
    )
    assert q["aggs"]["enabled"] is False

    q = svc.normalize(
        {
            "domainId": 1,
            "columns": [{"columnName": "id"}],
            "aggs": {"metrics": [{"fn": "count", "column": {"columnName": "id"}}], "groupBy": []},
            "sorting": [],
        }
    )
    assert q["aggs"]["metrics"][0]["field"]["columnName"] == "id"


def test_normalize_aggs_accepts_agg_alias_for_fn() -> None:
    svc = _svc()
    q = svc.normalize(
        {
            "domainId": 1,
            "columns": [{"columnName": "id"}],
            "aggs": {"metrics": [{"agg": "count", "field": {"columnName": "id"}}], "groupBy": []},
            "sorting": [],
        }
    )
    assert q["aggs"]["metrics"][0]["fn"] == "count"
    assert q["aggs"]["metrics"][0]["field"]["columnName"] == "id"


def test_normalize_aggs_parses_function_style_metric_fn() -> None:
    svc = _svc()
    q = svc.normalize(
        {
            "domainId": 1,
            "columns": [{"columnName": "id"}],
            "aggs": {"metrics": [{"fn": "count(id)"}], "groupBy": []},
            "sorting": [],
        }
    )
    assert q["aggs"]["metrics"][0]["fn"] == "count"
    assert q["aggs"]["metrics"][0]["field"]["columnName"] == "id"


def test_normalize_aggs_defaults_to_count_when_field_present_and_fn_missing() -> None:
    svc = _svc()
    q = svc.normalize(
        {
            "domainId": 1,
            "columns": [{"columnName": "id"}],
            "aggs": {"metrics": [{"field": {"columnName": "id"}}], "groupBy": []},
            "sorting": [],
        }
    )
    assert q["aggs"]["metrics"][0]["fn"] == "count"
    assert q["aggs"]["metrics"][0]["field"]["columnName"] == "id"


def test_normalize_aggs_accepts_metric_ref_object_shape() -> None:
    svc = _svc()
    q = svc.normalize(
        {
            "domainId": 7,
            "columns": [{"workspaceTableId": 24, "modelColumnId": 363, "columnName": "grade_level"}],
            "aggs": {
                "enabled": True,
                "metrics": [
                    {
                        "id": "domain_metric:enrollment_count",
                        "metricRef": {
                            "type": "column",
                            "columnKey": {
                                "workspaceTableId": 24,
                                "modelColumnId": 363,
                                "columnName": "grade_level",
                                "exprId": None,
                                "alias": None,
                            },
                            "agg": "count",
                            "label": "Enrollment Count",
                        },
                    }
                ],
                "groupBy": [{"workspaceTableId": 24, "modelColumnId": 363, "columnName": "grade_level"}],
            },
            "sorting": [],
        }
    )
    assert q["aggs"]["metrics"][0]["fn"] == "count"
    assert q["aggs"]["metrics"][0]["field"]["columnName"] == "grade_level"
    assert q["aggs"]["metrics"][0]["field"]["workspaceTableId"] == 24
    assert q["aggs"]["metrics"][0]["label"] == "Enrollment Count"


def test_normalize_aggs_count_allows_empty_field_object() -> None:
    svc = _svc()
    q = svc.normalize(
        {
            "domainId": 1,
            "columns": [{"columnName": "id"}],
            "aggs": {
                "enabled": True,
                "metrics": [
                    {
                        "id": "semantic_plan_metric_count",
                        "fn": "count",
                        "field": {
                            "modelColumnId": None,
                            "workspaceTableId": None,
                            "exprId": None,
                            "alias": None,
                        },
                        "label": "count",
                    }
                ],
                "groupBy": [],
            },
            "sorting": [],
        }
    )
    assert q["aggs"]["metrics"][0]["fn"] == "count"
    assert q["aggs"]["metrics"][0]["field"] is None


def test_normalize_metrics_item_not_object() -> None:
    svc = _svc()
    with pytest.raises(ForgeError):
        svc.normalize(
            {
                "domainId": 1,
                "columns": [{"columnName": "id"}],
                "aggs": {"metrics": ["bad"], "groupBy": []},
            }
        )


def test_normalize_data_prep_rules_type() -> None:
    svc = _svc()
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "dataPrep": {"rules": {}}})


def test_normalize_data_prep_invalid_type() -> None:
    svc = _svc()
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "dataPrep": "bad"})


def test_normalize_sorting_errors() -> None:
    svc = _svc()
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "sorting": ["bad"]})
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "sorting": [{"dir": "up"}]})
    with pytest.raises(ForgeError):
        svc.normalize(
            {
                "domainId": 1,
                "columns": [{"columnName": "id"}],
                "sorting": [{"columnName": {"columnName": "id"}, "dir": "up"}],
            }
        )


def test_normalize_sorting_requires_list() -> None:
    svc = _svc()
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "sorting": "bad"})


def test_normalize_sorting_col_key() -> None:
    svc = _svc()
    q = svc.normalize(
        {
            "domainId": 1,
            "columns": [{"columnName": "id"}],
            "sorting": [{"col": {"columnName": "id"}, "dir": "asc"}],
        }
    )
    assert q["sorting"][0]["col"]["columnName"] == "id"


def test_normalize_requires_columns_or_aggs() -> None:
    svc = _svc()
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [], "aggs": {"enabled": False}})


def test_normalize_col_key() -> None:
    svc = _svc()
    assert svc._qf_norm_col_key("id", "path")["columnName"] == "id"
    with pytest.raises(ForgeError):
        svc._qf_norm_col_key("t.id", "path")
    with pytest.raises(ForgeError):
        svc._qf_norm_col_key("  ", "path")
    with pytest.raises(ForgeError):
        svc._qf_norm_col_key({}, "path")
    with pytest.raises(ForgeError):
        svc._qf_norm_col_key({"columnName": "id", "modelColumnId": "bad"}, "path")
    with pytest.raises(ForgeError):
        svc._qf_norm_col_key({"columnName": "id", "exprId": 123}, "path")
    with pytest.raises(ForgeError):
        svc._qf_norm_col_key({"columnName": "bad.name"}, "path")
    with pytest.raises(ForgeError):
        svc._qf_norm_col_key({"columnName": "id", "workspaceTableId": "bad"}, "path")


def test_compile_invalid_mode() -> None:
    svc = _svc()
    with pytest.raises(ForgeError):
        svc.compile({"domainId": 1, "columns": [{"columnName": "id"}]}, mode="bad")


def test_compile_distinct_with_aggs_rejected() -> None:
    primary = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.table",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="WHERE",
        cardinality="ONE",
    )
    plan = DomainPlan(
        primary=primary,
        tables=[primary],
        joins=[],
        alias_by_workspace_table_id={1: "t0"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeDomainResolver(plan))
    with pytest.raises(ForgeError):
        svc.compile(
            {"domainId": 1, "columns": [{"columnName": "id"}], "aggs": {"enabled": True, "groupBy": [], "metrics": []}, "distinct": True},
        )


def test_normalize_accepts_selects_and_derived_metrics_shape() -> None:
    svc = _svc()
    q = svc.normalize(
        {
            "domainId": 1,
            "selects": {
                "dimensions": ["wt1.id"],
                "metrics": [{"metricRef": "derived:students_per_teacher_ratio"}],
            },
            "derived_metrics": [
                {
                    "kind": "ratio",
                    "name": "students_per_teacher_ratio",
                    "numerator": {"columnKey": "wt1.id", "agg": "count_distinct"},
                    "denominator": {"columnKey": "wt1.id", "agg": "count_distinct"},
                    "safeDivide": True,
                }
            ],
        }
    )
    assert q["aggs"]["enabled"] is True
    assert q["aggs"]["metrics"][0]["fn"] == "expr"
    assert q["aggs"]["metrics"][0]["expr"]["kind"] == "ratio"
    assert q["aggs"]["groupBy"][0]["workspaceTableId"] == 1
