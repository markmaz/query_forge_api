from __future__ import annotations

from typing import Any, Dict, List

from app.services.recon.workspace_recon_service import ReconQuery, WorkspaceReconService


class WorkspaceReconReadService:
    def __init__(self, *, recon: WorkspaceReconService | None = None):
        self._recon = recon or WorkspaceReconService()

    def list_recon(self, q: ReconQuery) -> List[Dict[str, Any]]:
        return self._recon.list_recon(q)

    def counts_by_status(self, *, workspace_id: str) -> Dict[str, int]:
        return self._recon.counts_by_status(workspace_id=workspace_id)