from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.domain_resolver import DomainPlan, DomainPlanJoin, DomainPlanTable
from app.services.query_forge_service import QF_MAX_MANUAL_IN, TABLE_BY_TYPE, QueryForgeService
from tests._support.fakes import FakeForgeQueryPort


class FakeResolver:
    def __init__(
        self,
        plan: DomainPlan,
        *,
        paths: dict[int, list[DomainPlanJoin]] | None = None,
        workspace_id: str | None = "ws",
    ) -> None:
        self._plan = plan
        self._paths = paths or {}
        self._workspace_id = workspace_id

    def resolve_plan(self, domain_id: int) -> DomainPlan:
        del domain_id
        return self._plan

    def get_join_path(self, plan: DomainPlan, to_workspace_table_id: int) -> list[DomainPlanJoin]:
        del plan
        return list(self._paths.get(int(to_workspace_table_id), []))

class ArrayExec(FakeForgeQueryPort):
    supports_array_params = True


class NoArrayExec(FakeForgeQueryPort):
    supports_array_params = False


def _single_table_plan() -> DomainPlan:
    table = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.people",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="WHERE",
        cardinality="ONE",
    )
    return DomainPlan(
        primary=table,
        tables=[table],
        joins=[],
        alias_by_workspace_table_id={1: "t0"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )


def _two_table_plan(filter_mode_secondary: str = "AUTO") -> tuple[DomainPlan, DomainPlanJoin]:
    primary = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.patients",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="WHERE",
        cardinality="ONE",
    )
    secondary = DomainPlanTable(
        workspace_table_id=2,
        full_name="main.asset.codes",
        alias="t1",
        table_alias=None,
        is_primary=False,
        sort_order=1,
        filter_mode=filter_mode_secondary,
        cardinality="MANY",
    )
    join = DomainPlanJoin(
        join_id="j1",
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="LEFT",
        join_spec={
            "on": [
                {
                    "left": {"columnName": "patient_id"},
                    "right": {"columnName": "patient_id"},
                }
            ]
        },
        sort_order=0,
    )
    plan = DomainPlan(
        primary=primary,
        tables=[primary, secondary],
        joins=[join],
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    return plan, join


def _three_table_plan() -> tuple[DomainPlan, DomainPlanJoin, DomainPlanJoin]:
    primary = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.patients",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="WHERE",
        cardinality="ONE",
    )
    filter_only = DomainPlanTable(
        workspace_table_id=2,
        full_name="main.asset.codes",
        alias="t1",
        table_alias=None,
        is_primary=False,
        sort_order=1,
        filter_mode="AUTO",
        cardinality="MANY",
    )
    projected = DomainPlanTable(
        workspace_table_id=3,
        full_name="main.asset.visits",
        alias="t2",
        table_alias=None,
        is_primary=False,
        sort_order=2,
        filter_mode="AUTO",
        cardinality="MANY",
    )
    join_filter = DomainPlanJoin(
        join_id="j1",
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="LEFT",
        join_spec={
            "on": [
                {
                    "left": {"columnName": "patient_id"},
                    "right": {"columnName": "patient_id"},
                }
            ]
        },
        sort_order=0,
    )
    join_projected = DomainPlanJoin(
        join_id="j2",
        from_workspace_table_id=1,
        to_workspace_table_id=3,
        join_type="LEFT",
        join_spec={
            "on": [
                {
                    "left": {"columnName": "patient_id"},
                    "right": {"columnName": "patient_id"},
                }
            ]
        },
        sort_order=1,
    )
    plan = DomainPlan(
        primary=primary,
        tables=[primary, filter_only, projected],
        joins=[join_filter, join_projected],
        alias_by_workspace_table_id={1: "t0", 2: "t1", 3: "t2"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    return plan, join_filter, join_projected


def _staff_two_table_plan() -> tuple[DomainPlan, DomainPlanJoin]:
    primary = DomainPlanTable(
        workspace_table_id=23,
        full_name="main.asset.staff",
        alias="staff",
        table_alias="staff",
        is_primary=True,
        sort_order=0,
        filter_mode="WHERE",
        cardinality="ONE",
    )
    secondary = DomainPlanTable(
        workspace_table_id=30,
        full_name="main.asset.staff_assignment",
        alias="assign",
        table_alias="assign",
        is_primary=False,
        sort_order=1,
        filter_mode="AUTO",
        cardinality="MANY",
    )
    join = DomainPlanJoin(
        join_id="j_staff",
        from_workspace_table_id=23,
        to_workspace_table_id=30,
        join_type="LEFT",
        join_spec={
            "on": [
                {
                    "left": {"columnName": "k_person"},
                    "right": {"columnName": "k_person"},
                }
            ]
        },
        sort_order=0,
    )
    plan = DomainPlan(
        primary=primary,
        tables=[primary, secondary],
        joins=[join],
        alias_by_workspace_table_id={23: "staff", 30: "assign"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    return plan, join


def _compile_where_with_params(
    svc: QueryForgeService,
    node: dict | None,
    plan: DomainPlan,
    *,
    alias_by_wt: dict | None = None,
    force_exists_for_tables: set[int] | None = None,
) -> tuple[str, list[str], dict]:
    params: dict = {}
    counter = 0

    def new_param(val):
        nonlocal counter
        counter += 1
        params[f"p{counter}"] = val
        return f":p{counter}"

    where_sql, exists_parts = svc._compile_where(
        node,
        {},
        {},
        {},
        {},
        False,
        "t0",
        alias_by_wt or {1: "t0"},
        plan,
        new_param,
        force_exists_for_tables=force_exists_for_tables,
    )
    return where_sql, exists_parts, params


def test_normalize_filters_collapses_or_equals() -> None:
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeResolver(_single_table_plan()))
    node = {
        "type": "group",
        "id": "g1",
        "match": "or",
        "children": [
            {"type": "condition", "field": {"columnName": "code"}, "op": "equals", "value": "A"},
            {"type": "condition", "field": {"columnName": "code"}, "op": "equals", "value": "B"},
        ],
    }
    out = svc._qf_norm_filters(node)
    assert out["op"] == "in"
    assert out["value"] == ["A", "B"]
    assert out["id"] == "g1"


@pytest.mark.parametrize(
    "node",
    [
        {"type": "group", "match": "or", "children": [{"type": "condition", "field": "x", "op": "gt", "value": 1}]},
        {"type": "group", "match": "or", "children": ["bad"]},
        {
            "type": "group",
            "match": "or",
            "children": [
                {"type": "condition", "field": {"columnName": "x"}, "op": "equals", "value": 1},
                {"type": "condition", "field": {"columnName": "y"}, "op": "equals", "value": 2},
            ],
        },
    ],
)
def test_normalize_filters_no_collapse(node: dict) -> None:
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeResolver(_single_table_plan()))
    out = svc._qf_norm_filters(node)
    assert out.get("type") == "group"


def test_normalize_value_override_attachments_dict_input() -> None:
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeResolver(_single_table_plan()))
    q = svc.normalize(
        {
            "domainId": 1,
            "columns": [{"columnName": "id"}],
            "value_overrideAttachments": {
                "a": {
                    "id": "cw1",
                    "listType": "regions",
                    "listId": "l1",
                    "mode": "join",
                    "domainJoinColumns": [{"columnName": "zip", "workspaceTableId": 1}],
                    "projectFields": ["region"],
                }
            },
        }
    )
    cw = q["value_overrideAttachments"][0]
    assert cw["value_overrideJoinColumns"] == ["zipcode"]
    assert q["cohortAttachment"] is None


def test_normalize_value_override_none_inputs() -> None:
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeResolver(_single_table_plan()))
    q = svc.normalize(
        {
            "domainId": 1,
            "columns": [{"columnName": "id"}],
            "value_overrideAttachments": None,
            "value_overrides": None,
        }
    )
    assert q["value_overrideAttachments"] == []


