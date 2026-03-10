from __future__ import annotations

from app.services.workspace_inventory.unmapped_workspace_tables_read_service import (
    UnmappedWorkspaceTablesReadService,
)
from tests._support.fakes import FakeForgeQueryPort


def test_list_unmapped_tables() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [
        [{"total": 2}],
        [
            {
                "id": 1,
                "catalog_name": "main",
                "schema_name": "asset",
                "table_name": "patients",
                "full_name": "main.asset.patients",
                "qf_variant_code": None,
                "is_qe": 0,
                "qf_exists_in_dbx": 1,
                "qf_last_seen_at": "now",
            }
        ],
    ]
    svc = UnmappedWorkspaceTablesReadService(sql=fake)
    result = svc.list_unmapped_tables(workspace_id="ws", schema_name="asset", q="pat")

    assert result["total"] == 2
    assert result["rows"][0]["table_name"] == "patients"
