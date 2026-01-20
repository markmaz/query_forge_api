from __future__ import annotations

import pytest

from app.services.crosswalks.list_writer import COLUMNS_BY_TYPE, ListWriter


class _FakeExecutor:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def submit_statement(self, sql, parameters=None, result_format=None, **_kwargs):
        self.calls.append((sql, parameters, result_format))
        return self._responses.pop(0)


def _schema_rows(cols):
    return [{"col_name": c, "data_type": "string"} for c in cols]


def test_insert_rows_chunks() -> None:
    cols = COLUMNS_BY_TYPE["regions"]
    responses = [
        {"status": {"state": "SUCCEEDED"}},  # create table
        {"status": {"state": "SUCCEEDED"}, "rows": _schema_rows(cols)},  # describe
        {"status": {"state": "SUCCEEDED"}},  # insert 1
        {"status": {"state": "SUCCEEDED"}},  # insert 2
    ]
    executor = _FakeExecutor(responses)
    writer = ListWriter(executor, max_rows_per_chunk=1)

    rows = [
        {c: "v1" for c in cols},
        {c: "v2" for c in cols},
    ]
    inserted = writer.insert_rows("regions", rows)
    assert inserted == 2
    assert len(executor.calls) >= 4


def test_build_insert_values_missing_col() -> None:
    writer = ListWriter(_FakeExecutor([]))
    with pytest.raises(ValueError):
        writer._build_insert_values("tbl", ["a", "b"], [{"a": 1}])