@pytest.mark.parametrize(
    "bad_cw",
    [
        "bad",
        {"listType": "bad", "listId": "l1", "mode": "join", "domainJoinColumns": []},
        {"listType": "regions", "listId": None, "mode": "join", "domainJoinColumns": []},
        {"listType": "regions", "listId": "l1", "mode": "bad", "domainJoinColumns": []},
        {"listType": "regions", "listId": "l1", "mode": "join", "domainJoinColumns": "bad"},
        {"listType": "regions", "listId": "l1", "mode": "join", "domainJoinColumns": [], "value_overrideJoinColumns": "bad"},
        {"listType": "regions", "listId": "l1", "mode": "join", "domainJoinColumns": [], "projectFields": "bad"},
    ],
)
def test_normalize_value_override_errors(bad_cw: object) -> None:
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeResolver(_single_table_plan()))
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "value_overrideAttachments": [bad_cw]})


@pytest.mark.parametrize("bad_ch", ["bad", {"mode": "filter", "cohortTableFullName": "x"}])
def test_normalize_cohort_errors(bad_ch: object) -> None:
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeResolver(_single_table_plan()))
    with pytest.raises(ForgeError, match="cohort functionality is no longer supported"):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "cohortAttachment": bad_ch})


def test_normalize_filters_or_children_non_condition() -> None:
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeResolver(_single_table_plan()))
    node = {
        "type": "group",
        "match": "or",
        "children": [
            {"type": "condition", "field": {"columnName": "id"}, "op": "equals", "value": 1},
            "bad",
        ],
    }
    normalized = svc._qf_norm_filters(node)
    assert normalized["children"][1] == "bad"

    node = {
        "type": "group",
        "match": "or",
        "children": [
            {"type": "condition", "field": {"columnName": "id"}, "op": "equals", "value": 1},
            {"type": "condition", "field": {"columnName": "id"}, "op": "gt", "value": 2},
        ],
    }
    normalized = svc._qf_norm_filters(node)
    assert normalized["children"][1]["op"] == "gt"


