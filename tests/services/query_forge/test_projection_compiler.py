from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.query_forge.projection_compiler import QueryForgeProjectionCompiler


def _compiler():
    return QueryForgeProjectionCompiler(
        col_expr=lambda *args, **kwargs: "t1.age",
        compile_metric=lambda *args, **kwargs: "COUNT(*)",
        safe_alias=lambda value: value,
        col_label_key=lambda value: value.get("columnName") if isinstance(value, dict) else str(value),
    )


def _plan():
    return SimpleNamespace(
        tables=[
            SimpleNamespace(workspace_table_id=20, table_alias="t1", alias="t1"),
        ]
    )


def test_projection_compile_ignores_expected_group_alias_hint_parse_errors():
    compiler = _compiler()
    result = compiler.compile(
        raw_cols=[],
        aggs={
            "enabled": True,
            "groupBy": [{"workspaceTableId": "bad", "columnName": "age"}],
            "metrics": [],
        },
        distinct=False,
        plan=_plan(),
        derived_by_exprid={},
        derived_by_name={},
        rewrite_by_colname={},
        rewrite_by_modelid={},
        rewrite_by_wt_col={},
        qf_using_prep=False,
        qf_base_alias="t1",
        alias_by_wt={20: "t1"},
    )

    assert result.qf_output_cols[0]["key"] == "age"


def test_projection_compile_surfaces_unexpected_group_alias_hint_parse_errors():
    class _BadInt:
        def __int__(self):
            raise AssertionError("int bug")

    compiler = _compiler()

    with pytest.raises(AssertionError, match="int bug"):
        compiler.compile(
            raw_cols=[],
            aggs={
                "enabled": True,
                "groupBy": [{"workspaceTableId": _BadInt(), "columnName": "age"}],
                "metrics": [],
            },
            distinct=False,
            plan=_plan(),
            derived_by_exprid={},
            derived_by_name={},
            rewrite_by_colname={},
            rewrite_by_modelid={},
            rewrite_by_wt_col={},
            qf_using_prep=False,
            qf_base_alias="t1",
            alias_by_wt={20: "t1"},
        )


def test_projection_compile_ignores_expected_nonagg_alias_hint_parse_errors():
    compiler = _compiler()
    result = compiler.compile(
        raw_cols=[{"workspaceTableId": "bad", "columnName": "age"}],
        aggs={},
        distinct=False,
        plan=_plan(),
        derived_by_exprid={},
        derived_by_name={},
        rewrite_by_colname={},
        rewrite_by_modelid={},
        rewrite_by_wt_col={},
        qf_using_prep=False,
        qf_base_alias="t1",
        alias_by_wt={20: "t1"},
    )

    assert result.qf_output_cols[0]["key"] == "age"
