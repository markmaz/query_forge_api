from __future__ import annotations

from app.services.recon.workspace_recon_service import ReconQuery, WorkspaceReconService
from tests._support.fakes import FakeForgeQueryPort


def test_list_recon() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses.append(
        [
            {
                "logical_table_name": "patients",
                "column_name": "id",
                "status": "MATCHED",
                "dict_column_id": 1,
                "dbx_column_id": 2,
                "dict_description": "desc",
                "dbx_data_type": "STRING",
                "dict_data_type": "STRING",
            }
        ]
    )
    svc = WorkspaceReconService(sql=fake)
    rows = svc.list_recon(ReconQuery(workspace_id="ws"))
    assert rows[0]["status"] == "MATCHED"


def test_counts_by_status() -> None:
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses.append([{"status": "MATCHED", "cnt": 3}])
    svc = WorkspaceReconService(sql=fake)
    counts = svc.counts_by_status(workspace_id="ws")
    assert counts["MATCHED"] == 3