def test_normalize_value_override_domain_join_column() -> None:
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeResolver(_single_table_plan()))
    normalized = svc.normalize(
        {
            "domainId": 1,
            "columns": [{"columnName": "id"}],
            "value_overrideAttachments": [
                {
                    "listType": "regions",
                    "listId": "l1",
                    "mode": "join",
                    "domainJoinColumn": {"columnName": "zip"},
                }
            ],
        }
    )
    cw = normalized["value_overrideAttachments"][0]
    assert cw["domainJoinColumns"][0]["columnName"] == "zip"


def test_normalize_value_overrides_invalid_type() -> None:
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeResolver(_single_table_plan()))
    with pytest.raises(ForgeError):
        svc.normalize({"domainId": 1, "columns": [{"columnName": "id"}], "value_overrideAttachments": "bad"})


def test_attachment_required_table_ids() -> None:
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeResolver(_single_table_plan()))
    ids = svc._qf_attach_table_ids(
        [{"domainJoinColumns": [{"columnName": "id", "workspaceTableId": 2}]}],
        {"domainJoinColumn": {"columnName": "id"}},
        1,
    )
    assert ids == {1, 2}

    with pytest.raises(ForgeError):
        svc._qf_attach_table_ids(["bad"], None, 1)
    with pytest.raises(ForgeError):
        svc._qf_attach_table_ids([{"domainJoinColumns": "bad"}], None, 1)
    with pytest.raises(ForgeError):
        svc._qf_attach_table_ids([], "bad", 1)


def test_supports_array_params() -> None:
    svc = QueryForgeService(executor=ArrayExec(), domain_resolver=FakeResolver(_single_table_plan()))
    assert svc._qf_supports_array_params() is True

    svc = QueryForgeService(executor=NoArrayExec(), domain_resolver=FakeResolver(_single_table_plan()))
    assert svc._qf_supports_array_params() is False

    class DatabricksFoo:
        def submit_statement(self, *args, **kwargs):
            return {}

    svc = QueryForgeService(executor=DatabricksFoo(), domain_resolver=FakeResolver(_single_table_plan()))
    assert svc._qf_supports_array_params() is True


def test_filter_and_sorting_table_ids() -> None:
    plan = _single_table_plan()
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeResolver(plan))
    node = {
        "type": "group",
        "match": "and",
        "children": [
            {"type": "condition", "field": {"columnName": "x", "exprId": "e1"}, "op": "equals", "value": 1},
            {"type": "condition", "field": {"columnName": "x", "workspaceTableId": "bad"}, "op": "equals", "value": 1},
            {"type": "condition", "field": {"columnName": "x", "workspaceTableId": 0}, "op": "equals", "value": 1},
        ],
    }
    assert svc._qf_filter_table_ids(node, plan) == {1}
    assert svc._qf_filter_table_ids({"type": "mystery"}, plan) == set()

    sorting = ["bad", {"col": {"columnName": "x", "workspaceTableId": 1}, "dir": "asc"}, {"columnName": "x", "dir": "asc"}]
    assert svc._qf_sorting_table_ids(sorting, plan) == {1}
    sorting = [{"col": {"columnName": "x", "workspaceTableId": "bad"}, "dir": "asc"}]
    assert svc._qf_sorting_table_ids(sorting, plan) == set()


def test_safe_table_full_name_errors() -> None:
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=FakeResolver(_single_table_plan()))
    with pytest.raises(ForgeError):
        svc._safe_table_full_name("")
    with pytest.raises(ForgeError):
        svc._safe_table_full_name(".")


