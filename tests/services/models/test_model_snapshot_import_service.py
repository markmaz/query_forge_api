from __future__ import annotations

import json

import pytest

from app.services.models.model_snapshot_import_service import ModelSnapshotImportService
from tests._support.fakes import FakeDatabricksForgeQueryPort, FakeForgeQueryPort


def test_latest_snapshot_id_missing() -> None:
    sql = FakeDatabricksForgeQueryPort()
    sql.submit_responses.append({"rows": []})
    svc = ModelSnapshotImportService(sql=sql, mysql=FakeForgeQueryPort())

    with pytest.raises(ValueError):
        svc._latest_snapshot_id()


def test_import_snapshot_upserts_and_deactivates() -> None:
    sql = FakeDatabricksForgeQueryPort()
    sql.submit_responses.append(
        {
            "rows": [
                {
                    "snapshot_id": "snap-1",
                    "logical_table_name": "patients",
                    "physical_table_name": "patients_v1",
                },
                {
                    "snapshot_id": "snap-1",
                    "logical_table_name": "visits",
                    "physical_table_name": "visits_v1",
                },
            ]
        }
    )
    sql.submit_responses.append(
        {
            "rows": [
                {
                    "logical_table_name": "patients",
                    "column_name": "id",
                    "data_type": "STRING",
                    "nullable": "true",
                    "ordinal_position": 1,
                    "sample_values_json": ["a", "b"],
                    "sample_stats_json": {"rows": 2},
                    "sample_error": None,
                }
            ]
        }
    )

    mysql = FakeForgeQueryPort()
    mysql.query_mappings_responses.append([{"id": 10, "name": "patients"}, {"id": 20, "name": "visits"}])
    mysql.write_responses = [0, 0, 3]

    svc = ModelSnapshotImportService(sql=sql, mysql=mysql)
    result = svc.import_snapshot(snapshot_id="snap-1", deactivate_missing=True)

    assert result.tables_upserted == 2
    assert result.columns_upserted == 1
    assert result.columns_deactivated == 3

    col_insert = next(call for call in mysql.write_calls if "INSERT INTO model_column" in call.query)
    payload = col_insert.params[0]
    assert json.loads(payload["sample_values_json"]) == ["a", "b"]
