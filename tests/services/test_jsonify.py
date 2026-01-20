from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.services.shared.jsonify import jsonify_dict, jsonify_rows, jsonify_value


def test_jsonify_value_converts_types() -> None:
    now = datetime(2024, 1, 1)
    today = date(2024, 1, 2)
    uid = UUID("12345678-1234-5678-1234-567812345678")

    assert jsonify_value(now) == "2024-01-01T00:00:00"
    assert jsonify_value(today) == "2024-01-02"
    assert jsonify_value(Decimal("1.5")) == 1.5
    assert jsonify_value(uid) == str(uid)
    assert jsonify_value(b"hi") == "hi"


def test_jsonify_dict_and_rows() -> None:
    data = {"a": 1, "b": (2, 3)}
    assert jsonify_dict(data) == {"a": 1, "b": [2, 3]}
    assert jsonify_rows([data]) == [{"a": 1, "b": [2, 3]}]