def test_compile_where_in_expands_and_parses_strings() -> None:
    plan = _single_table_plan()
    svc = QueryForgeService(executor=ArrayExec(), domain_resolver=FakeResolver(plan))

    node = {"type": "condition", "field": {"columnName": "code"}, "op": "in", "value": ["a", "b"]}
    where_sql, _exists, params = _compile_where_with_params(svc, node, plan)
    assert where_sql == "t0.code IN (:p1, :p2)"
    assert params == {"p1": "a", "p2": "b"}


def test_compile_where_in_normalization_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _single_table_plan()
    svc = QueryForgeService(executor=ArrayExec(), domain_resolver=FakeResolver(plan))

    node = {"type": "condition", "field": {"columnName": "code"}, "op": "in", "value": None}
    where_sql, _exists, params = _compile_where_with_params(svc, node, plan)
    assert where_sql == ""
    assert params == {}

    node = {"type": "condition", "field": {"columnName": "code"}, "op": "in", "value": 123}
    where_sql, _exists, params = _compile_where_with_params(svc, node, plan)
    assert where_sql == "t0.code IN (:p1)"
    assert params == {"p1": "123"}

    node = {
        "type": "condition",
        "field": {"columnName": "code"},
        "op": "in",
        "value": [None, "", " 'a' ", ' "b" '],
    }
    where_sql, _exists, params = _compile_where_with_params(svc, node, plan)
    assert where_sql == "t0.code IN (:p1, :p2)"
    assert params == {"p1": "a", "p2": "b"}

    node = {"type": "condition", "field": {"columnName": "code"}, "op": "in", "value": "[a]"}
    where_sql, _exists, params = _compile_where_with_params(svc, node, plan)
    assert where_sql == "t0.code IN (:p1)"
    assert params == {"p1": "[a]"}

    monkeypatch.setattr("app.services.query_forge_service.QF_MAX_MANUAL_IN", 500)
    values = [str(i) for i in range(201)]
    node = {"type": "condition", "field": {"columnName": "code"}, "op": "in", "value": values}
    where_sql, _exists, params = _compile_where_with_params(svc, node, plan)
    assert "normalized large IN list (201 items)" in where_sql
    assert len(params) == 201

    node = {"type": "condition", "field": {"columnName": "code"}, "op": "in", "value": "['a','b']"}
    where_sql, _exists, params = _compile_where_with_params(svc, node, plan)
    assert where_sql == "t0.code IN (:p1, :p2)"
    assert params == {"p1": "a", "p2": "b"}

    node = {"type": "condition", "field": {"columnName": "code"}, "op": "in", "value": '["a","b"]'}
    where_sql, _exists, params = _compile_where_with_params(svc, node, plan)
    assert where_sql == "t0.code IN (:p1, :p2)"
    assert params == {"p1": "a", "p2": "b"}

    node = {"type": "condition", "field": {"columnName": "code"}, "op": "in", "value": "a,b"}
    where_sql, _exists, params = _compile_where_with_params(svc, node, plan)
    assert where_sql == "t0.code IN (:p1, :p2)"
    assert params == {"p1": "a", "p2": "b"}


def test_compile_where_in_manual_errors_and_value_override_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _single_table_plan()
    svc = QueryForgeService(executor=ArrayExec(), domain_resolver=FakeResolver(plan))
    manual = {
        "type": "condition",
        "field": {"columnName": "code"},
        "op": "in",
        "value": {"mode": "manual", "values": "a,b"},
    }
    where_sql, _exists, params = _compile_where_with_params(svc, manual, plan)
    assert where_sql == "t0.code IN (:p1, :p2)"
    assert params == {"p1": "a", "p2": "b"}

    bad_mode = {"type": "condition", "field": {"columnName": "code"}, "op": "in", "value": {"mode": "weird"}}
    with pytest.raises(ForgeError):
        _compile_where_with_params(svc, bad_mode, plan)

    bad_list_type = {"type": "condition", "field": {"columnName": "code"}, "op": "in", "value": {"mode": "value_override", "listType": "bad", "listId": "x"}}
    with pytest.raises(ForgeError):
        _compile_where_with_params(svc, bad_list_type, plan)

    missing_list_id = {"type": "condition", "field": {"columnName": "code"}, "op": "in", "value": {"mode": "value_override", "listType": "regions"}}
    with pytest.raises(ForgeError):
        _compile_where_with_params(svc, missing_list_id, plan)

    monkeypatch.setitem(TABLE_BY_TYPE, "regions", None)
    bad_table = {"type": "condition", "field": {"columnName": "code"}, "op": "in", "value": {"mode": "value_override", "listType": "regions", "listId": "x"}}
    with pytest.raises(ForgeError):
        _compile_where_with_params(svc, bad_table, plan)


