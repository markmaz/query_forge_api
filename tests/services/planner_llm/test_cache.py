from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from app.services.planner_llm.cache import PlannerLLMCache


class _CaptureSQL:
    def __init__(self) -> None:
        self.query = None
        self.params = None

    def execute_write(self, query, _params=None):
        self.query = query
        self.params = _params
        return 1


def test_set_writes_without_vertical_column() -> None:
    sql = _CaptureSQL()
    cache = PlannerLLMCache(sql=sql)

    cache.set(
        cache_key="abc",
        workspace_id="ws-1",
        normalized_prompt="students by county",
        constraints={},
        registry_version="v1",
        plan_json={"intent": "list"},
        sql_json={"query": "select 1"},
        validation={"is_valid": True},
        candidates={"domains": [], "concepts": [], "columns": []},
    )

    assert sql.query is not None
    assert "vertical" not in sql.query.lower()
    assert "vertical" not in sql.params


def test_get_returns_cached_payloads() -> None:
    class _SQL:
        def execute_query_mappings(self, _query, _params=None):
            return [
                {
                    "cache_key": "abc",
                    "plan_json": '{"intent":"list"}',
                    "sql_json": '{"query":"select 1"}',
                    "validation_json": '{"is_valid":true}',
                    "candidates_json": '{"domains":[{"domain_id":1}],"concepts":[],"columns":[]}',
                }
            ]

    cache = PlannerLLMCache(sql=_SQL())
    out = cache.get(cache_key="abc", registry_version="v1")

    assert out == {
        "plan_json": {"intent": "list"},
        "sql_json": {"query": "select 1"},
        "validation": {"is_valid": True},
        "candidates": {"domains": [{"domain_id": 1}], "concepts": [], "columns": []},
    }


def test_get_returns_none_when_cache_table_missing() -> None:
    class _SQL:
        def execute_query_mappings(self, _query, _params=None):
            raise SQLAlchemyError("1146 Table 'forge.planner_cache' doesn't exist")

    cache = PlannerLLMCache(sql=_SQL())

    assert cache.get(cache_key="abc", registry_version="v1") is None


def test_get_surfaces_unexpected_sql_errors() -> None:
    class _SQL:
        def execute_query_mappings(self, _query, _params=None):
            raise RuntimeError("query wiring bug")

    cache = PlannerLLMCache(sql=_SQL())

    try:
        cache.get(cache_key="abc", registry_version="v1")
    except RuntimeError as exc:
        assert str(exc) == "query wiring bug"
    else:
        raise AssertionError("expected RuntimeError to propagate")


def test_set_skips_write_when_cache_table_missing() -> None:
    class _SQL:
        def execute_write(self, _query, _params=None):
            raise SQLAlchemyError("1146 Table 'forge.planner_cache' doesn't exist")

    cache = PlannerLLMCache(sql=_SQL())

    cache.set(
        cache_key="abc",
        workspace_id="ws-1",
        normalized_prompt="students by county",
        constraints={},
        registry_version="v1",
        plan_json={"intent": "list"},
        sql_json={"query": "select 1"},
        validation={"is_valid": True},
        candidates={"domains": [], "concepts": [], "columns": []},
    )


def test_set_surfaces_unexpected_sql_errors() -> None:
    class _SQL:
        def execute_write(self, _query, _params=None):
            raise RuntimeError("write bug")

    cache = PlannerLLMCache(sql=_SQL())

    try:
        cache.set(
            cache_key="abc",
            workspace_id="ws-1",
            normalized_prompt="students by county",
            constraints={},
            registry_version="v1",
            plan_json={"intent": "list"},
            sql_json={"query": "select 1"},
            validation={"is_valid": True},
            candidates={"domains": [], "concepts": [], "columns": []},
        )
    except RuntimeError as exc:
        assert str(exc) == "write bug"
    else:
        raise AssertionError("expected RuntimeError to propagate")
