from __future__ import annotations

from app.services.models.model_write_service import ModelWriteService
from tests._support.fakes import FakeSQLExecutor


def test_upsert_dictionary_empty_rows_returns_zero() -> None:
    svc = ModelWriteService(sql=FakeSQLExecutor())
    result = svc.upsert_dictionary(user_name="user", rows=[])
    assert result == {
        "inserted_tables": 0,
        "inserted_columns": 0,
        "updated_columns": 0,
        "deactivated_columns": 0,
    }


def test_upsert_dictionary_dedupes_and_counts() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses.append([{"id": 1, "name": "patients"}])
    sql.query_mappings_responses.append([{"model_table_id": 1, "column_name": "id"}])

    svc = ModelWriteService(sql=sql)
    result = svc.upsert_dictionary(
        user_name="user",
        rows=[
            {"table_name": "patients", "column_name": "id", "data_type": "INT", "description": "id"},
            {"table_name": "patients", "column_name": "name", "data_type": "STRING", "description": "name"},
            {"table_name": "patients", "column_name": "ID", "data_type": "INT", "description": "dup"},
        ],
    )

    assert result["inserted_columns"] == 1
    assert result["updated_columns"] == 1


def test_upsert_dictionary_full_replace_deactivates() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses.append([{"id": 2, "name": "visits"}])
    sql.query_mappings_responses.append([])
    sql.write_responses = [0, 0, 2]

    svc = ModelWriteService(sql=sql)
    result = svc.upsert_dictionary(
        user_name="user",
        rows=[{"table_name": "visits", "column_name": "visit_id", "data_type": "INT", "description": None}],
        full_replace=True,
    )

    assert result["deactivated_columns"] == 2