def test_compile_where_force_exists_for_tables() -> None:
    plan, join = _two_table_plan()
    resolver = FakeResolver(plan, paths={2: [join]})
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)
    node = {
        "type": "condition",
        "field": {"columnName": "code", "workspaceTableId": 2},
        "op": "equals",
        "value": "A1",
    }
    where_sql, exists_parts, _params = _compile_where_with_params(
        svc,
        node,
        plan,
        alias_by_wt={1: "t0", 2: "t1"},
        force_exists_for_tables={2},
    )
    assert where_sql == ""
    assert exists_parts and "EXISTS" in exists_parts[0]


def test_compile_where_in_no_array_raises_for_large() -> None:
    plan = _single_table_plan()
    svc = QueryForgeService(executor=NoArrayExec(), domain_resolver=FakeResolver(plan))
    values = list(range(QF_MAX_MANUAL_IN + 1))
    node = {"type": "condition", "field": {"columnName": "code"}, "op": "in", "value": values}
    with pytest.raises(ForgeError):
        _compile_where_with_params(svc, node, plan)


def test_compile_attachments_value_override_filter_and_join() -> None:
    plan, join = _two_table_plan()
    resolver = FakeResolver(plan, paths={2: [join]}, workspace_id="ws")
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)

    def new_param(_val, _counter=[0]):
        _counter[0] += 1
        return f":p{_counter[0]}"

    ctx = svc._compile_attachments(
        value_override_attachments=[
            {
                "listType": "regions",
                "listId": "l1",
                "mode": "filter",
                "domainJoinColumns": [
                    {"columnName": "zip", "workspaceTableId": 1},
                    {"columnName": "facility_zip", "workspaceTableId": 1},
                ],
            },
            {
                "listType": "regions",
                "listId": "l2",
                "mode": "join",
                "domainJoinColumns": [
                    {"columnName": "zip", "workspaceTableId": 1},
                    {"columnName": "facility_zip", "workspaceTableId": 1},
                ],
                "projectFields": ["region"],
            },
        ],
        cohort_attachment=None,
        derived_by_exprid={},
        derived_by_name={},
        rewrite_by_colname={},
        rewrite_by_modelid={},
        qf_using_prep=False,
        qf_base_alias="t0",
        alias_by_wt=plan.alias_by_workspace_table_id,
        plan=plan,
        new_param=new_param,
    )
    assert ctx["where"] and "EXISTS" in ctx["where"][0]
    assert "OR" in ctx["where"][0] and "(" in ctx["where"][0]
    assert ctx["ctes"] and "cw_regions" in ctx["ctes"][0]
    assert ctx["selects"] and "cw_region" in ctx["selects"][0][0]


def test_compile_attachments_join_separate_aliases_and_needs_base_alias() -> None:
    plan, join = _two_table_plan()
    resolver = FakeResolver(plan, paths={2: [join]}, workspace_id="ws")
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)

    def new_param(_val, _counter=[0]):
        _counter[0] += 1
        return f":p{_counter[0]}"

    ctx = svc._compile_attachments(
        value_override_attachments=[
            {
                "id": "att1",
                "listType": "npiCategories",
                "listId": "l1",
                "mode": "join",
                "domainJoinColumns": [
                    {"columnName": "attending_npi", "workspaceTableId": 1, "joinAlias": "1att"},
                    "referring_npi",
                ],
                "projectFields": ["customer_npi_category_1"],
                "supportsSeparateAliasJoins": True,
            }
        ],
        cohort_attachment=None,
        derived_by_exprid={},
        derived_by_name={"attending_npi": "__dp_attending_npi"},
        rewrite_by_colname={},
        rewrite_by_modelid={},
        qf_using_prep=True,
        qf_base_alias="t0",
        alias_by_wt=plan.alias_by_workspace_table_id,
        plan=plan,
        new_param=new_param,
    )
    assert ctx["needs_base_alias"] is True
    assert any("cw_npi" in cte for cte in ctx["ctes"])
    assert any("cw_c_1att" in expr for expr, _name in ctx["selects"])
    assert "cw:att1:cw:c_1att:customer_npi_category_1" in ctx["exprid_sql"]


