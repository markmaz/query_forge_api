from __future__ import annotations

from app.services.recon.workspace_recon_read_service import WorkspaceReconReadService
from app.services.recon.workspace_recon_service import ReconQuery


class _DummyRecon:
    def __init__(self) -> None:
        self.calls = []

    def list_recon(self, q: ReconQuery):
        self.calls.append(("list", q))
        return [{"ok": True}]

    def counts_by_status(self, *, workspace_id: str):
        self.calls.append(("counts", workspace_id))
        return {"MATCHED": 1}


def test_recon_read_service_delegates() -> None:
    dummy = _DummyRecon()
    svc = WorkspaceReconReadService(recon=dummy)
    assert svc.list_recon(ReconQuery(workspace_id="ws")) == [{"ok": True}]
    assert svc.counts_by_status(workspace_id="ws")["MATCHED"] == 1
