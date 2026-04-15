"""Phase 3 — tests for app/services/query_forge/result_mapper.py."""
from __future__ import annotations


class TestExtractTotal:
    def test_empty_returns_zero(self):
        from app.services.query_forge.result_mapper import extract_total
        assert extract_total([]) == 0

    def test_dict_row_total_key(self):
        from app.services.query_forge.result_mapper import extract_total
        assert extract_total([{"total": 42}]) == 42

    def test_list_row_first_element(self):
        from app.services.query_forge.result_mapper import extract_total
        assert extract_total([[99]]) == 99

    def test_none_total_returns_zero(self):
        from app.services.query_forge.result_mapper import extract_total
        assert extract_total([{"total": None}]) == 0


class TestInferCols:
    def test_empty_rows_returns_empty(self):
        from app.services.query_forge.result_mapper import infer_cols
        assert infer_cols([]) == []

    def test_dict_rows_returns_keys(self):
        from app.services.query_forge.result_mapper import infer_cols
        cols = infer_cols([{"a": 1, "b": 2}])
        assert [c["key"] for c in cols] == ["a", "b"]

    def test_non_dict_rows_returns_empty(self):
        from app.services.query_forge.result_mapper import infer_cols
        assert infer_cols([[1, 2, 3]]) == []


class TestRowsToDicts:
    def test_empty_returns_empty(self):
        from app.services.query_forge.result_mapper import rows_to_dicts
        assert rows_to_dicts([], []) == []

    def test_already_dict_rows_passed_through(self):
        from app.services.query_forge.result_mapper import rows_to_dicts
        rows = [{"a": 1}, {"a": 2}]
        assert rows_to_dicts(rows, [{"key": "a", "label": "a"}]) == rows

    def test_list_rows_mapped_to_dicts(self):
        from app.services.query_forge.result_mapper import rows_to_dicts
        cols = [{"key": "x", "label": "x"}, {"key": "y", "label": "y"}]
        result = rows_to_dicts([[10, 20]], cols)
        assert result == [{"x": 10, "y": 20}]

    def test_short_row_fills_none(self):
        from app.services.query_forge.result_mapper import rows_to_dicts
        cols = [{"key": "a", "label": "a"}, {"key": "b", "label": "b"}]
        result = rows_to_dicts([[1]], cols)
        assert result == [{"a": 1, "b": None}]


class TestColsFromJson:
    def test_plain_columns(self):
        from app.services.query_forge.result_mapper import cols_from_json
        q = {"columns": [{"columnName": "region", "alias": "Region"}]}
        result = cols_from_json(q)
        assert result == [{"key": "Region", "label": "Region"}]

    def test_aggs_enabled_uses_groupby_and_metrics(self):
        from app.services.query_forge.result_mapper import cols_from_json
        q = {
            "columns": [{"columnName": "region", "alias": "Region"}],
            "aggs": {
                "enabled": True,
                "groupBy": [{"columnName": "region"}],
                "metrics": [{"fn": "count", "label": "Count"}],
            },
        }
        result = cols_from_json(q)
        assert result[0] == {"key": "region", "label": "Region"}
        assert result[1] == {"key": "Count", "label": "Count"}

    def test_empty_query_returns_empty(self):
        from app.services.query_forge.result_mapper import cols_from_json
        assert cols_from_json({}) == []
