
import pytest

from app.exceptions.service_error import ServiceError
from app.services.domain_resolver import DomainPlan, DomainPlanJoin, DomainPlanTable
from app.services.no_code_query_service import NoCodeQueryService


class FakeDomainResolver:
    def __init__(self, plan: DomainPlan):
        self._plan = plan

    def resolve_plan(self, domain_id: int) -> DomainPlan:
        assert domain_id == 99
        return self._plan

    def get_join_path(self, plan: DomainPlan, to_workspace_table_id: int):
        if int(to_workspace_table_id) == int(plan.primary.workspace_table_id):
            return []
        for edge in plan.joins:
            if int(edge.to_workspace_table_id) == int(to_workspace_table_id):
                return [edge]
        raise AssertionError("Join path not found in test plan")


class FakeExecutor:
    def execute(self, sql: str, params=None):
        return {"ok": True, "sql": sql, "params": params}


def test_compile_with_aliases_where_sorting():
    plan = DomainPlan(
        primary=DomainPlanTable(
            workspace_table_id=1,
            full_name="main.asset.claims_header",
            alias="t0",
            table_alias=None,
            is_primary=True,
            sort_order=0,
            filter_mode="AUTO",
            cardinality="ONE",
        ),
        tables=[
            DomainPlanTable(
                workspace_table_id=1,
                full_name="main.asset.claims_header",
                alias="t0",
                table_alias=None,
                is_primary=True,
                sort_order=0,
                filter_mode="AUTO",
                cardinality="ONE",
            )
        ],
        joins=[],
        alias_by_workspace_table_id={1: "t0"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )

    svc = NoCodeQueryService(executor=FakeExecutor(), domain_resolver=FakeDomainResolver(plan))

    q = {
        "version": 1,
        "domainId": 99,
        "columns": [
            {"columnName": "provider_npi", "alias": "Provider NPI"},
            {"columnName": "paid_amount", "alias": "Paid Amount"},
        ],
        "filters": {
            "type": "group",
            "id": "g1",
            "match": "and",
            "children": [
                {"type": "condition", "id": "c1", "field": "paid_amount", "op": "gt", "value": 100},
                {"type": "condition", "id": "c2", "field": "provider_npi", "op": "contains", "value": "123"},
            ],
        },
        "sorting": [{"columnName": "paid_amount", "dir": "desc"}],
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    compiled = svc.compile(svc.normalize(q), mode="preview")
    print(compiled)

    assert "FROM main.asset.claims_header t0" in compiled.sql
    assert "provider_npi AS `Provider NPI`" in compiled.sql
    assert "paid_amount AS `Paid Amount`" in compiled.sql
    assert "WHERE" in compiled.sql
    assert "t0.paid_amount > :p1" in compiled.sql
    assert "t0.provider_npi LIKE :p2" in compiled.sql
    assert "ORDER BY t0.paid_amount DESC" in compiled.sql
    assert "LIMIT 200" in compiled.sql

    assert compiled.params == {"p1": 100, "p2": "%123%"}


def test_exists_filters_secondary_table():
    joins = [
        DomainPlanJoin(
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
    ]
    tables = [
        DomainPlanTable(
            workspace_table_id=1,
            full_name="main.asset.patients",
            alias="t0",
            table_alias=None,
            is_primary=True,
            sort_order=0,
            filter_mode="AUTO",
            cardinality="ONE",
        ),
        DomainPlanTable(
            workspace_table_id=2,
            full_name="main.asset.codes",
            alias="t1",
            table_alias=None,
            is_primary=False,
            sort_order=1,
            filter_mode="EXISTS",
            cardinality="MANY",
        ),
    ]
    plan = DomainPlan(
        primary=tables[0],
        tables=tables,
        joins=joins,
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )

    svc = NoCodeQueryService(executor=FakeExecutor(), domain_resolver=FakeDomainResolver(plan))

    q = {
        "version": 1,
        "domainId": 99,
        "columns": [{"columnName": "patient_id"}],
        "filters": {
            "type": "group",
            "id": "g1",
            "match": "and",
            "children": [
                {
                    "type": "condition",
                    "id": "c1",
                    "field": {"workspaceTableId": 1, "columnName": "gender"},
                    "op": "equals",
                    "value": "F",
                },
                {
                    "type": "condition",
                    "id": "c2",
                    "field": {"workspaceTableId": 2, "columnName": "code"},
                    "op": "equals",
                    "value": "A1",
                },
            ],
        },
        "sorting": [],
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    compiled = svc.compile(svc.normalize(q), mode="preview")

    assert "FROM main.asset.patients t0" in compiled.sql
    assert "JOIN main.asset.codes" not in compiled.sql
    assert "WHERE t0.gender = :p1" in compiled.sql
    assert "EXISTS" in compiled.sql
    assert "FROM main.asset.codes e1" in compiled.sql
    assert "t0.patient_id = e1.patient_id" in compiled.sql
    assert "e1.code = :p2" in compiled.sql
    assert compiled.params == {"p1": "F", "p2": "A1"}


def test_exists_filters_multiple_buckets():
    joins = [
        DomainPlanJoin(
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
    ]
    tables = [
        DomainPlanTable(
            workspace_table_id=1,
            full_name="main.asset.patients",
            alias="t0",
            table_alias=None,
            is_primary=True,
            sort_order=0,
            filter_mode="AUTO",
            cardinality="ONE",
        ),
        DomainPlanTable(
            workspace_table_id=2,
            full_name="main.asset.codes",
            alias="t1",
            table_alias=None,
            is_primary=False,
            sort_order=1,
            filter_mode="EXISTS",
            cardinality="MANY",
        ),
    ]
    plan = DomainPlan(
        primary=tables[0],
        tables=tables,
        joins=joins,
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )

    svc = NoCodeQueryService(executor=FakeExecutor(), domain_resolver=FakeDomainResolver(plan))

    q = {
        "version": 1,
        "domainId": 99,
        "columns": [{"columnName": "patient_id"}],
        "filters": {
            "type": "group",
            "id": "g1",
            "match": "and",
            "children": [
                {
                    "type": "condition",
                    "id": "c1",
                    "existsScopeId": "bucket-1",
                    "field": {"workspaceTableId": 2, "columnName": "code"},
                    "op": "equals",
                    "value": "A1",
                },
                {
                    "type": "condition",
                    "id": "c2",
                    "existsScopeId": "bucket-2",
                    "field": {"workspaceTableId": 2, "columnName": "code"},
                    "op": "equals",
                    "value": "B2",
                },
            ],
        },
        "sorting": [],
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    compiled = svc.compile(svc.normalize(q), mode="preview")

    assert compiled.sql.count("EXISTS") == 2
    assert "FROM main.asset.codes e1" in compiled.sql
    assert "FROM main.asset.codes e2" in compiled.sql
    assert compiled.params == {"p1": "A1", "p2": "B2"}


def test_compile_distinct_select():
    primary = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.patients",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    plan = DomainPlan(
        primary=primary,
        tables=[primary],
        joins=[],
        alias_by_workspace_table_id={1: "t0"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )

    svc = NoCodeQueryService(executor=FakeExecutor(), domain_resolver=FakeDomainResolver(plan))
    q = {
        "version": 1,
        "domainId": 99,
        "columns": [{"columnName": "patient_id"}],
        "filters": None,
        "sorting": [],
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
        "distinct": True,
    }

    compiled = svc.compile(svc.normalize(q), mode="preview")
    assert compiled.sql.startswith("SELECT DISTINCT")


def test_compile_distinct_with_aggs_errors():
    primary = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.patients",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    plan = DomainPlan(
        primary=primary,
        tables=[primary],
        joins=[],
        alias_by_workspace_table_id={1: "t0"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )

    svc = NoCodeQueryService(executor=FakeExecutor(), domain_resolver=FakeDomainResolver(plan))
    q = {
        "version": 1,
        "domainId": 99,
        "columns": [{"columnName": "patient_id"}],
        "filters": None,
        "sorting": [],
        "aggs": {"enabled": True, "metrics": [], "groupBy": []},
        "distinct": True,
    }

    with pytest.raises(ServiceError):
        svc.compile(svc.normalize(q), mode="preview")


def test_compile_aggs_group_by_and_metric():
    primary = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.patients",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    plan = DomainPlan(
        primary=primary,
        tables=[primary],
        joins=[],
        alias_by_workspace_table_id={1: "t0"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )

    svc = NoCodeQueryService(executor=FakeExecutor(), domain_resolver=FakeDomainResolver(plan))
    q = {
        "version": 1,
        "domainId": 99,
        "columns": [],
        "filters": None,
        "sorting": [],
        "aggs": {
            "enabled": True,
            "groupBy": [{"columnName": "gender"}],
            "metrics": [{"fn": "count_distinct", "field": {"columnName": "patient_id"}, "label": "Distinct"}],
        },
    }

    compiled = svc.compile(svc.normalize(q), mode="preview")
    assert "GROUP BY t0.gender" in compiled.sql
    assert "COUNT(DISTINCT t0.patient_id) AS Distinct" in compiled.sql


def test_compile_auto_alias_for_duplicates():
    joins = [
        DomainPlanJoin(
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
    ]
    tables = [
        DomainPlanTable(
            workspace_table_id=1,
            full_name="main.asset.dx",
            alias="t0",
            table_alias="dx",
            is_primary=True,
            sort_order=0,
            filter_mode="AUTO",
            cardinality="ONE",
        ),
        DomainPlanTable(
            workspace_table_id=2,
            full_name="main.asset.px",
            alias="t1",
            table_alias="px",
            is_primary=False,
            sort_order=1,
            filter_mode="AUTO",
            cardinality="ONE",
        ),
    ]
    plan = DomainPlan(
        primary=tables[0],
        tables=tables,
        joins=joins,
        alias_by_workspace_table_id={1: "t0", 2: "t1"},
        column_name_policy="SHOW_ALL_QUALIFIED",
    )

    svc = NoCodeQueryService(executor=FakeExecutor(), domain_resolver=FakeDomainResolver(plan))
    q = {
        "version": 1,
        "domainId": 99,
        "columns": [
            {"columnName": "code", "workspaceTableId": 1},
            {"columnName": "code", "workspaceTableId": 2},
        ],
        "filters": None,
        "sorting": [],
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    compiled = svc.compile(svc.normalize(q), mode="preview")
    assert "t0.code AS dx_code" in compiled.sql
    assert "t1.code AS px_code" in compiled.sql


def test_compile_duplicate_output_names_error():
    primary = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.patients",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    plan = DomainPlan(
        primary=primary,
        tables=[primary],
        joins=[],
        alias_by_workspace_table_id={1: "t0"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )

    svc = NoCodeQueryService(executor=FakeExecutor(), domain_resolver=FakeDomainResolver(plan))
    q = {
        "version": 1,
        "domainId": 99,
        "columns": [
            {"columnName": "patient_id", "alias": "dup"},
            {"columnName": "gender", "alias": "dup"},
        ],
        "filters": None,
        "sorting": [],
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    with pytest.raises(ServiceError):
        svc.compile(svc.normalize(q), mode="preview")


def test_compile_data_prep_fill_empty():
    primary = DomainPlanTable(
        workspace_table_id=1,
        full_name="main.asset.patients",
        alias="t0",
        table_alias=None,
        is_primary=True,
        sort_order=0,
        filter_mode="AUTO",
        cardinality="ONE",
    )
    plan = DomainPlan(
        primary=primary,
        tables=[primary],
        joins=[],
        alias_by_workspace_table_id={1: "t0"},
        column_name_policy="DEDUP_PRIMARY_FIRST",
    )

    svc = NoCodeQueryService(executor=FakeExecutor(), domain_resolver=FakeDomainResolver(plan))
    q = {
        "version": 1,
        "domainId": 99,
        "columns": [{"columnName": "gender"}],
        "filters": None,
        "sorting": [],
        "dataPrep": {
            "rules": [
                {
                    "id": "r1",
                    "op": "fill_empty",
                    "target": {"columnName": "gender"},
                    "output": {"columnName": "gender_filled"},
                    "treatBlankAsEmpty": True,
                    "value": "U",
                }
            ]
        },
        "aggs": {"enabled": False, "metrics": [], "groupBy": []},
    }

    compiled = svc.compile(svc.normalize(q), mode="preview")
    assert compiled.sql.startswith("WITH prep AS")
