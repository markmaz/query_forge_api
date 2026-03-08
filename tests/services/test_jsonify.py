from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.services.shared.jsonify import serialize_record, serialize_result_rows, serialize_cell


def test_serialize_cell_converts_types() -> None:
    now = datetime(2024, 1, 1)
    today = date(2024, 1, 2)
    uid = UUID("12345678-1234-5678-1234-567812345678")

    assert serialize_cell(now) == "2024-01-01T00:00:00"
    assert serialize_cell(today) == "2024-01-02"
    assert serialize_cell(Decimal("1.5")) == 1.5
    assert serialize_cell(uid) == str(uid)
    assert serialize_cell(b"hi") == "hi"


def test_serialize_record_and_rows() -> None:
    data = {"a": 1, "b": (2, 3)}
    assert serialize_record(data) == {"a": 1, "b": [2, 3]}
    assert serialize_result_rows([data]) == [{"a": 1, "b": [2, 3]}]
