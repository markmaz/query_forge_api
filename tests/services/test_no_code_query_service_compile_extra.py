from __future__ import annotations

import re

import pytest

from app.exceptions.service_error import ServiceError
from app.services.domain_resolver import DomainPlan, DomainPlanJoin, DomainPlanTable
from app.services.no_code_query_service import MAX_MANUAL_IN, NoCodeQueryService
from tests._support.fakes import FakeSQLExecutor


class FakeResolver:
    def __init__(self, plan: DomainPlan, paths: dict[int, list[DomainPlanJoin]] | None = None) -> None:
        self._plan = plan
        self._paths = paths or {}

    def resolve_plan(self, domain_id: int) -> DomainPlan:
        del domain_id
        return self._plan

    def get_join_path(self, plan: DomainPlan, to_workspace_table_id: int) -> list[DomainPlanJoin]:
        del plan
        return list(self._paths.get(int(to_workspace_table_id), []))


class FakeRunExecutor:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict | None]] = []

    def submit_statement(self, sql: str, *, parameters: dict | None = None, **_kwargs) -> dict:
        self.calls.append((sql, parameters))
        return self._responses.pop(0)


def _single_table_plan() -> DomainPlan:
    table = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.people",
        alias="t0",
        table_alias="p",
        is_primary=True,
        sort_order=0,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    return DomainPlan(
        primary=table,
        tables=[table],
        joins=[],
        alias_by_workspace_table_id={1: "t0"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )


def _compile_where_with_params(
    svc: NoCodeQueryService,
    node: dict | None,
    plan: DomainPlan,
    *,
    derived_by_exprid: dict | None = None,
    derived_by_name: dict | None = None,
    rewrite_by_colname: dict | None = None,
    rewrite_by_modelid: dict | None = None,
    using_prep: bool = False,
    base_alias: str = "t0",
    alias_by_wt: dict | None = None,
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
        derived_by_exprid or {},
        derived_by_name or {},
        rewrite_by_colname or {},
        rewrite_by_modelid or {},
        using_prep,
        base_alias,
        alias_by_wt or {1: "t0"},
        plan,
        new_param,
    )
    return where_sql, exists_parts, params


def test_compile_with_data_prep_cte_rewrites() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))

    q = {
        "domainId": 1,
        "columns": [
            {"columnName": "name"},
            {"columnName": "age_num"},
            {"columnName": "city_norm"},
            {"columnName": "dob_date"},
            {"columnName": "score_round"},
        ],
        "filters": {
            "type": "group",
            "id": "g1",
            "match": "and",
            "children": [
                {"type": "condition", "id": "c1", "field": "name", "op": "equals", "value": "Bob"},
            ],
        },
        "dataPrep": {
            "rules": [
                {
                    "id": "r1",
                    "op": "fill_empty",
                    "target": {"columnName": "name"},
                    "output": {"columnName": "name"},
                    "fallbackCol": {"columnName": "name_fallback"},
                    "treatBlankAsEmpty": True,
                },
                {
                    "id": "r2",
                    "op": "cast",
                    "target": {"columnName": "age"},
                    "output": {"columnName": "age_num"},
                    "toType": "INT",
                    "safe": True,
                },
                {
                    "id": "r3",
                    "op": "normalize_text",
                    "target": {"columnName": "city"},
                    "output": {"columnName": "city_norm"},
                    "mode": "trim_lower",
                },
                {
                    "id": "r4",
                    "op": "parse_date",
                    "target": {"columnName": "dob"},
                    "output": {"columnName": "dob_date"},
                    "format": "yyyy-MM-dd",
                },
                {
                    "id": "r5",
                    "op": "round",
                    "target": {"columnName": "score"},
                    "output": {"columnName": "score_round"},
                    "decimals": 2,
                },
            ]
        },
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    compiled = svc.compile(svc.normalize(q))

    assert "WITH prep AS" in compiled.sql
    assert "COALESCE(NULLIF(TRIM(t0.name), ''), t0.name_fallback) AS __dp_name" in compiled.sql
    assert "TRY_CAST(t0.age AS INT) AS __dp_age_num" in compiled.sql
    assert "LOWER(TRIM(t0.city)) AS __dp_city_norm" in compiled.sql
    assert "TO_DATE(t0.dob, 'yyyy-MM-dd') AS __dp_dob_date" in compiled.sql
    assert "ROUND(t0.score, 2) AS __dp_score_round" in compiled.sql
    assert "FROM prep" in compiled.sql
    assert "WHERE __dp_name = :p1" in compiled.sql


def test_compile_aggs_with_metrics_and_aliases() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))

    q = {
        "domainId": 1,
        "columns": [{"columnName": "city", "alias": "City Name", "workspaceTableId": 1}],
        "aggs": {
            "enabled": True,
            "groupBy": [{"columnName": "city", "workspaceTableId": 1}],
            "metrics": [
                {"fn": "count", "label": "Total Rows"},
                {"fn": "count_distinct", "field": {"columnName": "user_id", "workspaceTableId": 1}, "label": "Unique Users"},
                {"fn": "sum", "field": {"columnName": "amount", "workspaceTableId": 1}, "label": "Total Amount"},
            ],
        },
        "sorting": [{"columnName": {"columnName": "city", "workspaceTableId": 1}, "dir": "asc"}],
    }

    compiled = svc.compile(svc.normalize(q))

    assert "t0.city AS `City Name`" in compiled.sql
    assert "COUNT(*) AS `Total Rows`" in compiled.sql
    assert "COUNT(DISTINCT t0.user_id) AS `Unique Users`" in compiled.sql
    assert "SUM(t0.amount) AS `Total Amount`" in compiled.sql
    assert "GROUP BY t0.city" in compiled.sql
    assert "ORDER BY t0.city ASC" in compiled.sql


def test_compile_metric_invalid_fn_raises() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))

    q = {
        "domainId": 1,
        "columns": [{"columnName": "city"}],
        "aggs": {"enabled": True, "groupBy": [], "metrics": [{"fn": "median", "label": "Median"}]},
    }

    with pytest.raises(ServiceError, match="Unsupported metric"):
        svc.compile(svc.normalize(q))


