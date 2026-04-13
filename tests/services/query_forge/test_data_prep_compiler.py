"""Phase 5 — tests for app/services/query_forge/data_prep_compiler.py."""
from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError


_CAST_RULE_QUERY = {
    "dataPrep": {
        "rules": [
            {
                "id": "r1",
                "op": "cast",
                "target": {"columnName": "age"},
                "output": {"columnName": "age_int"},
                "toType": "INT",
            }
        ]
    }
}

_DOMAIN_COLUMNS = {(1, "age"): {"data_type": "string"}}
_ALIAS_BY_WT = {1: "t1"}
_QF_BASE_ALIAS = "t1"
_WS_TABLE_IDS = [1]


class TestDataPrepCompilerNoDataPrep:
    def test_no_data_prep_returns_empty_cte_and_empty_context(self):
        from app.services.query_forge.data_prep_compiler import DataPrepCompiler
        from app.services.query_forge.types import CompilationContext

        cte_sql, ctx = DataPrepCompiler().compile(
            query_json={"columns": []},
            alias_by_wt=_ALIAS_BY_WT,
            qf_base_alias=_QF_BASE_ALIAS,
        )
        assert cte_sql == ""
        assert isinstance(ctx, CompilationContext)
        assert ctx.derived_by_exprid == {}
        assert ctx.derived_by_name == {}
        assert ctx.rewrite_by_colname == {}
        assert ctx.rewrite_by_modelid == {}
        assert ctx.rewrite_by_wt_col == {}

    def test_empty_data_prep_rules_returns_empty(self):
        from app.services.query_forge.data_prep_compiler import DataPrepCompiler

        cte_sql, ctx = DataPrepCompiler().compile(
            query_json={"dataPrep": {"rules": []}},
            alias_by_wt=_ALIAS_BY_WT,
            qf_base_alias=_QF_BASE_ALIAS,
        )
        assert cte_sql == ""
        assert ctx.derived_by_exprid == {}


class TestDataPrepCompilerCastRule:
    def test_cast_rule_returns_non_empty_cte(self):
        from app.services.query_forge.data_prep_compiler import DataPrepCompiler

        cte_sql, ctx = DataPrepCompiler().compile(
            query_json=_CAST_RULE_QUERY,
            alias_by_wt=_ALIAS_BY_WT,
            qf_base_alias=_QF_BASE_ALIAS,
        )
        assert "WITH prep AS" in cte_sql
        assert "CAST" in cte_sql
        assert "__dp_age_int" in cte_sql

    def test_cast_rule_populates_derived_by_exprid(self):
        from app.services.query_forge.data_prep_compiler import DataPrepCompiler

        _, ctx = DataPrepCompiler().compile(
            query_json=_CAST_RULE_QUERY,
            alias_by_wt=_ALIAS_BY_WT,
            qf_base_alias=_QF_BASE_ALIAS,
        )
        assert "r1" in ctx.derived_by_exprid
        assert ctx.derived_by_exprid["r1"] == "__dp_age_int"

    def test_cast_rule_populates_derived_by_name(self):
        from app.services.query_forge.data_prep_compiler import DataPrepCompiler

        _, ctx = DataPrepCompiler().compile(
            query_json=_CAST_RULE_QUERY,
            alias_by_wt=_ALIAS_BY_WT,
            qf_base_alias=_QF_BASE_ALIAS,
        )
        assert ctx.derived_by_name.get("age_int") == "__dp_age_int"

    def test_cast_rule_populates_rewrite_by_colname(self):
        from app.services.query_forge.data_prep_compiler import DataPrepCompiler

        _, ctx = DataPrepCompiler().compile(
            query_json=_CAST_RULE_QUERY,
            alias_by_wt=_ALIAS_BY_WT,
            qf_base_alias=_QF_BASE_ALIAS,
        )
        assert ctx.rewrite_by_colname.get("age") == "__dp_age_int"


class TestDataPrepCompilerValidation:
    def test_rule_with_invalid_op_raises_forge_error(self):
        from app.services.query_forge.data_prep_compiler import DataPrepCompiler

        q = {
            "dataPrep": {
                "rules": [
                    {
                        "id": "r1",
                        "op": "unknown_op",
                        "target": {"columnName": "age"},
                        "output": {"columnName": "age_x"},
                    }
                ]
            }
        }
        with pytest.raises(ForgeError):
            DataPrepCompiler().compile(
                query_json=q,
                alias_by_wt=_ALIAS_BY_WT,
                qf_base_alias=_QF_BASE_ALIAS,
            )

    def test_rule_missing_id_raises_forge_error(self):
        from app.services.query_forge.data_prep_compiler import DataPrepCompiler

        q = {
            "dataPrep": {
                "rules": [
                    {
                        "op": "cast",
                        "target": {"columnName": "age"},
                        "output": {"columnName": "age_int"},
                        "toType": "INT",
                    }
                ]
            }
        }
        with pytest.raises(ForgeError):
            DataPrepCompiler().compile(
                query_json=q,
                alias_by_wt=_ALIAS_BY_WT,
                qf_base_alias=_QF_BASE_ALIAS,
            )

    def test_stateless_no_constructor_args(self):
        from app.services.query_forge.data_prep_compiler import DataPrepCompiler
        # Should construct with no args
        compiler = DataPrepCompiler()
        assert compiler is not None

    def test_compile_skips_invalid_workspace_table_ids(self):
        from app.services.query_forge.data_prep_compiler import DataPrepCompiler

        base_selects, by_colname, by_modelid, by_wt_col = DataPrepCompiler().build_prep_base_selects(
            required_cols=[
                {"workspaceTableId": 1, "columnName": "age"},
                {"workspaceTableId": "bad", "columnName": "age"},
            ],
            primary_id=1,
            qf_base_alias=_QF_BASE_ALIAS,
            alias_by_wt=_ALIAS_BY_WT,
        )

        assert base_selects == ["t1.age AS age"]
        assert by_colname == {"age": "age"}
        assert by_modelid == {}
        assert by_wt_col == {(1, "age"): "age"}

    def test_compile_surfaces_unexpected_workspace_table_id_errors(self):
        from app.services.query_forge.data_prep_compiler import DataPrepCompiler

        class _BadInt:
            def __int__(self) -> int:
                raise AssertionError("unexpected workspace table conversion failure")

        with pytest.raises(AssertionError, match="unexpected workspace table conversion failure"):
            DataPrepCompiler().build_prep_base_selects(
                required_cols=[{"workspaceTableId": _BadInt(), "columnName": "age"}],
                primary_id=1,
                qf_base_alias=_QF_BASE_ALIAS,
                alias_by_wt=_ALIAS_BY_WT,
            )