def test_compile_attachments_duplicate_cte_names() -> None:
    plan, join = _two_table_plan()
    resolver = FakeResolver(plan, paths={2: [join]}, workspace_id="ws")
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)

    def new_param(_val, _counter=[0]):
        _counter[0] += 1
        return f":p{_counter[0]}"

    ctx = svc._compile_attachments(
        value_override_attachments=[
            {
                "listType": "regions",
                "listId": "l1",
                "mode": "join",
                "domainJoinColumns": [{"columnName": "zip", "workspaceTableId": 1}],
                "projectFields": ["region"],
            },
            {
                "listType": "regions",
                "listId": "l2",
                "mode": "join",
                "domainJoinColumns": [{"columnName": "zip", "workspaceTableId": 1}],
                "projectFields": ["subregion"],
            },
        ],
        cohort_attachment=None,
        derived_by_exprid={},
        derived_by_name={},
        rewrite_by_colname={},
        rewrite_by_modelid={},
        qf_using_prep=False,
        qf_base_alias="t0",
        alias_by_wt=plan.alias_by_workspace_table_id,
        plan=plan,
        new_param=new_param,
    )
    assert any("cw_regions_2" in cte for cte in ctx["ctes"])


def test_compile_attachments_table_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    plan, join = _two_table_plan()
    resolver = FakeResolver(plan, paths={2: [join]}, workspace_id="ws")
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)

    def new_param(_val, _counter=[0]):
        _counter[0] += 1
        return f":p{_counter[0]}"

    monkeypatch.setitem(TABLE_BY_TYPE, "regions", None)
    with pytest.raises(ForgeError):
        svc._compile_attachments(
            value_override_attachments=[
                {
                    "listType": "regions",
                    "listId": "l1",
                    "mode": "join",
                    "domainJoinColumns": [{"columnName": "zip", "workspaceTableId": 1}],
                    "projectFields": ["region"],
                }
            ],
            cohort_attachment=None,
            derived_by_exprid={},
            derived_by_name={},
            rewrite_by_colname={},
            rewrite_by_modelid={},
            qf_using_prep=False,
            qf_base_alias="t0",
            alias_by_wt=plan.alias_by_workspace_table_id,
            plan=plan,
            new_param=new_param,
        )


def test_compile_attachments_join_default_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    plan, join = _two_table_plan()
    resolver = FakeResolver(plan, paths={2: [join]}, workspace_id="ws")
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)

    def new_param(_val, _counter=[0]):
        _counter[0] += 1
        return f":p{_counter[0]}"

    monkeypatch.setattr(
        svc,
        "_qf_norm_col_key",
        lambda _col, _path: {"columnName": "patient_id", "workspaceTableId": 1, "modelColumnId": None, "exprId": None},
    )
    ctx = svc._compile_attachments(
        value_override_attachments=[
            {
                "id": "att1",
                "listType": "npiCategories",
                "listId": "l1",
                "mode": "join",
                "domainJoinColumns": [{}, {}],
                "projectFields": ["customer_npi_category_1"],
                "supportsSeparateAliasJoins": True,
            }
        ],
        cohort_attachment=None,
        derived_by_exprid={},
        derived_by_name={},
        rewrite_by_colname={},
        rewrite_by_modelid={},
        qf_using_prep=False,
        qf_base_alias="t0",
        alias_by_wt=plan.alias_by_workspace_table_id,
        plan=plan,
        new_param=new_param,
    )
    assert any(name.startswith("cw_c_1_") for _expr, name in ctx["selects"])
    assert "cw:att1:cw:c_1:customer_npi_category_1" in ctx["exprid_sql"]


@pytest.mark.parametrize(
    "bad_cw,workspace_id",
    [
        ("bad", "ws"),
        ({"mode": "bad"}, "ws"),
        ({"listType": "bad", "listId": "x", "mode": "join", "domainJoinColumns": []}, "ws"),
        ({"listType": "regions", "listId": None, "mode": "join", "domainJoinColumns": []}, "ws"),
        ({"listType": "regions", "listId": "x", "mode": "join", "domainJoinColumns": "bad"}, "ws"),
        ({"listType": "regions", "listId": "x", "mode": "join", "domainJoinColumns": []}, "ws"),
        ({"listType": "regions", "listId": "x", "mode": "join", "domainJoinColumns": [{"columnName": "zip"}], "projectFields": "bad"}, "ws"),
        ({"listType": "regions", "listId": "x", "mode": "join", "domainJoinColumns": [{"columnName": "zip"}], "projectFields": ["bad"]}, "ws"),
        ({"listType": "regions", "listId": "x", "mode": "join", "domainJoinColumns": [{"columnName": "zip"}]}, None),
    ],
)
def test_compile_attachments_value_override_errors(bad_cw: object, workspace_id: str | None) -> None:
    plan, join = _two_table_plan()
    resolver = FakeResolver(plan, paths={2: [join]}, workspace_id=workspace_id)
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)

    def new_param(_val, _counter=[0]):
        _counter[0] += 1
        return f":p{_counter[0]}"

    with pytest.raises(ForgeError):
        svc._compile_attachments(
            value_override_attachments=[bad_cw],
            cohort_attachment=None,
            derived_by_exprid={},
            derived_by_name={},
            rewrite_by_colname={},
            rewrite_by_modelid={},
            qf_using_prep=False,
            qf_base_alias="t0",
            alias_by_wt=plan.alias_by_workspace_table_id,
            plan=plan,
            new_param=new_param,
        )


