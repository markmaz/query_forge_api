"""Phase 7 — tests for app/services/query_forge/where_compiler.py."""
from __future__ import annotations

import pytest
import app.services.query_forge.where_compiler as where_compiler_module

from app.exceptions.forge_error import ForgeError


class TestIsAndOnlyFilterTree:
    def test_none_returns_true(self):
        from app.services.query_forge.where_compiler import is_and_only_filter_tree
        assert is_and_only_filter_tree(None) is True

    def test_empty_dict_returns_true(self):
        from app.services.query_forge.where_compiler import is_and_only_filter_tree
        assert is_and_only_filter_tree({}) is True

    def test_single_condition_returns_true(self):
        from app.services.query_forge.where_compiler import is_and_only_filter_tree
        node = {"type": "condition", "field": {"columnName": "age"}, "op": "gt", "value": 5}
        assert is_and_only_filter_tree(node) is True

    def test_and_group_returns_true(self):
        from app.services.query_forge.where_compiler import is_and_only_filter_tree
        node = {
            "type": "group",
            "match": "and",
            "children": [
                {"type": "condition", "field": {"columnName": "a"}, "op": "equals", "value": 1},
                {"type": "condition", "field": {"columnName": "b"}, "op": "equals", "value": 2},
            ],
        }
        assert is_and_only_filter_tree(node) is True

    def test_or_group_returns_false(self):
        from app.services.query_forge.where_compiler import is_and_only_filter_tree
        node = {
            "type": "group",
            "match": "or",
            "children": [
                {"type": "condition", "field": {"columnName": "a"}, "op": "equals", "value": 1},
            ],
        }
        assert is_and_only_filter_tree(node) is False


class TestFlattenAndConditions:
    def test_none_returns_empty(self):
        from app.services.query_forge.where_compiler import flatten_and_conditions
        assert flatten_and_conditions(None) == []

    def test_single_condition_returns_list_with_it(self):
        from app.services.query_forge.where_compiler import flatten_and_conditions
        node = {"type": "condition", "field": {"columnName": "age"}, "op": "gt", "value": 5}
        assert flatten_and_conditions(node) == [node]

    def test_nested_group_flattened(self):
        from app.services.query_forge.where_compiler import flatten_and_conditions
        c1 = {"type": "condition", "field": {"columnName": "a"}, "op": "equals", "value": 1}
        c2 = {"type": "condition", "field": {"columnName": "b"}, "op": "equals", "value": 2}
        node = {"type": "group", "match": "and", "children": [c1, c2]}
        result = flatten_and_conditions(node)
        assert result == [c1, c2]


class TestBuildAndFilterTree:
    def test_empty_list_returns_none(self):
        from app.services.query_forge.where_compiler import build_and_filter_tree
        assert build_and_filter_tree([]) is None

    def test_single_condition_returned_directly(self):
        from app.services.query_forge.where_compiler import build_and_filter_tree
        c = {"type": "condition"}
        assert build_and_filter_tree([c]) is c

    def test_multiple_conditions_wrapped_in_group(self):
        from app.services.query_forge.where_compiler import build_and_filter_tree
        c1 = {"type": "condition"}
        c2 = {"type": "condition"}
        result = build_and_filter_tree([c1, c2])
        assert result is not None
        assert result["type"] == "group"
        assert result["match"] == "and"
        assert c1 in result["children"]
        assert c2 in result["children"]


