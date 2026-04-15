"""Phase 8 — tests for app/services/query_forge/service.py public interface."""
from __future__ import annotations

import pytest

from app.services.domain_resolver import DomainPlan, DomainPlanTable


def _make_plan() -> DomainPlan:
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


class FakeResolver:
    def __init__(self, plan: DomainPlan) -> None:
        self._plan = plan

    def resolve_plan(self, domain_id: int) -> DomainPlan:
        del domain_id
        return self._plan

    def get_join_path(self, plan: DomainPlan, to_workspace_table_id: int):
        return []


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list = []

    def submit_statement(self, sql: str, *, parameters=None, **_kwargs) -> dict:
        self.calls.append((sql, parameters))
        return {"rows": []}


class TestImports:
    def test_importable_from_new_package_path(self):
        from app.services.query_forge.service import QueryForgeService  # noqa: F401
        assert QueryForgeService is not None



class TestInstantiation:
    def test_can_instantiate_with_mock_executor_and_resolver(self):
        from app.services.query_forge.service import QueryForgeService

        svc = QueryForgeService(
            executor=FakeExecutor(),
            domain_resolver=FakeResolver(_make_plan()),
        )
        assert svc is not None


class TestRunSignature:
    def test_run_accepts_query_json_as_first_positional(self):
        """run(query_json, mode=...) must accept query_json positionally."""
        from app.services.query_forge.service import QueryForgeService

        executor = FakeExecutor()
        executor.submit_statement = lambda sql, parameters=None, **kw: {"rows": [{"total": 0}]}
        svc = QueryForgeService(
            executor=executor,
            domain_resolver=FakeResolver(_make_plan()),
        )
        # Minimal valid query — one column, no filters
        q = {
            "domainId": 1,
            "columns": [{"columnName": "id", "workspaceTableId": 1}],
            "filters": None,
            "sorting": [],
            "aggs": None,
        }
        result = svc.run(q, mode="preview")
        from app.services.query_forge.types import QueryForgeRunResult
        assert isinstance(result, QueryForgeRunResult)

    def test_run_rejects_raw_query_as_keyword(self):
        """raw_query keyword was renamed to query_json — old callers should fail fast."""
        from app.services.query_forge.service import QueryForgeService

        svc = QueryForgeService(
            executor=FakeExecutor(),
            domain_resolver=FakeResolver(_make_plan()),
        )
        q = {"domainId": 1, "columns": [], "filters": None, "sorting": [], "aggs": None}
        with pytest.raises(TypeError):
            svc.run(raw_query=q, mode="preview")  # type: ignore[call-arg]

    def test_run_mode_is_keyword_only(self):
        """mode must be keyword-only so positional callers are caught at call time."""
        from app.services.query_forge.service import QueryForgeService
        import inspect

        sig = inspect.signature(QueryForgeService.run)
        mode_param = sig.parameters.get("mode")
        assert mode_param is not None
        assert mode_param.kind == inspect.Parameter.KEYWORD_ONLY


class TestPrepareSignature:
    def test_prepare_rejects_raw_query_as_keyword(self):
        from app.services.query_forge.service import QueryForgeService

        svc = QueryForgeService(
            executor=FakeExecutor(),
            domain_resolver=FakeResolver(_make_plan()),
        )
        q = {"domainId": 1, "columns": [], "filters": None, "sorting": [], "aggs": None}
        with pytest.raises(TypeError):
            svc.prepare(raw_query=q, mode="preview")  # type: ignore[call-arg]

    def test_prepare_mode_is_keyword_only(self):
        from app.services.query_forge.service import QueryForgeService
        import inspect

        sig = inspect.signature(QueryForgeService.prepare)
        mode_param = sig.parameters.get("mode")
        assert mode_param is not None
        assert mode_param.kind == inspect.Parameter.KEYWORD_ONLY