def test_compile_attachments_cohort_join_and_filter() -> None:
    plan, join = _two_table_plan()
    resolver = FakeResolver(plan, paths={2: [join]}, workspace_id="ws")
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)

    def new_param(_val, _counter=[0]):
        _counter[0] += 1
        return f":p{_counter[0]}"

    with pytest.raises(ForgeError, match="cohort functionality is no longer supported"):
        svc._compile_attachments(
            value_override_attachments=[],
            cohort_attachment={
                "id": "co1",
                "mode": "filter",
                "cohortTableFullName": "main.asset.cohort",
                "cohortTableAlias": "cohort",
                "cohortJoinKey": "patient_id",
                "domainJoinColumn": {"columnName": "patient_id", "workspaceTableId": 1},
                "cohortKeyFilter": "ck",
                "projectFields": [],
            },
            derived_by_exprid={},
            derived_by_name={},
            rewrite_by_colname={},
            rewrite_by_modelid={},
            qf_using_prep=False,
            qf_base_alias="t0",
            alias_by_wt=plan.alias_by_workspace_table_id,
            plan=plan,
            new_param=new_param,
        )


@pytest.mark.parametrize(
    "bad_cohort",
    [
        "bad",
        {"mode": "bad"},
        {"mode": "join", "cohortTableAlias": "c", "cohortJoinKey": "patient_id", "domainJoinColumn": {"columnName": "id"}},
        {"mode": "join", "cohortTableFullName": "x", "cohortTableAlias": "c", "cohortJoinKey": None, "domainJoinColumn": {"columnName": "id"}},
        {"mode": "join", "cohortTableFullName": "x", "cohortTableAlias": "c", "cohortJoinKey": "patient_id"},
        {"mode": "join", "cohortTableFullName": "x", "cohortTableAlias": "c", "cohortJoinKey": "patient_id", "domainJoinColumn": {"columnName": "id"}, "projectFields": "bad"},
        {"mode": "join", "cohortTableFullName": "x", "cohortTableAlias": "c", "cohortJoinKey": "patient_id", "domainJoinColumn": {"columnName": "id"}, "projectFields": [None]},
    ],
)
def test_compile_attachments_cohort_errors(bad_cohort: object) -> None:
    plan, join = _two_table_plan()
    resolver = FakeResolver(plan, paths={2: [join]}, workspace_id="ws")
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)

    def new_param(_val, _counter=[0]):
        _counter[0] += 1
        return f":p{_counter[0]}"

    with pytest.raises(ForgeError):
        svc._compile_attachments(
            value_override_attachments=[],
            cohort_attachment=bad_cohort,
            derived_by_exprid={},
            derived_by_name={},
            rewrite_by_colname={},
            rewrite_by_modelid={},
            qf_using_prep=False,
            qf_base_alias="t0",
            alias_by_wt=plan.alias_by_workspace_table_id,
            plan=plan,
            new_param=new_param,
        )


def test_compile_skips_attachment_select_duplicates() -> None:
    plan = _single_table_plan()
    resolver = FakeResolver(plan, workspace_id="ws")
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)
    q = {
        "domainId": 1,
        "columns": [
            {"columnName": "cw_region", "exprId": "cw:att1:cw:region"},
            {"columnName": "cw_subregion", "exprId": "cw:att1:cw:subregion"},
        ],
        "value_overrideAttachments": [
            {
                "id": "att1",
                "listType": "regions",
                "listId": "l1",
                "mode": "join",
                "domainJoinColumns": [{"columnName": "zip", "workspaceTableId": 1}],
                "projectFields": ["region", "subregion"],
            }
        ],
    }
    compiled = svc.compile(svc.normalize(q))
    assert compiled.sql.count("cw_regions.region") == 1
    assert compiled.sql.count("cw_regions.subregion") == 1


