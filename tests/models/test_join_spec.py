from __future__ import annotations

import pytest

from app.models.join_spec import JoinSpecV1


def test_join_spec_valid() -> None:
    spec = JoinSpecV1(
        on=[
            {
                "left": {"col": "patient_id"},
                "right": {"col": "patient_id"},
                "op": "=",
            }
        ]
    )
    assert spec.on[0].left.col == "patient_id"


def test_join_spec_rejects_invalid_col() -> None:
    with pytest.raises(Exception):
        JoinSpecV1(on=[{"left": {"col": "bad name"}, "right": {"col": "ok"}}])


def test_join_spec_rejects_duplicate_clauses() -> None:
    with pytest.raises(Exception):
        JoinSpecV1(
            on=[
                {"left": {"col": "a"}, "right": {"col": "b"}, "op": "="},
                {"left": {"col": "a"}, "right": {"col": "b"}, "op": "="},
            ]
        )

