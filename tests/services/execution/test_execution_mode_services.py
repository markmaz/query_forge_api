from __future__ import annotations

from app.services.execution.execution_mode_query_builder import ExecutionModeQueryBuilder
from app.services.execution.execution_mode_query_builder_sql import ExecutionModeQueryBuilderSql


def test_query_builder_mode_prepares_sql_from_query_forge_service() -> None:
    class _Prepared:
        sql = "SELECT 1"
        params = {"a": 1}
        qf_rendered_sql = "SELECT 1"
        qf_count_sql = "SELECT COUNT(*) AS total"

    class _QueryForgeService:
        def __init__(self, executor, domain_resolver):
            self.executor = executor
            self.domain_resolver = domain_resolver

        def prepare(self, raw_query, mode="preview", limit=200, offset=0):
            assert raw_query == {"domainId": 1}
            assert mode == "preview"
            assert limit == 5
            assert offset == 10
            return _Prepared()

    mode = ExecutionModeQueryBuilder(
        query_forge_service_cls=_QueryForgeService,
        domain_resolver_factory=lambda workspace_id: {"workspace_id": workspace_id},
    )

    prepared = mode.prepare(
        workspace_id="ws-1",
        sql_exec=object(),
        sql_json={"domainId": 1},
        mode="preview",
        limit=5,
        offset=10,
    )

    assert prepared.sql == "SELECT 1"
    assert prepared.params == {"a": 1}
    assert prepared.sql_rendered == "SELECT 1"
    assert prepared.count_sql == "SELECT COUNT(*) AS total"


def test_query_builder_sql_mode_wraps_raw_sql() -> None:
    prepared = ExecutionModeQueryBuilderSql().prepare(raw_sql="SELECT 7")
    assert prepared.sql == "SELECT 7"
    assert prepared.params == {}
    assert prepared.sql_rendered == "SELECT 7"
    assert prepared.count_sql is None
