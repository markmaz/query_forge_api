from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.domain_resolver import DomainPlan, DomainPlanTable
from app.services.no_code_query_service import NoCodeQueryService
from tests._support.fakes import FakeDomainResolver, FakeSQLExecutor


def _svc() -> NoCodeQueryService:
    return NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeDomainResolver())


def test_normalize_requires_domain() -> None:
    svc = _svc()
    with pytest.raises(ServiceError):
        svc.normalize({})
    with pytest.raises(ServiceError, match="domainId is required"):
        svc.normalize({"domainId": None, "columns": [{"columnName": "id"}]})


def test_normalize_validates_distinct_type() -> None:
    svc = _svc()
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "distinct": "yes"})


def test_normalize_columns_type() -> None:
    svc = _svc()
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": "bad"})
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": ["bad"]})
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [{}]})
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id", "alias": 123}]})
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id", "exprId": 123}]})
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id", "workspaceTableId": "x"}]})


def test_normalize_rejects_qualified_column() -> None:
    svc = _svc()
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "t.id"}]})


def test_normalize_aggs_validations() -> None:
    svc = _svc()
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "aggs": {"groupBy": "bad"}})
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "aggs": {"metrics": "bad"}})
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "aggs": "bad"})
    with pytest.raises(ServiceError):
        svc.normalize(
            {
                "domainId": 1,
                "columns": [{"columnName": "id"}],
                "aggs": {"metrics": [{"fn": "count", "label": 12}], "groupBy": []},
            }
        )
    with pytest.raises(ServiceError):
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


def test_normalize_metrics_item_not_object() -> None:
    svc = _svc()
    with pytest.raises(ServiceError):
        svc.normalize(
            {
                "domainId": 1,
                "columns": [{"columnName": "id"}],
                "aggs": {"metrics": ["bad"], "groupBy": []},
            }
        )


def test_normalize_data_prep_rules_type() -> None:
    svc = _svc()
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "dataPrep": {"rules": {}}})


def test_normalize_data_prep_invalid_type() -> None:
    svc = _svc()
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "dataPrep": "bad"})


def test_normalize_sorting_errors() -> None:
    svc = _svc()
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "sorting": ["bad"]})
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "sorting": [{"dir": "up"}]})
    with pytest.raises(ServiceError):
        svc.normalize(
            {
                "domainId": 1,
                "columns": [{"columnName": "id"}],
                "sorting": [{"columnName": {"columnName": "id"}, "dir": "up"}],
            }
        )


def test_normalize_sorting_requires_list() -> None:
    svc = _svc()
    with pytest.raises(ServiceError):
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
    with pytest.raises(ServiceError):
        svc.normalize({"domainId": 1, "columns": [], "aggs": {"enabled": False}})


def test_normalize_col_key() -> None:
    svc = _svc()
    assert svc._normalize_col_key("id", "path")["columnName"] == "id"
    with pytest.raises(ServiceError):
        svc._normalize_col_key("t.id", "path")
    with pytest.raises(ServiceError):
        svc._normalize_col_key("  ", "path")
    with pytest.raises(ServiceError):
        svc._normalize_col_key({}, "path")
    with pytest.raises(ServiceError):
        svc._normalize_col_key({"columnName": "id", "modelColumnId": "bad"}, "path")
    with pytest.raises(ServiceError):
        svc._normalize_col_key({"columnName": "id", "exprId": 123}, "path")
    with pytest.raises(ServiceError):
        svc._normalize_col_key({"columnName": "bad.name"}, "path")
    with pytest.raises(ServiceError):
        svc._normalize_col_key({"columnName": "id", "workspaceTableId": "bad"}, "path")


def test_compile_invalid_mode() -> None:
    svc = _svc()
    with pytest.raises(ServiceError):
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
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeDomainResolver(plan))
    with pytest.raises(ServiceError):
        svc.compile(
            {"domainId": 1, "columns": [{"columnName": "id"}], "aggs": {"enabled": True, "groupBy": [], "metrics": []}, "distinct": True},
        )
