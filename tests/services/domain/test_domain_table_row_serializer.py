from __future__ import annotations

from app.services.domain.table_read.domain_table_row_serializer import serialize_workspace_table_rows


def test_serialize_workspace_table_rows_sets_model_fields() -> None:
    out = serialize_workspace_table_rows(
        [
            {
                "workspace_table_id": 7,
                "table_label": "dim_patient",
                "table_name": "dim_patient",
            }
        ]
    )

    assert out[0]["model_table_id"] == 7
    assert out[0]["model_table_name"] == "dim_patient"