def test_compile_aggs_with_attachment_selects_raises() -> None:
    plan = _single_table_plan()
    resolver = FakeResolver(plan, workspace_id="ws")
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)
    q = {
        "domainId": 1,
        "columns": [{"columnName": "patient_id"}],
        "aggs": {"enabled": True, "groupBy": [{"columnName": "patient_id"}], "metrics": []},
        "value_overrideAttachments": [
            {
                "listType": "regions",
                "listId": "l1",
                "mode": "join",
                "domainJoinColumns": [{"columnName": "zip", "workspaceTableId": 1}],
                "projectFields": ["region"],
            }
        ],
    }
    with pytest.raises(ForgeError):
        svc.compile(svc.normalize(q))


def test_compile_uses_prep_alias_with_attachment_needs_base_alias() -> None:
    plan = _single_table_plan()
    resolver = FakeResolver(plan, workspace_id="ws")
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)
    q = {
        "domainId": 1,
        "columns": [{"columnName": "zip"}],
        "dataPrep": {
            "rules": [
                {"id": "r1", "op": "fill_empty", "target": {"columnName": "zip"}, "output": {"columnName": "zip"}, "value": ""}
            ]
        },
        "value_overrideAttachments": [
            {
                "id": "att1",
                "listType": "regions",
                "listId": "l1",
                "mode": "join",
                "domainJoinColumns": [{"columnName": "zip", "workspaceTableId": 1}],
                "projectFields": ["region"],
            }
        ],
    }
    compiled = svc.compile(svc.normalize(q))
    assert "FROM prep t0" in compiled.sql


def test_compile_two_phase_preview_with_filter_only_table() -> None:
    plan, join = _two_table_plan()
    resolver = FakeResolver(plan, paths={2: [join]}, workspace_id="ws")
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)
    q = {
        "domainId": 1,
        "columns": [{"columnName": "patient_id", "workspaceTableId": 1}],
        "filters": {
            "type": "group",
            "match": "and",
            "children": [
                {"type": "condition", "field": {"columnName": "code", "workspaceTableId": 2}, "op": "equals", "value": "A1"}
            ],
        },
        "value_overrideAttachments": [
            {
                "id": "att1",
                "listType": "regions",
                "listId": "l1",
                "mode": "join",
                "domainJoinColumns": [{"columnName": "zip", "workspaceTableId": 1}],
                "projectFields": ["region"],
            }
        ],
    }
    compiled = svc.compile(svc.normalize(q))
    assert "WITH base_patients AS" in compiled.sql
    assert "FROM base_patients bp" in compiled.sql
    assert "EXISTS" in compiled.sql
    assert "\nLIMIT " not in compiled.sql.split("\n")[-2]
    assert "WITH base_patients AS" in compiled.qf_count_sql


def test_compile_two_phase_with_projection_join_lines() -> None:
    plan, join_filter, join_projected = _three_table_plan()
    resolver = FakeResolver(plan, paths={2: [join_filter], 3: [join_projected]}, workspace_id="ws")
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)
    q = {
        "domainId": 1,
        "columns": [{"columnName": "visit_id", "workspaceTableId": 3}],
        "filters": {
            "type": "group",
            "match": "and",
            "children": [
                {"type": "condition", "field": {"columnName": "code", "workspaceTableId": 2}, "op": "equals", "value": "A1"}
            ],
        },
    }
    compiled = svc.compile(svc.normalize(q))
    assert "WITH base_patients AS" in compiled.sql
    assert "JOIN main.asset.visits" in compiled.sql


def test_compile_two_phase_uses_primary_join_key_not_hardcoded_patient_id() -> None:
    plan, join = _staff_two_table_plan()
    resolver = FakeResolver(plan, paths={30: [join]}, workspace_id="ws")
    svc = QueryForgeService(executor=FakeForgeQueryPort(), domain_resolver=resolver)
    q = {
        "domainId": 1,
        "columns": [{"columnName": "first_name", "workspaceTableId": 23}],
        "filters": {
            "type": "group",
            "match": "and",
            "children": [
                {
                    "type": "condition",
                    "field": {"columnName": "staff_classification", "workspaceTableId": 30},
                    "op": "equals",
                    "value": "Principal",
                }
            ],
        },
    }
    compiled = svc.compile(svc.normalize(q))
    assert "WITH base_patients AS" in compiled.sql
    assert "staff.k_person" in compiled.sql
    assert "staff.patient_id" not in compiled.sql
