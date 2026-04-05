from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.domain_resolution.models import DomainPlan, DomainPlanJoin, DomainPlanTable
from app.services.query_forge.plan_inspector import QueryForgePlanInspector


def _plan() -> DomainPlan:
    primary = DomainPlanTable(
        workspace_table_id=10,
        full_name="main.students",
        alias="students",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="default",
        cardinality="one",
    )
    secondary = DomainPlanTable(
        workspace_table_id=20,
        full_name="main.enrollment",
        alias="enrollment",
        table_alias=None,
        is_primary=False,
        sort_order=1,
        filter_mode="default",
        cardinality="many",
    )
    join = DomainPlanJoin(
        join_id="j1",
        from_workspace_table_id=10,
        to_workspace_table_id=20,
        join_type="INNER",
        join_spec={"on": [{"left": {"columnName": "student_id"}, "right": {"columnName": "student_id"}}]},
        sort_order=0,
    )
    return DomainPlan(
        primary=primary,
        tables=[primary, secondary],
        joins=[join],
        alias_by_workspace_table_id={10: "students", 20: "enrollment"},
        column_name_policy="SHOW_ALL",
    )


class _Resolver:
    def __init__(self, *, path_exc: Exception | None = None, rows=None) -> None:
        self._workspace_id = "ws-1"
        self._sql = self
        self._path_exc = path_exc
        self._rows = list(rows or [])

    def get_join_path(self, plan: DomainPlan, to_workspace_table_id: int):
        del plan, to_workspace_table_id
        if self._path_exc is not None:
            raise self._path_exc
        return [
            DomainPlanJoin(
                join_id="j1",
                from_workspace_table_id=10,
                to_workspace_table_id=20,
                join_type="INNER",
                join_spec={"on": [{"left": {"columnName": "student_id"}, "right": {"columnName": "student_id"}}]},
                sort_order=0,
            )
        ]

    def execute_query_mappings(self, query: str, params: dict[str, object]):
        del query, params
        return list(self._rows)


def test_primary_join_key_candidates_tolerates_missing_join_paths() -> None:
    inspector = QueryForgePlanInspector(_Resolver(path_exc=ForgeError("missing", status_code=400)))  # type: ignore[arg-type]

    out = inspector.primary_join_key_candidates(plan=_plan(), primary_id=10, filter_only_table_ids={20})

    assert out == []


def test_primary_join_key_candidates_surfaces_unexpected_resolver_errors() -> None:
    inspector = QueryForgePlanInspector(_Resolver(path_exc=RuntimeError("broken resolver")))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="broken resolver"):
        inspector.primary_join_key_candidates(plan=_plan(), primary_id=10, filter_only_table_ids={20})


def test_primary_query_key_candidates_ignores_invalid_workspace_table_ids() -> None:
    out = QueryForgePlanInspector.primary_query_key_candidates(
        q={
            "columns": [{"columnName": "student_id", "workspaceTableId": "not-an-int"}],
            "sorting": [{"col": {"columnName": "student_id", "workspaceTableId": None}}],
        },
        primary_id=10,
    )

    assert out == ["student_id"]


def test_primary_query_key_candidates_surfaces_unexpected_workspace_table_id_errors() -> None:
    class _BadInt:
        def __int__(self) -> int:
            raise RuntimeError("bad table id")

    with pytest.raises(RuntimeError, match="bad table id"):
        QueryForgePlanInspector.primary_query_key_candidates(
            q={"columns": [{"columnName": "student_id", "workspaceTableId": _BadInt()}]},
            primary_id=10,
        )


def test_load_domain_column_catalog_ignores_bad_workspace_table_ids() -> None:
    inspector = QueryForgePlanInspector(
        _Resolver(rows=[{"workspace_table_id": "bad", "column_name": "student_id", "data_type": "INT"}])  # type: ignore[arg-type]
    )

    out = inspector.load_domain_column_catalog(_plan())

    assert out == {}


def test_load_domain_column_catalog_surfaces_unexpected_workspace_table_id_errors() -> None:
    class _BadInt:
        def __int__(self) -> int:
            raise RuntimeError("bad catalog row")

    inspector = QueryForgePlanInspector(
        _Resolver(rows=[{"workspace_table_id": _BadInt(), "column_name": "student_id", "data_type": "INT"}])  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="bad catalog row"):
        inspector.load_domain_column_catalog(_plan())
