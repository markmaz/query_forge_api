from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List

import pytest

from app.services.workspace_inventory.catalog_snapshot_import_service import CatalogSnapshotImportService
from tests._support.fakes import FakeDatabricksForgeQueryPort, FakeForgeQueryPort


@dataclass
class _GatewayCall:
    name: str
    payload: Dict[str, Any]


class _GatewayStub:
    def __init__(self) -> None:
        self.calls: List[_GatewayCall] = []

    def sync_table_patch_from_model(self, *, model_table_id: int, updates: Dict[str, Any]) -> int:
        self.calls.append(_GatewayCall(name="sync_table_patch_from_model", payload={"model_table_id": model_table_id, "updates": updates}))
        return 1

    def sync_column_patch_from_model_table(self, *, model_table_id: int, column_name: str, updates: Dict[str, Any]) -> int:
        self.calls.append(
            _GatewayCall(
                name="sync_column_patch_from_model_table",
                payload={"model_table_id": model_table_id, "column_name": column_name, "updates": updates},
            )
        )
        return 1

    def deactivate_workspace_columns_not_in(
        self,
        *,
        model_table_id: int,
        keep_column_names: List[str],
        origin: str | None = None,
        only_not_missing: bool = False,
    ) -> int:
        self.calls.append(
            _GatewayCall(
                name="deactivate_workspace_columns_not_in",
                payload={
                    "model_table_id": model_table_id,
                    "keep_column_names": keep_column_names,
                    "origin": origin,
                    "only_not_missing": only_not_missing,
                },
            )
        )
        return 1


def test_latest_snapshot_id_missing() -> None:
    sql = FakeDatabricksForgeQueryPort()
    sql.submit_responses.append({"rows": []})
    svc = CatalogSnapshotImportService(sql=sql, mysql=FakeForgeQueryPort(), metadata_gateway=_GatewayStub())  # type: ignore[arg-type]

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
    gateway = _GatewayStub()

    svc = CatalogSnapshotImportService(sql=sql, mysql=mysql, metadata_gateway=gateway)  # type: ignore[arg-type]
    result = svc.import_snapshot(snapshot_id="snap-1", deactivate_missing=True)

    assert result.tables_upserted == 2
    assert result.columns_upserted == 1
    assert result.columns_deactivated == 3

    col_insert = next(call for call in mysql.write_calls if "INSERT INTO model_column" in call.query)
    payload = col_insert.params[0]
    assert json.loads(payload["sample_values_json"]) == ["a", "b"]
    assert any(call.name == "sync_table_patch_from_model" for call in gateway.calls)
    assert any(call.name == "sync_column_patch_from_model_table" for call in gateway.calls)
