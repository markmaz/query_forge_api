from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.domain_resolver import (
    DomainPlan,
    DomainPlanJoin,
    DomainPlanTable,
    DomainResolver,
    ResolvedDomainFrom,
    _safe_fqn,
)
from tests._support.fakes import FakeSQLExecutor


def test_safe_fqn_rejects_invalid() -> None:
    with pytest.raises(ServiceError):
        _safe_fqn("bad name")
    with pytest.raises(ServiceError):
        _safe_fqn("too.many.parts.name")


def test_resolve_plan_builds_aliases() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {
                "workspace_table_id": 10,
                "table_alias": "pt",
                "is_primary": 1,
                "sort_order": 0,
                "filter_mode": "AUTO",
                "cardinality": "ONE",
                "column_name_policy": "DEDUP_PRIMARY_FIRST",
                "full_name": "main.asset.patients",
            },
            {
                "workspace_table_id": 11,
                "table_alias": None,
                "is_primary": 0,
                "sort_order": 1,
                "filter_mode": "WHERE",
                "cardinality": "MANY",
                "column_name_policy": "DEDUP_PRIMARY_FIRST",
                "full_name": "main.asset.codes",
            },
        ],
        [
            {
                "id": 1,
                "from_workspace_table_id": 10,
                "to_workspace_table_id": 11,
                "join_type": "INNER",
                "join_spec_json": {"on": []},
                "sort_order": 0,
            }
        ],
    ]

    resolver = DomainResolver(workspace_id="ws1", sql=sql)
    plan = resolver.resolve_plan(1)

    assert plan.primary.workspace_table_id == 10
    assert plan.alias_by_workspace_table_id[10] == "pt"
    assert plan.alias_by_workspace_table_id[11] == "t0"
    assert plan.joins[0].join_type == "INNER"


def test_resolve_plan_requires_alias_for_show_all() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {
                "workspace_table_id": 10,
                "table_alias": None,
                "is_primary": 1,
                "sort_order": 0,
                "filter_mode": "AUTO",
                "cardinality": "ONE",
                "column_name_policy": "SHOW_ALL_QUALIFIED",
                "full_name": "main.asset.patients",
            },
            {
                "workspace_table_id": 11,
                "table_alias": "dx",
                "is_primary": 0,
                "sort_order": 1,
                "filter_mode": "AUTO",
                "cardinality": "ONE",
                "column_name_policy": "SHOW_ALL_QUALIFIED",
                "full_name": "main.asset.codes",
            },
        ],
        [],
    ]
    resolver = DomainResolver(workspace_id="ws1", sql=sql)
    with pytest.raises(ServiceError, match="table_alias is required"):
        resolver.resolve_plan(1)


def test_resolve_plan_rejects_invalid_filter_mode() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {
                "workspace_table_id": 10,
                "table_alias": "pt",
                "is_primary": 1,
                "sort_order": 0,
                "filter_mode": "BAD",
                "cardinality": "ONE",
                "column_name_policy": "DEDUP_PRIMARY_FIRST",
                "full_name": "main.asset.patients",
            }
        ],
        [],
    ]
    resolver = DomainResolver(workspace_id="ws1", sql=sql)
    with pytest.raises(ServiceError, match="Invalid filter_mode"):
        resolver.resolve_plan(1)


def test_get_join_path_finds_route() -> None:
    plan = DomainPlan(
        primary=DomainPlanTable(
            workspace_table_id=1,
            full_name="main.asset.patients",
            alias="t0",
            table_alias="pt",
            is_primary=True,
            sort_order=0,
            filter_mode="AUTO",
            cardinality="ONE",
        ),
        tables=[],
        joins=[
            DomainPlanJoin(
                join_id="1",
                from_workspace_table_id=1,
                to_workspace_table_id=2,
                join_type="INNER",
                join_spec={"on": []},
                sort_order=0,
            ),
            DomainPlanJoin(
                join_id="2",
                from_workspace_table_id=2,
                to_workspace_table_id=3,
                join_type="LEFT",
                join_spec={"on": []},
                sort_order=1,
            ),
        ],
        alias_by_workspace_table_id={},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )

    resolver = DomainResolver(workspace_id="ws1", sql=FakeSQLExecutor())
    path = resolver.get_join_path(plan, 3)
    assert [p.join_id for p in path] == ["1", "2"]

    with pytest.raises(ServiceError, match="Join path not found"):
        resolver.get_join_path(plan, 99)


def test_resolve_ambiguous_raises() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {"workspace_table_id": 1, "full_name": "main.asset.patients"},
            {"workspace_table_id": 2, "full_name": "main.asset.patients_two"},
        ]
    ]
    resolver = DomainResolver(workspace_id="ws1", sql=sql)
    with pytest.raises(ServiceError, match="maps to multiple workspace tables"):
        resolver.resolve(1)


def test_resolve_fallback() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [],
        [{"workspace_table_id": 9, "full_name": "main.asset.fallback"}],
    ]
    resolver = DomainResolver(workspace_id="ws1", sql=sql)
    resolved = resolver.resolve(1)
    assert isinstance(resolved, ResolvedDomainFrom)
    assert resolved.workspace_table_id == 9
