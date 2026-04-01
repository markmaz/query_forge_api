"""Phase 6 — tests for app/services/query_forge/split_ratio_compiler.py."""
from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError

_SPLIT_RATIO_QUERY = {
    "aggs": {
        "enabled": True,
        "groupBy": [],
        "metrics": [
            {
                "fn": "expr",
                "expr": {
                    "kind": "ratio",
                    "numerator": {
                        "fn": "count",
                        "field": {"columnName": "member_id", "workspaceTableId": 1},
                    },
                    "denominator": {
                        "fn": "count",
                        "field": {"columnName": "member_id", "workspaceTableId": 2},
                    },
                },
            }
        ],
    }
}

_STANDARD_AGG_QUERY = {
    "aggs": {
        "enabled": True,
        "groupBy": [{"columnName": "region"}],
        "metrics": [{"fn": "count"}],
    }
}


class TestIsSplitRatioQuery:
    def test_returns_true_for_split_ratio_metric(self):
        from app.services.query_forge.split_ratio_compiler import is_split_ratio_query

        assert is_split_ratio_query(_SPLIT_RATIO_QUERY, primary_id=1) is True

    def test_returns_false_for_standard_agg_query(self):
        from app.services.query_forge.split_ratio_compiler import is_split_ratio_query

        assert is_split_ratio_query(_STANDARD_AGG_QUERY, primary_id=1) is False

    def test_returns_false_when_aggs_not_enabled(self):
        from app.services.query_forge.split_ratio_compiler import is_split_ratio_query

        q = {"aggs": {"enabled": False, "metrics": [{"fn": "expr", "expr": {"kind": "ratio"}}]}}
        assert is_split_ratio_query(q, primary_id=1) is False

    def test_returns_false_for_ratio_with_same_table(self):
        from app.services.query_forge.split_ratio_compiler import is_split_ratio_query

        q = {
            "aggs": {
                "enabled": True,
                "metrics": [
                    {
                        "fn": "expr",
                        "expr": {
                            "kind": "ratio",
                            "numerator": {"fn": "count", "field": {"columnName": "id", "workspaceTableId": 1}},
                            "denominator": {"fn": "count", "field": {"columnName": "id", "workspaceTableId": 1}},
                        },
                    }
                ],
            }
        }
        assert is_split_ratio_query(q, primary_id=1) is False

    def test_multiple_split_ratio_metrics_raises_forge_error(self):
        from app.services.query_forge.split_ratio_compiler import is_split_ratio_query

        q = {
            "aggs": {
                "enabled": True,
                "metrics": [
                    {
                        "fn": "expr",
                        "expr": {
                            "kind": "ratio",
                            "numerator": {"fn": "count", "field": {"columnName": "a", "workspaceTableId": 1}},
                            "denominator": {"fn": "count", "field": {"columnName": "a", "workspaceTableId": 2}},
                        },
                    },
                    {
                        "fn": "expr",
                        "expr": {
                            "kind": "ratio",
                            "numerator": {"fn": "count", "field": {"columnName": "b", "workspaceTableId": 1}},
                            "denominator": {"fn": "count", "field": {"columnName": "b", "workspaceTableId": 3}},
                        },
                    },
                ],
            }
        }
        with pytest.raises(ForgeError):
            is_split_ratio_query(q, primary_id=1)


class TestDetectSplitRatioMetric:
    def test_returns_metric_for_split_ratio_query(self):
        from app.services.query_forge.split_ratio_compiler import detect_split_ratio_metric

        metric = detect_split_ratio_metric(_SPLIT_RATIO_QUERY, primary_id=1)
        assert metric is not None
        assert metric["fn"] == "expr"

    def test_returns_none_for_standard_query(self):
        from app.services.query_forge.split_ratio_compiler import detect_split_ratio_metric

        assert detect_split_ratio_metric(_STANDARD_AGG_QUERY, primary_id=1) is None

    def test_returns_none_for_empty_query(self):
        from app.services.query_forge.split_ratio_compiler import detect_split_ratio_metric

        assert detect_split_ratio_metric({}, primary_id=1) is None


class TestSplitRatioCompilerStateless:
    def test_stateless_no_constructor_args(self):
        from app.services.query_forge.split_ratio_compiler import SplitRatioCompiler

        compiler = SplitRatioCompiler()
        assert compiler is not None
