from __future__ import annotations

from app.services.embedding.embedding_index_service import (
    build_workspace_column_payload,
    build_workspace_column_point_id,
)


def test_build_workspace_column_point_id() -> None:
    point_id = build_workspace_column_point_id("ws1", 42)
    assert isinstance(point_id, str)
    assert len(point_id) == 36


def test_build_workspace_column_payload_schema() -> None:
    row = {
        "workspace_id": "ws1",
        "workspace_table_id": 10,
        "workspace_column_id": 55,
        "model_table_id": 3,
        "model_column_id": 9,
        "model_table_name": "students",
        "table_name": "students",
        "full_name": "main.asset.students",
        "column_name": "student_id",
        "model_data_type": "INT",
        "workspace_data_type": "INT",
        "column_description": "Student identifier",
        "model_is_active": 1,
    }

    payload = build_workspace_column_payload(row)
    assert payload["type"] == "column"
    assert payload["external_id"] == "col:ws1:55"
    assert payload["workspace_id"] == "ws1"
    assert payload["workspace_table_id"] == 10
    assert payload["workspace_column_id"] == 55
    assert payload["model_table_id"] == 3
    assert payload["model_column_id"] == 9
    assert payload["column_name"] == "student_id"
    assert payload["data_type"] == "INT"
    assert payload["is_active"] is True