class TestWhereCompilerFilters:
    """Test WhereCompiler.compile() with simple filter nodes."""

    def _make_compiler_and_params(self):
        from app.services.query_forge.where_compiler import WhereCompiler
        from app.services.query_forge.types import CompilationContext

        ctx = CompilationContext(
            derived_by_exprid={},
            derived_by_name={},
            rewrite_by_colname={},
            rewrite_by_modelid={},
            rewrite_by_wt_col={},
        )
        params: dict = {}
        counter = [0]

        def new_param(v):
            counter[0] += 1
            key = f"p{counter[0]}"
            params[key] = v
            return f":{key}"

        compiler = WhereCompiler()
        return compiler, ctx, new_param, params

    def test_empty_node_returns_empty_string(self):
        compiler, ctx, new_param, _ = self._make_compiler_and_params()
        sql, issues = compiler.compile(
            node=None,
            context=ctx,
            qf_using_prep=False,
            qf_base_alias="t1",
            alias_by_wt={1: "t1"},
            plan=None,
            new_param=new_param,
            filter_mode_fn=lambda plan, tid: "WHERE",
        )
        assert sql == ""
        assert issues == []

    def test_equals_condition_produces_param_binding(self):
        compiler, ctx, new_param, params = self._make_compiler_and_params()
        node = {"type": "condition", "field": {"columnName": "age"}, "op": "equals", "value": 30}
        sql, _ = compiler.compile(
            node=node,
            context=ctx,
            qf_using_prep=False,
            qf_base_alias="t1",
            alias_by_wt={1: "t1"},
            plan=None,
            new_param=new_param,
            filter_mode_fn=lambda plan, tid: "WHERE",
        )
        assert "age" in sql
        assert ":p1" in sql
        assert params["p1"] == 30

    def test_is_null_produces_is_null_clause(self):
        compiler, ctx, new_param, _ = self._make_compiler_and_params()
        node = {"type": "condition", "field": {"columnName": "region"}, "op": "is_null"}
        sql, _ = compiler.compile(
            node=node,
            context=ctx,
            qf_using_prep=False,
            qf_base_alias="t1",
            alias_by_wt={1: "t1"},
            plan=None,
            new_param=new_param,
            filter_mode_fn=lambda plan, tid: "WHERE",
        )
        assert "IS NULL" in sql

    def test_is_not_null_produces_is_not_null_clause(self):
        compiler, ctx, new_param, _ = self._make_compiler_and_params()
        node = {"type": "condition", "field": {"columnName": "region"}, "op": "is_not_null"}
        sql, _ = compiler.compile(
            node=node,
            context=ctx,
            qf_using_prep=False,
            qf_base_alias="t1",
            alias_by_wt={1: "t1"},
            plan=None,
            new_param=new_param,
            filter_mode_fn=lambda plan, tid: "WHERE",
        )
        assert "IS NOT NULL" in sql

    def test_in_filter_produces_in_clause(self):
        compiler, ctx, new_param, params = self._make_compiler_and_params()
        node = {"type": "condition", "field": {"columnName": "status"}, "op": "in", "value": ["A", "B"]}
        sql, _ = compiler.compile(
            node=node,
            context=ctx,
            qf_using_prep=False,
            qf_base_alias="t1",
            alias_by_wt={1: "t1"},
            plan=None,
            new_param=new_param,
            filter_mode_fn=lambda plan, tid: "WHERE",
        )
        assert " IN " in sql
        assert len(params) == 2

    def test_in_filter_bracket_string_falls_back_to_literal_eval(self):
        compiler, ctx, new_param, params = self._make_compiler_and_params()
        node = {"type": "condition", "field": {"columnName": "status"}, "op": "in", "value": "['A', 'B']"}
        sql, _ = compiler.compile(
            node=node,
            context=ctx,
            qf_using_prep=False,
            qf_base_alias="t1",
            alias_by_wt={1: "t1"},
            plan=None,
            new_param=new_param,
            filter_mode_fn=lambda plan, tid: "WHERE",
        )
        assert " IN " in sql
        assert params == {"p1": "A", "p2": "B"}

    def test_in_filter_surfaces_unexpected_json_parse_failures(self, monkeypatch: pytest.MonkeyPatch):
        compiler, ctx, new_param, _ = self._make_compiler_and_params()
        node = {"type": "condition", "field": {"columnName": "status"}, "op": "in", "value": "['A', 'B']"}
        monkeypatch.setattr(
            where_compiler_module.json,
            "loads",
            lambda value: (_ for _ in ()).throw(AssertionError("json bug")),
        )

        with pytest.raises(AssertionError, match="json bug"):
            compiler.compile(
                node=node,
                context=ctx,
                qf_using_prep=False,
                qf_base_alias="t1",
                alias_by_wt={1: "t1"},
                plan=None,
                new_param=new_param,
                filter_mode_fn=lambda plan, tid: "WHERE",
            )

    def test_gt_produces_greater_than_clause(self):
        compiler, ctx, new_param, _ = self._make_compiler_and_params()
        node = {"type": "condition", "field": {"columnName": "score"}, "op": "gt", "value": 50}
        sql, _ = compiler.compile(
            node=node,
            context=ctx,
            qf_using_prep=False,
            qf_base_alias="t1",
            alias_by_wt={1: "t1"},
            plan=None,
            new_param=new_param,
            filter_mode_fn=lambda plan, tid: "WHERE",
        )
        assert " > " in sql

    def test_unknown_operator_raises_forge_error(self):
        compiler, ctx, new_param, _ = self._make_compiler_and_params()
        node = {"type": "condition", "field": {"columnName": "col"}, "op": "zzzunknown", "value": 1}
        with pytest.raises(ForgeError):
            compiler.compile(
                node=node,
                context=ctx,
                qf_using_prep=False,
                qf_base_alias="t1",
                alias_by_wt={1: "t1"},
                plan=None,
                new_param=new_param,
                filter_mode_fn=lambda plan, tid: "WHERE",
            )

    def test_stateless_no_constructor_args(self):
        from app.services.query_forge.where_compiler import WhereCompiler
        compiler = WhereCompiler()
        assert compiler is not None
