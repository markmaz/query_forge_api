from __future__ import annotations

from app.services.workspace_inventory.workspace_snapshot_staging import stage_snapshot_rows


def test_stage_snapshot_rows_builds_table_and_column_stages() -> None:
    tables, columns, seen_bases = stage_snapshot_rows(
        [
            {
                "qf_catalog_name": "main",
                "qf_schema_name": "asset",
                "qf_table_name": "patient",
                "column_name": "patient_id",
                "qf_ordinal_position": 1,
                "data_type": "STRING",
                "is_nullable": "NO",
            },
            {
                "qf_catalog_name": "main",
                "qf_schema_name": "asset",
                "qf_table_name": "diagnosis_QE",
                "column_name": "code",
                "qf_ordinal_position": 1,
                "data_type": "STRING",
                "is_nullable": "YES",
            },
        ],
        accepted_bases={"patient", "diagnosis"},
    )

    assert len(tables) == 2
    assert len(columns) == 2
    assert "patient" in seen_bases
    diagnosis = next(table for table in tables if table.full_name.endswith("diagnosis_QE"))
    assert diagnosis.qf_table_name == "diagnosis"
    assert diagnosis.is_qe == 1
