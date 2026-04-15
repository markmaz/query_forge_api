"""Phase 1 — tests for app/services/query_forge/types.py.

Written BEFORE the production module exists (TDD red phase).
"""
from __future__ import annotations

import pytest
from dataclasses import FrozenInstanceError


# ---------------------------------------------------------------------------
# CompilationContext
# ---------------------------------------------------------------------------


class TestCompilationContext:
    def test_can_construct_with_all_five_fields(self):
        from app.services.query_forge.types import CompilationContext

        ctx = CompilationContext(
            derived_by_exprid={"e1": {"col": "revenue"}},
            derived_by_name={"revenue": {"col": "revenue"}},
            rewrite_by_colname={"col_a": "col_b"},
            rewrite_by_modelid={1: "alias_col"},
            rewrite_by_wt_col={(2, "col_a"): "prep_col"},
        )
        assert ctx.derived_by_exprid == {"e1": {"col": "revenue"}}
        assert ctx.derived_by_name == {"revenue": {"col": "revenue"}}
        assert ctx.rewrite_by_colname == {"col_a": "col_b"}
        assert ctx.rewrite_by_modelid == {1: "alias_col"}
        assert ctx.rewrite_by_wt_col == {(2, "col_a"): "prep_col"}

    def test_is_immutable(self):
        from app.services.query_forge.types import CompilationContext

        ctx = CompilationContext(
            derived_by_exprid={},
            derived_by_name={},
            rewrite_by_colname={},
            rewrite_by_modelid={},
            rewrite_by_wt_col={},
        )
        with pytest.raises(FrozenInstanceError):
            ctx.derived_by_exprid = {"new": "value"}  # type: ignore[misc]

    def test_empty_dicts_are_valid(self):
        from app.services.query_forge.types import CompilationContext

        ctx = CompilationContext(
            derived_by_exprid={},
            derived_by_name={},
            rewrite_by_colname={},
            rewrite_by_modelid={},
            rewrite_by_wt_col={},
        )
        assert ctx.derived_by_exprid == {}
        assert ctx.derived_by_name == {}


# ---------------------------------------------------------------------------
# ForgeCompiledQuery
# ---------------------------------------------------------------------------


class TestForgeCompiledQuery:
    def test_has_correct_fields_and_is_frozen(self):
        from app.services.query_forge.types import ForgeCompiledQuery

        q = ForgeCompiledQuery(
            sql="SELECT 1",
            qf_count_sql="SELECT COUNT(*) FROM (SELECT 1)",
            params={"p0": "val"},
            qf_output_cols=[{"name": "col1"}],
        )
        assert q.sql == "SELECT 1"
        assert q.qf_count_sql == "SELECT COUNT(*) FROM (SELECT 1)"
        assert q.params == {"p0": "val"}
        assert q.qf_output_cols == [{"name": "col1"}]

    def test_is_frozen(self):
        from app.services.query_forge.types import ForgeCompiledQuery

        q = ForgeCompiledQuery(sql="SELECT 1", qf_count_sql="", params={}, qf_output_cols=[])
        with pytest.raises(FrozenInstanceError):
            q.sql = "SELECT 2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# QueryForgeRunResult
# ---------------------------------------------------------------------------


class TestQueryForgeRunResult:
    def test_has_correct_fields_and_is_frozen(self):
        from app.services.query_forge.types import QueryForgeRunResult

        r = QueryForgeRunResult(
            sql="SELECT 1",
            qf_rendered_sql="SELECT 1",
            params={},
            rows=[{"col": 1}],
            columns=[{"name": "col"}],
            total=1,
            limit=20,
            offset=0,
        )
        assert r.total == 1
        assert r.limit == 20
        assert r.offset == 0

    def test_is_frozen(self):
        from app.services.query_forge.types import QueryForgeRunResult

        r = QueryForgeRunResult(
            sql="", qf_rendered_sql="", params={}, rows=[], columns=[], total=0, limit=20, offset=0
        )
        with pytest.raises(FrozenInstanceError):
            r.total = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# QueryForgePreparedQuery
# ---------------------------------------------------------------------------


class TestQueryForgePreparedQuery:
    def test_has_correct_fields_and_is_frozen(self):
        from app.services.query_forge.types import QueryForgePreparedQuery

        p = QueryForgePreparedQuery(
            sql="SELECT 1",
            qf_rendered_sql="SELECT 1",
            params={},
            qf_count_sql="SELECT COUNT(*)",
            columns=[],
            limit=200,
            offset=0,
        )
        assert p.sql == "SELECT 1"
        assert p.limit == 200

    def test_is_frozen(self):
        from app.services.query_forge.types import QueryForgePreparedQuery

        p = QueryForgePreparedQuery(
            sql="", qf_rendered_sql="", params={}, qf_count_sql="", columns=[], limit=200, offset=0
        )
        with pytest.raises(FrozenInstanceError):
            p.limit = 500  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Import shim — QueryForgeService still importable from old path
# ---------------------------------------------------------------------------


class TestImportShim:
    def test_query_forge_service_importable_from_legacy_path(self):
        """The shim at query_forge_service.py must still resolve."""
        from app.services.query_forge.service import QueryForgeService  # noqa: F401

        assert QueryForgeService is not None