def test_compile_no_selectable_exprs() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    q = {
        "domainId": 1,
        "columns": [],
        "aggs": {"enabled": True, "groupBy": [], "metrics": []},
    }
    with pytest.raises(ServiceError, match="No selectable columns"):
        svc.compile(svc.normalize(q))


def test_compile_show_all_qualified_auto_alias_and_join_expr() -> None:
    join = DomainPlanJoin(
        join_id="j1",
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="INNER",
        join_spec={
            "on": [
                {
                    "left": {"expr": "get_json_object({from}.payload, '$.id')"},
                    "right": {"columnName": "id"},
                }
            ]
        },
        sort_order=0,
    )
    t0 = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.dx",
        alias="t0",
        table_alias="dx",
        is_primary=True,
        sort_order=0,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    t1 = DomainPlanTable(
        workspace_table_id=2,
        full_name="main.asset.px",
        alias="t1",
        table_alias="px",
        is_primary=False,
        sort_order=1,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    plan = DomainPlan(
        primary=t0,
        tables=[t0, t1],
        joins=[join],
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="SHOW_ALL_QUALIFIED",
    )
    resolver = FakeResolver(plan, paths={2: [join]})
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=resolver)

    q = {
        "domainId": 1,
        "columns": [
            {"columnName": "code", "workspaceTableId": 1},
            {"columnName": "code", "workspaceTableId": 2},
        ],
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    compiled = svc.compile(svc.normalize(q))

    assert "INNER JOIN main.asset.px t1 ON get_json_object(t0.payload, '$.id') = t1.id" in compiled.sql
    assert "t0.code AS dx_code" in compiled.sql
    assert "t1.code AS px_code" in compiled.sql


def test_data_prep_empty_rules_returns_defaults() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    ctx = svc._compile_data_prep_cte(
        {"rules": []},
        base_from_sql="main.asset.people t0",
        base_alias="t0",
        alias_by_wt={},
    )
    assert ctx["cte_sql"] == ""
    assert ctx["from_clause_sql"] == "main.asset.people t0"


@pytest.mark.parametrize(
    "rules, msg",
    [
        (["bad"], "dataPrep.rules[0] must be an object"),
        ([{"op": "fill_empty", "target": {"columnName": "a"}, "output": {"columnName": "b"}}], "id is required"),
        ([{"id": "r1", "op": "fill_empty", "target": "bad", "output": {"columnName": "b"}}], "target must be a column key"),
        ([{"id": "r1", "op": "fill_empty", "target": {"columnName": "a"}, "output": "bad"}], "output must be a column key"),
        ([{"id": "r1", "op": "fill_empty", "target": {"columnName": "a"}, "output": {"columnName": ""}}], "output.columnName is required"),
        ([{"id": "r1", "op": "cast", "target": {"columnName": "a"}, "output": {"columnName": "b"}}], "cast.toType is required"),
        ([{"id": "r1", "op": "normalize_text", "target": {"columnName": "a"}, "output": {"columnName": "b"}, "mode": "bad"}], "normalize_text.mode invalid"),
        ([{"id": "r1", "op": "parse_date", "target": {"columnName": "a"}, "output": {"columnName": "b"}, "format": 12}], "parse_date.format"),
        ([{"id": "r1", "op": "round", "target": {"columnName": "a"}, "output": {"columnName": "b"}, "decimals": "2"}], "round.decimals"),
        ([{"id": "r1", "op": "noop", "target": {"columnName": "a"}, "output": {"columnName": "b"}}], "Unsupported dataPrep op"),
    ],
)
def test_data_prep_validation_errors(rules: list[dict], msg: str) -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    with pytest.raises(ServiceError, match=re.escape(msg)):
        svc._compile_data_prep_cte(
            {"rules": rules},
            base_from_sql="main.asset.people t0",
            base_alias="t0",
            alias_by_wt={},
        )


def test_data_prep_ops_variants() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    ctx = svc._compile_data_prep_cte(
        {
            "rules": [
                {
                    "id": "r1",
                    "op": "fill_empty",
                    "target": {"columnName": "name"},
                    "output": {"columnName": "name_fill"},
                    "value": "x",
                },
                {
                    "id": "r2",
                    "op": "cast",
                    "target": {"columnName": "age"},
                    "output": {"columnName": "age_cast"},
                    "toType": "INT",
                    "safe": False,
                },
                {
                    "id": "r3",
                    "op": "normalize_text",
                    "target": {"columnName": "city"},
                    "output": {"columnName": "city_lower"},
                    "mode": "lower",
                },
                {
                    "id": "r4",
                    "op": "normalize_text",
                    "target": {"columnName": "state"},
                    "output": {"columnName": "state_upper"},
                    "mode": "upper",
                },
                {
                    "id": "r5",
                    "op": "normalize_text",
                    "target": {"columnName": "zip"},
                    "output": {"columnName": "zip_trim"},
                    "mode": "trim",
                },
                {
                    "id": "r6",
                    "op": "parse_date",
                    "target": {"columnName": "dob"},
                    "output": {"columnName": "dob_date"},
                },
                {
                    "id": "r7",
                    "op": "round",
                    "target": {"columnName": "score"},
                    "output": {"columnName": "score_round"},
                    "decimals": 1,
                },
                {
                    "id": "r8",
                    "op": "cast",
                    "target": {"columnName": "code", "modelColumnId": 10},
                    "output": {"columnName": "code_cast"},
                    "toType": "STRING",
                },
                {
                    "id": "r9",
                    "op": "concat",
                    "inputs": [
                        {"type": "column", "col": {"columnName": "first"}},
                        {"type": "column", "col": {"columnName": "last"}},
                    ],
                    "separator": " ",
                    "nulls": "skip",
                    "output": {"columnName": "full_name"},
                },
                {
                    "id": "r10",
                    "op": "concat",
                    "inputs": [
                        {"type": "column", "col": {"columnName": "city"}},
                        {"type": "literal", "value": "-"},
                        {"type": "column", "col": {"columnName": "state"}},
                    ],
                    "nulls": "propagate",
                    "output": {"columnName": "city_state"},
                },
            ]
        },
        base_from_sql="main.asset.people t0",
        base_alias="t0",
        alias_by_wt={},
    )

    cte_sql = ctx["cte_sql"]
    assert "COALESCE(t0.name, 'x') AS __dp_name_fill" in cte_sql
    assert "CAST(t0.age AS INT) AS __dp_age_cast" in cte_sql
    assert "LOWER(t0.city) AS __dp_city_lower" in cte_sql
    assert "UPPER(t0.state) AS __dp_state_upper" in cte_sql
    assert "TRIM(t0.zip) AS __dp_zip_trim" in cte_sql
    assert "TO_DATE(t0.dob) AS __dp_dob_date" in cte_sql
    assert "ROUND(t0.score, 1) AS __dp_score_round" in cte_sql
    assert "CONCAT_WS(' ', t0.first, t0.last) AS __dp_full_name" in cte_sql
    assert "CONCAT(t0.city, '-', t0.state) AS __dp_city_state" in cte_sql
    assert ctx["rewrite_by_modelid"][10] == "__dp_code_cast"


def test_data_prep_exprs_empty_after_iteration() -> None:
    class EmptyIter(list):
        def __iter__(self):
            return iter([])

    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    rules = EmptyIter(
        [
            {
                "id": "r1",
                "op": "fill_empty",
                "target": {"columnName": "a"},
                "output": {"columnName": "b"},
            }
        ]
    )
    ctx = svc._compile_data_prep_cte(
        {"rules": rules},
        base_from_sql="main.asset.people t0",
        base_alias="t0",
        alias_by_wt={},
    )
    assert ctx["cte_sql"] == ""


def test_compile_exprid_projection_alias() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    q = {
        "domainId": 1,
        "columns": [
            {"columnName": "full_name", "exprId": "r1", "alias": "Full Name"},
        ],
        "filters": None,
        "sorting": [],
        "dataPrep": {
            "rules": [
                {
                    "id": "r1",
                    "op": "concat",
                    "inputs": [
                        {"type": "column", "col": {"columnName": "first"}},
                        {"type": "column", "col": {"columnName": "last"}},
                    ],
                    "separator": " ",
                    "nulls": "skip",
                    "output": {"columnName": "full_name"},
                }
            ]
        },
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    compiled = svc.compile(svc.normalize(q))
    assert "__dp_full_name AS `Full Name`" in compiled.sql
    assert compiled.output_columns == [{"key": "Full Name", "label": "Full Name"}]


def test_compile_crosswalk_exprid_projection_alias() -> None:
    plan = _single_table_plan()
    resolver = FakeResolver(plan)
    resolver._workspace_id = "ws"
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=resolver)
    q = {
        "domainId": 1,
        "columns": [
            {"columnName": "cw_region", "exprId": "cw:att1:cw:region"},
        ],
        "filters": None,
        "sorting": [],
        "crosswalkAttachments": [
            {
                "id": "att1",
                "listType": "regions",
                "listId": "list-1",
                "mode": "join",
                "domainJoinColumns": [{"columnName": "patient_zip"}],
                "projectFields": ["region"],
            }
        ],
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    compiled = svc.compile(svc.normalize(q))
    assert "cw_regions.region AS cw_region" in compiled.sql
    assert compiled.output_columns == [{"key": "cw_region", "label": "cw_region"}]


def test_compile_exprid_duplicate_column_names_are_aliased() -> None:
    plan = _single_table_plan()
    resolver = FakeResolver(plan)
    resolver._workspace_id = "ws"
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=resolver)
    q = {
        "domainId": 1,
        "columns": [
            {
                "columnName": "val",
                "exprId": "r1",
            },
            {
                "columnName": "val",
                "exprId": "r2",
            },
        ],
        "filters": None,
        "sorting": [],
        "dataPrep": {
            "rules": [
                {
                    "id": "r1",
                    "op": "fill_empty",
                    "target": {"columnName": "a"},
                    "output": {"columnName": "val_1"},
                    "value": "x",
                },
                {
                    "id": "r2",
                    "op": "normalize_text",
                    "target": {"columnName": "b"},
                    "output": {"columnName": "val_2"},
                    "mode": "lower",
                },
            ]
        },
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    compiled = svc.compile(svc.normalize(q))
    output_names = [c["key"] for c in compiled.output_columns]
    assert len(output_names) == 2
    assert output_names[0] != output_names[1]


def test_compile_exprid_projection_dedupes() -> None:
    plan = _single_table_plan()
    resolver = FakeResolver(plan)
    resolver._workspace_id = "ws"
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=resolver)
    q = {
        "domainId": 1,
        "columns": [
            {"columnName": "cw_region", "exprId": "cw:att1:cw:region"},
            {"columnName": "cw_region", "exprId": "cw:att1:cw:region"},
        ],
        "filters": None,
        "sorting": [],
        "crosswalkAttachments": [
            {
                "id": "att1",
                "listType": "regions",
                "listId": "list-1",
                "mode": "join",
                "domainJoinColumns": [{"columnName": "patient_zip"}],
                "projectFields": ["region"],
            }
        ],
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    compiled = svc.compile(svc.normalize(q))
    assert [c["key"] for c in compiled.output_columns] == ["cw_region"]


def test_compile_or_group_with_exists() -> None:
    join = DomainPlanJoin(
        join_id="j1",
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="INNER",
        join_spec={
            "on": [
                {
                    "left": {"columnName": "patient_id", "workspaceTableId": 1},
                    "right": {"columnName": "patient_id", "workspaceTableId": 2},
                }
            ]
        },
        sort_order=0,
    )
    t0 = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.patients",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    t1 = DomainPlanTable(
        workspace_table_id=2,
        full_name="main.asset.codes",
        alias="t1",
        table_alias=None,
        is_primary=False,
        sort_order=1,
        filter_mode="EXISTS",
        cardinality="MANY",
    )
    plan = DomainPlan(
        primary=t0,
        tables=[t0, t1],
        joins=[join],
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    resolver = FakeResolver(plan, paths={2: [join]})
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=resolver)

    q = {
        "domainId": 1,
        "columns": [{"columnName": "patient_id"}],
        "filters": {
            "type": "group",
            "id": "root",
            "match": "or",
            "children": [
                {"type": "condition", "id": "c1", "field": "gender", "op": "equals", "value": "F"},
                {
                    "type": "condition",
                    "id": "c2",
                    "existsScopeId": "bucket1",
                    "field": {"columnName": "code", "workspaceTableId": 2},
                    "op": "equals",
                    "value": "A1",
                },
            ],
        },
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    compiled = svc.compile(svc.normalize(q))
    assert "EXISTS" in compiled.sql
    assert " OR " in compiled.sql


def test_join_errors() -> None:
    t0 = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.a",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    t1 = DomainPlanTable(
        workspace_table_id=2,
        full_name="main.asset.b",
        alias="t1",
        table_alias=None,
        is_primary=False,
        sort_order=1,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    join_same = DomainPlanJoin(
        join_id="j1",
        from_workspace_table_id=2,
        to_workspace_table_id=2,
        join_type="INNER",
        join_spec={"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id"}}]},
        sort_order=0,
    )
    join_invalid_type = DomainPlanJoin(
        join_id="j2",
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="CROSS",
        join_spec={"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id"}}]},
        sort_order=0,
    )
    plan = DomainPlan(
        primary=t0,
        tables=[t0, t1],
        joins=[join_same, join_invalid_type],
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    resolver = FakeResolver(plan, paths={2: [join_same]})
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=resolver)

    with pytest.raises(ServiceError, match="Join cannot reference the same table"):
        svc._from_clause_from_plan(plan, {1, 2})

    resolver = FakeResolver(plan, paths={2: [join_invalid_type]})
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=resolver)
    with pytest.raises(ServiceError, match="Invalid join_type"):
        svc._from_clause_from_plan(plan, {1, 2})

    with pytest.raises(ServiceError, match="Join references table not in domain"):
        svc._compile_join_on(join_invalid_type, {1: "t0"})

    with pytest.raises(ServiceError, match="Join spec must include non-empty"):
        svc._join_predicates(DomainPlanJoin("j3", 1, 2, "INNER", {"on": []}, 0), "t0", "t1")

    with pytest.raises(ServiceError, match="Join spec on\\[] must be objects"):
        svc._join_predicates(DomainPlanJoin("j4", 1, 2, "INNER", {"on": ["bad"]}, 0), "t0", "t1")

    bad_side = DomainPlanJoin(
        "j5",
        1,
        2,
        "INNER",
        {"on": [{"left": {"columnName": "id", "workspaceTableId": 2}, "right": {"columnName": "id"}}]},
        0,
    )
    with pytest.raises(ServiceError, match="left.workspaceTableId"):
        svc._join_predicates(bad_side, "t0", "t1")

    bad_expr = DomainPlanJoin(
        "j6",
        1,
        2,
        "INNER",
        {"on": [{"left": {"expr": "get_json_object({to}.x, '$.id')"}, "right": {"columnName": "id"}}]},
        0,
    )
    with pytest.raises(ServiceError, match="wrong table scope"):
        svc._join_predicates(bad_expr, "t0", "t1")

    with pytest.raises(ServiceError, match="Join spec column invalid"):
        svc._compile_join_side({"columnName": "t.id"}, expected_scope="from", alias="t0")

    with pytest.raises(ServiceError, match="Join spec expr must match"):
        svc._parse_join_expr("bad")

    bad_right = DomainPlanJoin(
        "j7",
        1,
        2,
        "INNER",
        {"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id", "workspaceTableId": 1}}]},
        0,
    )
    with pytest.raises(ServiceError, match="right.workspaceTableId"):
        svc._join_predicates(bad_right, "t0", "t1")


