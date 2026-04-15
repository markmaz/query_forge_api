from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.query_forge.requirements import QueryForgeRequirementAnalyzer


def _plan():
    primary = SimpleNamespace(workspace_table_id=20)
    return SimpleNamespace(primary=primary)


def _normalize_col_key(value, path):
    del path
    if isinstance(value, dict):
        return dict(value)
    return {"columnName": str(value), "workspaceTableId": None, "modelColumnId": None, "exprId": None}


def _effective_filter_mode(plan, wt_id):
    del plan, wt_id
    return "WHERE"


def test_required_table_ids_ignores_expected_parse_errors():
    analyzer = QueryForgeRequirementAnalyzer(
        normalize_col_key=_normalize_col_key,
        effective_filter_mode=_effective_filter_mode,
    )
    needed = analyzer.required_table_ids_from_query(
        {"columns": [{"workspaceTableId": "bad"}]},
        _plan(),
    )

    assert needed == {20}


def test_required_table_ids_surfaces_unexpected_parse_errors():
    class _BadInt:
        def __int__(self):
            raise AssertionError("int bug")

    analyzer = QueryForgeRequirementAnalyzer(
        normalize_col_key=_normalize_col_key,
        effective_filter_mode=_effective_filter_mode,
    )

    with pytest.raises(AssertionError, match="int bug"):
        analyzer.required_table_ids_from_query(
            {"columns": [{"workspaceTableId": _BadInt()}]},
            _plan(),
        )


def test_collect_required_column_keys_ignores_expected_parse_errors():
    analyzer = QueryForgeRequirementAnalyzer(
        normalize_col_key=_normalize_col_key,
        effective_filter_mode=_effective_filter_mode,
    )
    refs = analyzer.collect_required_column_keys(
        {"columns": [{"workspaceTableId": "bad", "columnName": "age"}]},
        _plan(),
        required_table_ids={20},
        derived_by_exprid={},
        derived_by_name={},
    )

    assert refs == []


def test_collect_required_column_keys_surfaces_unexpected_parse_errors():
    class _BadInt:
        def __int__(self):
            raise AssertionError("int bug")

    analyzer = QueryForgeRequirementAnalyzer(
        normalize_col_key=_normalize_col_key,
        effective_filter_mode=_effective_filter_mode,
    )

    with pytest.raises(AssertionError, match="int bug"):
        analyzer.collect_required_column_keys(
            {"columns": [{"workspaceTableId": _BadInt(), "columnName": "age"}]},
            _plan(),
            required_table_ids={20},
            derived_by_exprid={},
            derived_by_name={},
        )
