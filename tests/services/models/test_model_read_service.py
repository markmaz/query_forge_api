from __future__ import annotations

from datetime import datetime, timezone

from app.services.models.model_read_service import ModelReadService
from tests._support.fakes import FakeForgeQueryPort


def test_list_tables_with_counts() -> None:
    sql = FakeForgeQueryPort()
    sql.query_responses = [
        [(2,)],
        [(1, "patients", "src_patients", "desc"), (2, "visits", None, None)],
        [(1, 5, 3)],
    ]
    svc = ModelReadService(sql=sql)
    result = svc.list_tables(include_counts=True)

    assert result["total"] == 2
    assert result["rows"][0]["columnCount"] == 5
    assert result["rows"][0]["activeColumnCount"] == 3
    assert result["rows"][1]["columnCount"] == 0


def test_list_table_names() -> None:
    sql = FakeForgeQueryPort()
    sql.query_responses = [[("alpha",), ("beta",)]]
    svc = ModelReadService(sql=sql)
    assert svc.list_table_names() == ["alpha", "beta"]


def test_list_columns_with_table_names() -> None:
    sql = FakeForgeQueryPort()
    sql.query_responses = [
        [
            (
                1,
                10,
                "patients",
                "patient_id",
                "STRING",
                "desc",
                1,
                '["a","b"]',
                '{"sample": 1}',
                datetime(2025, 1, 1, tzinfo=timezone.utc),
                None,
            )
        ],
        [("patients",), ("visits",)],
    ]
    svc = ModelReadService(sql=sql)
    result = svc.list_columns()

    assert result["rows"][0]["columnName"] == "patient_id"
    assert result["rows"][0]["sampleRanAt"].startswith("2025-01-01")
    assert result["tableNames"] == ["patients", "visits"]