def test_from_clause_missing_edges() -> None:
    t0 = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.a",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    t1 = DomainPlanTable(
        workspace_table_id=2,
        full_name="main.asset.b",
        alias="t1",
        table_alias=None,
        is_primary=False,
        sort_order=1,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    join = DomainPlanJoin(
        join_id="j1",
        from_workspace_table_id=1,
        to_workspace_table_id=99,
        join_type="INNER",
        join_spec={"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id"}}]},
        sort_order=0,
    )
    plan = DomainPlan(
        primary=t0,
        tables=[t0, t1],
        joins=[join],
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    resolver = FakeResolver(plan, paths={99: [join]})
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=resolver)
    with pytest.raises(ServiceError, match="Join references table not in domain"):
        svc._from_clause_from_plan(plan, {1, 99})

    resolver = FakeResolver(plan, paths={2: []})
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=resolver)
    with pytest.raises(ServiceError, match="does not cover all tables"):
        svc._from_clause_from_plan(plan, {1, 2})


def test_compile_rejects_invalid_join_order() -> None:
    join_first = DomainPlanJoin(
        join_id="j2",
        from_workspace_table_id=2,
        to_workspace_table_id=3,
        join_type="INNER",
        join_spec={"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id"}}]},
        sort_order=1,
    )
    join_second = DomainPlanJoin(
        join_id="j1",
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="INNER",
        join_spec={"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id"}}]},
        sort_order=0,
    )
    t0 = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.a",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    t1 = DomainPlanTable(
        workspace_table_id=2,
        full_name="main.asset.b",
        alias="t1",
        table_alias=None,
        is_primary=False,
        sort_order=1,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    t2 = DomainPlanTable(
        workspace_table_id=3,
        full_name="main.asset.c",
        alias="t2",
        table_alias=None,
        is_primary=False,
        sort_order=2,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    plan = DomainPlan(
        primary=t0,
        tables=[t0, t1, t2],
        joins=[join_first, join_second],
        alias_by_workspace_table_id={1: "t0", 2: "t1", 3: "t2"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    resolver = FakeResolver(plan, paths={3: [join_second, join_first]})
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=resolver)

    q = {
        "domainId": 1,
        "columns": [{"columnName": "id", "workspaceTableId": 3}],
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    with pytest.raises(ServiceError, match="Join order invalid"):
        svc.compile(svc.normalize(q))


def test_run_renders_sql_and_rows() -> None:
    plan = _single_table_plan()
    resolver = FakeResolver(plan)
    executor = FakeRunExecutor(
        [
            {"rows": [[1, "Alice"], [2, "Bob"]]},
            {"rows": [{"total": 2}]},
        ]
    )
    svc = NoCodeQueryService(executor=executor, domain_resolver=resolver)

    q = {
        "domainId": 1,
        "columns": [{"columnName": "id"}, {"columnName": "name"}],
        "filters": {
            "type": "group",
            "id": "g1",
            "match": "and",
            "children": [
                {"type": "condition", "id": "c1", "field": "name", "op": "in", "value": ["Alice", "Bob"]},
            ],
        },
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    result = svc.run(q, limit=2, offset=0)
    assert result.total == 2
    assert result.rows[0]["name"] == "Alice"
    assert "IN ('Alice', 'Bob')" in result.sql_rendered


def test_render_sql_with_params_list() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    rendered = svc._render_sql_with_params("SELECT :p1", {"p1": ["a", "b"]})
    assert rendered == "SELECT ('a', 'b')"


def test_safe_alias_rejects_control_chars() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    with pytest.raises(ServiceError):
        svc._safe_alias("bad\nalias")


def test_helper_literals_and_identifiers() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    assert svc._literal_sql(None) == "NULL"
    assert svc._literal_sql(True) == "TRUE"
    assert svc._literal_sql(False) == "FALSE"
    assert svc._literal_sql(3) == "3"
    assert svc._literal_sql("a'b") == "'a''b'"
    assert svc._render_sql_with_params("SELECT :p1", {"p2": "x"}) == "SELECT :p1"
    assert svc._render_sql_with_params("SELECT 1", {}) == "SELECT 1"

    with pytest.raises(ServiceError):
        svc._safe_ident("bad name")
    with pytest.raises(ServiceError):
        svc._safe_alias("")
    with pytest.raises(ServiceError):
        svc._safe_alias(None)

    assert svc._dp_ident("  ") == "__dp_col"
    assert svc._dp_ident("1 bad") == "__dp_c_1_bad"
    assert svc._project_expr("__dp_name", "name", None) == "__dp_name AS name"
    assert svc._project_expr("col", "col", "Alias") == "col AS Alias"


def test_col_expr_variants() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    derived_by_exprid = {"e1": "__dp_expr"}
    derived_by_name = {"derived": "__dp_derived"}
    rewrite_by_colname = {"name": "__dp_name"}
    rewrite_by_modelid = {10: "__dp_mid"}
    alias_by_wt = {1: "t0"}

    assert (
        svc._col_expr(
            "name",
            derived_by_exprid,
            derived_by_name,
            rewrite_by_colname,
            rewrite_by_modelid,
            True,
            "t0",
            alias_by_wt,
        )
        == "__dp_name"
    )
    assert (
        svc._col_expr(
            "other",
            derived_by_exprid,
            derived_by_name,
            {},
            {},
            True,
            "t0",
            alias_by_wt,
        )
        == "other"
    )
    assert (
        svc._col_expr(
            {"exprId": "e1", "columnName": "x"},
            derived_by_exprid,
            derived_by_name,
            rewrite_by_colname,
            rewrite_by_modelid,
            False,
            "t0",
            alias_by_wt,
        )
        == "__dp_expr"
    )
    assert (
        svc._col_expr(
            {"columnName": "derived"},
            derived_by_exprid,
            derived_by_name,
            rewrite_by_colname,
            rewrite_by_modelid,
            False,
            "t0",
            alias_by_wt,
        )
        == "__dp_derived"
    )
    assert (
        svc._col_expr(
            {"columnName": "z", "modelColumnId": 10},
            derived_by_exprid,
            derived_by_name,
            rewrite_by_colname,
            rewrite_by_modelid,
            True,
            "t0",
            alias_by_wt,
        )
        == "__dp_mid"
    )
    assert (
        svc._col_expr(
            {"columnName": "a", "workspaceTableId": 1},
            derived_by_exprid,
            derived_by_name,
            rewrite_by_colname,
            rewrite_by_modelid,
            False,
            "t0",
            alias_by_wt,
        )
        == "t0.a"
    )
    assert svc._physical_col_expr("col", True, "t0", None) == "col"

    with pytest.raises(ServiceError):
        svc._col_expr("bad.col", derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, False, "t0", alias_by_wt)
    with pytest.raises(ServiceError):
        svc._col_expr(123, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, False, "t0", alias_by_wt)
    with pytest.raises(ServiceError):
        svc._col_expr({"columnName": None}, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, False, "t0", alias_by_wt)
    with pytest.raises(ServiceError):
        svc._col_expr({"columnName": "a", "workspaceTableId": "bad"}, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, False, "t0", alias_by_wt)
    with pytest.raises(ServiceError):
        svc._col_expr({"columnName": "a", "workspaceTableId": 99}, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, False, "t0", alias_by_wt)
    with pytest.raises(ServiceError):
        svc._col_expr({"columnName": "a.b"}, derived_by_exprid, derived_by_name, rewrite_by_colname, rewrite_by_modelid, False, "t0", alias_by_wt)
    with pytest.raises(ServiceError):
        svc._physical_col_expr("bad.col", False, "t0", None)
    with pytest.raises(ServiceError):
        svc._physical_col_expr(None, False, "t0", None)


def test_compile_metric_variants() -> None:
    class FnLike:
        def __bool__(self) -> bool:
            return True

        def lower(self):
            return self

        def strip(self):
            return self

        def __eq__(self, _other) -> bool:
            return False

        def replace(self, _old, _new):
            return self

        def upper(self) -> str:
            return "COUNT"

    class FnLikeCountDistinct(FnLike):
        def upper(self) -> str:
            return "COUNT DISTINCT"

    class FnLikeSum(FnLike):
        def upper(self) -> str:
            return "SUM"

    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    base_kwargs = {
        "derived_by_exprid": {},
        "derived_by_name": {},
        "rewrite_by_colname": {},
        "rewrite_by_modelid": {},
        "using_prep": False,
        "base_alias": "t0",
        "alias_by_wt": {1: "t0"},
    }
    assert (
        svc._compile_metric("count", {"columnName": "id"}, **base_kwargs)
        == "COUNT(t0.id)"
    )
    assert (
        svc._compile_metric("count distinct", {"columnName": "id"}, **base_kwargs)
        == "COUNT(DISTINCT t0.id)"
    )
    assert svc._compile_metric("COUNT", None, **base_kwargs) == "COUNT(*)"
    assert (
        svc._compile_metric("COUNT", {"columnName": "id"}, **base_kwargs)
        == "COUNT(t0.id)"
    )
    assert (
        svc._compile_metric("SUM", {"columnName": "amount"}, **base_kwargs)
        == "SUM(t0.amount)"
    )
    with pytest.raises(ServiceError, match="count_distinct requires a field"):
        svc._compile_metric("count_distinct", None, **base_kwargs)
    with pytest.raises(ServiceError, match="sum requires a field"):
        svc._compile_metric("sum", None, **base_kwargs)
    with pytest.raises(ServiceError, match="sum requires a field"):
        svc._compile_metric("SUM", None, **base_kwargs)
    assert svc._compile_metric(FnLike(), None, **base_kwargs) == "COUNT(*)"
    with pytest.raises(ServiceError, match="count_distinct requires a field"):
        svc._compile_metric(FnLikeCountDistinct(), None, **base_kwargs)
    with pytest.raises(ServiceError, match="SUM requires a field"):
        svc._compile_metric(FnLikeSum(), None, **base_kwargs)
    assert svc._compile_metric(FnLikeSum(), {"columnName": "amount"}, **base_kwargs) == "SUM(t0.amount)"


def test_required_table_ids_and_filter_modes() -> None:
    t0 = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.a",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    t1 = DomainPlanTable(
        workspace_table_id=2,
        full_name="main.asset.b",
        alias="t1",
        table_alias=None,
        is_primary=False,
        sort_order=1,
        filter_mode="EXISTS",
        cardinality="MANY",
    )
    plan = DomainPlan(
        primary=t0,
        tables=[t0, t1],
        joins=[],
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    q = {
        "columns": [{"columnName": "id", "workspaceTableId": "bad"}],
        "dataPrep": {"rules": ["bad"]},
        "filters": {
            "type": "group",
            "match": "and",
            "children": [
                {"type": "condition", "field": {"columnName": "code", "workspaceTableId": 2}, "op": "equals", "value": "A"},
            ],
        },
    }
    needed = svc._required_table_ids_from_query(q, plan)
    assert needed == {1}
    assert svc._effective_filter_mode(plan, 1) == "WHERE"
    assert svc._effective_filter_mode(plan, 2) == "EXISTS"
    plan_auto = DomainPlan(
        primary=t0,
        tables=[t0, DomainPlanTable(2, "main.asset.b", "t1", None, False, 1, "AUTO", "ONE")],
        joins=[],
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    svc_auto = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan_auto))
    assert svc_auto._effective_filter_mode(plan_auto, 2) == "WHERE"
    with pytest.raises(ServiceError, match="workspaceTableId is not in domain"):
        svc._effective_filter_mode(plan, 99)


def test_compile_where_ops_and_errors() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    node = {
        "type": "group",
        "match": "and",
        "children": [
            {"type": "condition", "field": "name", "op": "starts_with", "value": "A"},
            {"type": "condition", "field": "age", "op": "gt", "value": 21},
            {"type": "condition", "field": "age", "op": "lt", "value": 99},
            {"type": "condition", "field": "state", "op": "in", "value": "CA, NY"},
            {"type": "condition", "field": "city", "op": "contains", "value": "x"},
            {"type": "condition", "field": "age", "op": "between", "value": [10, 20]},
        ],
    }
    where_sql, exists_parts, params = _compile_where_with_params(svc, node, plan)
    assert "LIKE" in where_sql
    assert "IN" in where_sql
    assert exists_parts == []
    assert params

    bad_between = {"type": "condition", "field": "x", "op": "between", "value": [1]}
    with pytest.raises(ServiceError, match="between requires"):
        _compile_where_with_params(svc, bad_between, plan)

    bad_op = {"type": "condition", "field": "x", "op": "nope", "value": 1}
    with pytest.raises(ServiceError, match="Unsupported filter op"):
        _compile_where_with_params(svc, bad_op, plan)

    with pytest.raises(ServiceError, match="Invalid filter node"):
        _compile_where_with_params(svc, "bad", plan)


def test_compile_where_in_manual_cap() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    node = {
        "type": "condition",
        "field": "state",
        "op": "in",
        "value": {"mode": "manual", "values": [str(i) for i in range(MAX_MANUAL_IN + 1)]},
    }
    with pytest.raises(ServiceError, match="Too many IN values"):
        _compile_where_with_params(svc, node, plan)


def test_compile_where_in_crosswalk_mode() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    node = {
        "type": "condition",
        "field": "zipcode",
        "op": "in",
        "value": {"mode": "crosswalk", "listType": "regions", "listId": "list-1"},
    }
    where_sql, exists_parts, params = _compile_where_with_params(svc, node, plan)
    assert exists_parts == []
    assert "IN (SELECT" in where_sql
    assert "custom_regions_lists" in where_sql
    assert "list_id" in where_sql
    assert len(params) == 1
    assert list(params.values())[0] == "list-1"


def test_compile_where_in_cohort_mode_view_name() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    node = {
        "type": "condition",
        "field": "patient_id",
        "op": "in",
        "value": {"mode": "cohort", "cohortId": "c1", "viewName": "workboard.cohort_test"},
    }
    where_sql, exists_parts, params = _compile_where_with_params(svc, node, plan)
    assert exists_parts == []
    assert "IN (SELECT" in where_sql
    assert "FROM `workboard`.`cohort_test`" in where_sql
    assert params == {}


def test_compile_where_or_group_empty() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    node = {"type": "group", "match": "or", "children": []}
    where_sql, exists_parts, params = _compile_where_with_params(svc, node, plan)
    assert where_sql == ""
    assert exists_parts == []
    assert params == {}


def test_compile_where_errors_for_exists() -> None:
    join = DomainPlanJoin(
        join_id="j1",
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="INNER",
        join_spec={"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id"}}]},
        sort_order=0,
    )
    t0 = DomainPlanTable(1, "main.asset.a", "t0", None, True, 0, "AUTO", "ONE")
    t1 = DomainPlanTable(2, "main.asset.b", "t1", None, False, 1, "EXISTS", "MANY")
    plan = DomainPlan(
        primary=t0,
        tables=[t0, t1],
        joins=[join],
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )

    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan, paths={2: []}))
    node = {
        "type": "condition",
        "field": {"columnName": "code", "workspaceTableId": 2},
        "op": "equals",
        "value": "x",
    }
    with pytest.raises(ServiceError, match="EXISTS requires non-primary table"):
        _compile_where_with_params(svc, node, plan, alias_by_wt={1: "t0", 2: "t1"})

    bad_plan = DomainPlan(
        primary=t0,
        tables=[t0, t1],
        joins=[join],
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    bad_edge = DomainPlanJoin(
        join_id="j2",
        from_workspace_table_id=1,
        to_workspace_table_id=3,
        join_type="INNER",
        join_spec={"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id"}}]},
        sort_order=0,
    )
    svc = NoCodeQueryService(
        executor=FakeSQLExecutor(),
        domain_resolver=FakeResolver(bad_plan, paths={2: [bad_edge]}),
    )
    with pytest.raises(ServiceError, match="Join path invalid for EXISTS"):
        _compile_where_with_params(svc, node, bad_plan)

    svc_str_field = NoCodeQueryService(
        executor=FakeSQLExecutor(),
        domain_resolver=FakeResolver(plan, paths={1: [join]}),
    )
    svc_str_field._effective_filter_mode = lambda *_args, **_kwargs: "EXISTS"  # type: ignore[assignment]
    with pytest.raises(ServiceError, match="Invalid columnName for exists filter"):
        _compile_where_with_params(
            svc_str_field,
            {"type": "condition", "field": "bad.name", "op": "equals", "value": 1},
            plan,
            alias_by_wt={1: "t0", 2: "t1"},
        )

    svc_non_str = NoCodeQueryService(
        executor=FakeSQLExecutor(),
        domain_resolver=FakeResolver(plan, paths={1: [join]}),
    )
    svc_non_str._effective_filter_mode = lambda *_args, **_kwargs: "EXISTS"  # type: ignore[assignment]
    with pytest.raises(ServiceError, match="Invalid columnName for exists filter"):
        _compile_where_with_params(
            svc_non_str,
            {"type": "condition", "field": 123, "op": "equals", "value": 1},
            plan,
            alias_by_wt={1: "t0", 2: "t1"},
        )

    join_bad_chain = DomainPlanJoin(
        join_id="j2",
        from_workspace_table_id=3,
        to_workspace_table_id=2,
        join_type="INNER",
        join_spec={"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id"}}]},
        sort_order=1,
    )
    plan_chain = DomainPlan(
        primary=t0,
        tables=[t0, t1, DomainPlanTable(3, "main.asset.c", "t2", None, False, 2, "AUTO", "ONE")],
        joins=[join, join_bad_chain],
        alias_by_workspace_table_id={1: "t0", 2: "t1", 3: "t2"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    svc_chain = NoCodeQueryService(
        executor=FakeSQLExecutor(),
        domain_resolver=FakeResolver(plan_chain, paths={2: [join, join_bad_chain]}),
    )
    with pytest.raises(ServiceError, match="Join path invalid for EXISTS"):
        _compile_where_with_params(svc_chain, node, plan_chain, alias_by_wt={1: "t0", 2: "t1", 3: "t2"})

    svc_bad_field = NoCodeQueryService(
        executor=FakeSQLExecutor(),
        domain_resolver=FakeResolver(plan, paths={2: [join]}),
    )
    bad_node = {
        "type": "condition",
        "field": {"columnName": "t.code", "workspaceTableId": 2},
        "op": "equals",
        "value": "x",
    }
    with pytest.raises(ServiceError, match="Invalid columnName for exists filter"):
        _compile_where_with_params(svc_bad_field, bad_node, plan, alias_by_wt={1: "t0", 2: "t1"})

    svc_empty = NoCodeQueryService(
        executor=FakeSQLExecutor(),
        domain_resolver=FakeResolver(plan, paths={2: [join]}),
    )
    svc_empty._join_predicates = lambda *_args, **_kwargs: []  # type: ignore[assignment]
    empty_node = {
        "type": "condition",
        "field": {"columnName": "code", "workspaceTableId": 2},
        "op": "in",
        "value": [],
    }
    with pytest.raises(ServiceError, match="EXISTS predicates missing"):
        _compile_where_with_params(svc_empty, empty_node, plan, alias_by_wt={1: "t0", 2: "t1"})


def test_compile_where_exists_scope_mismatch() -> None:
    t0 = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.a",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    t1 = DomainPlanTable(
        workspace_table_id=2,
        full_name="main.asset.b",
        alias="t1",
        table_alias=None,
        is_primary=False,
        sort_order=1,
        filter_mode="EXISTS",
        cardinality="MANY",
    )
    t2 = DomainPlanTable(
        workspace_table_id=3,
        full_name="main.asset.c",
        alias="t2",
        table_alias=None,
        is_primary=False,
        sort_order=2,
        filter_mode="EXISTS",
        cardinality="MANY",
    )
    plan = DomainPlan(
        primary=t0,
        tables=[t0, t1, t2],
        joins=[],
        alias_by_workspace_table_id={1: "t0", 2: "t1", 3: "t2"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    node = {
        "type": "group",
        "match": "and",
        "children": [
            {"type": "condition", "existsScopeId": "bucket", "field": {"columnName": "x", "workspaceTableId": 2}, "op": "equals", "value": 1},
            {"type": "condition", "existsScopeId": "bucket", "field": {"columnName": "y", "workspaceTableId": 3}, "op": "equals", "value": 2},
        ],
    }
    with pytest.raises(ServiceError, match="existsScopeId must not mix tables"):
        _compile_where_with_params(svc, node, plan, alias_by_wt={1: "t0", 2: "t1", 3: "t2"})


def test_compile_where_exists_scope_merge() -> None:
    join = DomainPlanJoin(
        join_id="j1",
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="INNER",
        join_spec={"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id"}}]},
        sort_order=0,
    )
    t0 = DomainPlanTable(1, "main.asset.a", "t0", None, True, 0, "AUTO", "ONE")
    t1 = DomainPlanTable(2, "main.asset.b", "t1", None, False, 1, "EXISTS", "MANY")
    plan = DomainPlan(
        primary=t0,
        tables=[t0, t1],
        joins=[join],
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    svc = NoCodeQueryService(
        executor=FakeSQLExecutor(),
        domain_resolver=FakeResolver(plan, paths={2: [join]}),
    )
    node = {
        "type": "group",
        "match": "and",
        "children": [
            {"type": "condition", "existsScopeId": "bucket", "field": {"columnName": "x", "workspaceTableId": 2}, "op": "equals", "value": 1},
            {"type": "condition", "existsScopeId": "bucket", "field": {"columnName": "y", "workspaceTableId": 2}, "op": "equals", "value": 2},
        ],
    }
    where_sql, exists_parts, params = _compile_where_with_params(svc, node, plan, alias_by_wt={1: "t0", 2: "t1"})
    assert where_sql == ""
    assert exists_parts
    assert params


def test_compile_where_exists_missing_next_table() -> None:
    join1 = DomainPlanJoin(
        join_id="j1",
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="INNER",
        join_spec={"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id"}}]},
        sort_order=0,
    )
    join2 = DomainPlanJoin(
        join_id="j2",
        from_workspace_table_id=2,
        to_workspace_table_id=3,
        join_type="INNER",
        join_spec={"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id"}}]},
        sort_order=1,
    )
    t0 = DomainPlanTable(1, "main.asset.a", "t0", None, True, 0, "AUTO", "ONE")
    t1 = DomainPlanTable(2, "main.asset.b", "t1", None, False, 1, "EXISTS", "MANY")
    plan = DomainPlan(
        primary=t0,
        tables=[t0, t1],
        joins=[join1, join2],
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    svc = NoCodeQueryService(
        executor=FakeSQLExecutor(),
        domain_resolver=FakeResolver(plan, paths={2: [join1, join2]}),
    )
    node = {"type": "condition", "field": {"columnName": "code", "workspaceTableId": 2}, "op": "equals", "value": "x"}
    with pytest.raises(ServiceError, match="Join path invalid for EXISTS"):
        _compile_where_with_params(svc, node, plan, alias_by_wt={1: "t0", 2: "t1"})


def test_compile_where_exists_two_hops() -> None:
    join1 = DomainPlanJoin(
        join_id="j1",
        from_workspace_table_id=1,
        to_workspace_table_id=2,
        join_type="INNER",
        join_spec={"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id"}}]},
        sort_order=0,
    )
    join2 = DomainPlanJoin(
        join_id="j2",
        from_workspace_table_id=2,
        to_workspace_table_id=3,
        join_type="INNER",
        join_spec={"on": [{"left": {"columnName": "id"}, "right": {"columnName": "id"}}]},
        sort_order=1,
    )
    t0 = DomainPlanTable(1, "main.asset.a", "t0", None, True, 0, "AUTO", "ONE")
    t1 = DomainPlanTable(2, "main.asset.b", "t1", None, False, 1, "AUTO", "ONE")
    t2 = DomainPlanTable(3, "main.asset.c", "t2", None, False, 2, "EXISTS", "MANY")
    plan = DomainPlan(
        primary=t0,
        tables=[t0, t1, t2],
        joins=[join1, join2],
        alias_by_workspace_table_id={1: "t0", 2: "t1", 3: "t2"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    svc = NoCodeQueryService(
        executor=FakeSQLExecutor(),
        domain_resolver=FakeResolver(plan, paths={3: [join1, join2]}),
    )
    node = {"type": "condition", "field": {"columnName": "code", "workspaceTableId": 3}, "op": "equals", "value": "x"}
    where_sql, exists_parts, params = _compile_where_with_params(
        svc,
        node,
        plan,
        alias_by_wt={1: "t0", 2: "t1", 3: "t2"},
    )
    assert where_sql == ""
    assert exists_parts
    assert params


def test_compile_where_invalid_nodes() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    with pytest.raises(ServiceError, match="Invalid filter node type"):
        _compile_where_with_params(svc, {"type": "bad"}, plan)
    with pytest.raises(ServiceError, match="Qualified column names are not allowed in filters"):
        _compile_where_with_params(
            svc,
            {"type": "condition", "field": "a.b", "op": "equals", "value": 1},
            plan,
        )
    bad_plan = DomainPlan(
        primary=plan.primary,
        tables=[
            plan.primary,
            DomainPlanTable(2, "main.asset.other", "t1", None, False, 1, "BAD", "ONE"),
        ],
        joins=[],
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )
    svc_bad = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(bad_plan))
    with pytest.raises(ServiceError, match="Invalid filter mode"):
        _compile_where_with_params(
            svc_bad,
            {"type": "condition", "field": {"columnName": "id", "workspaceTableId": 2}, "op": "equals", "value": 1},
            bad_plan,
            alias_by_wt={1: "t0", 2: "t1"},
        )


def test_columns_and_rows_helpers() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    cols = svc._columns_from_query_json(
        {
            "columns": [{"columnName": "city", "alias": "City"}],
            "aggs": {"enabled": True, "groupBy": [{"columnName": "city"}], "metrics": [{"fn": "count", "label": "Total"}]},
        }
    )
    assert cols[0]["label"] == "City"
    assert svc._col_label_key({"columnName": "x"}) == "x"
    assert svc._col_label_key("y") == "y"
    assert svc._columns_from_query_json({"columns": ["bad"]}) == []
    assert svc._columns_from_query_json({"columns": [{"columnName": None}]}) == []
    assert svc._infer_columns_from_rows([{"a": 1, "b": 2}])[0]["key"] == "a"
    assert svc._infer_columns_from_rows([[1, 2]]) == []
    assert svc._infer_columns_from_rows([]) == []
    assert svc._extract_total([]) == 0
    assert svc._extract_total([{"total": 3}]) == 3
    assert svc._extract_total([[5]]) == 5
    assert svc._extract_total(["bad"]) == 0
    assert svc._rows_to_dicts([], [{"key": "a"}]) == []
    assert svc._rows_to_dicts([{"a": 1}], [{"key": "a"}])[0]["a"] == 1
    assert svc._rows_to_dicts([[1, 2], "bad"], [{"key": "a"}, {"key": "b"}])[0]["a"] == 1
    assert svc._rows_to_dicts([[1]], ["a"])[0]["a"] == 1
    assert svc._rows_to_dicts([[1, 2]], []) == []


def test_compile_order_by_errors() -> None:
    plan = _single_table_plan()
    svc = NoCodeQueryService(executor=FakeSQLExecutor(), domain_resolver=FakeResolver(plan))
    with pytest.raises(ServiceError, match="Invalid sorting entry"):
        svc._compile_order_by(["bad"], {}, {}, {}, {}, False, "t0", {1: "t0"})
    with pytest.raises(ServiceError, match="Invalid sort direction"):
        svc._compile_order_by([{"columnName": {"columnName": "id"}, "dir": "up"}], {}, {}, {}, {}, False, "t0", {1: "t0"})
