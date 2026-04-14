from __future__ import annotations

from typing import Any, Protocol

from app.services.recon.workspace_recon_service import ReconQuery, WorkspaceReconService


class _ReconReader(Protocol):
    def list_recon(self, q: ReconQuery) -> list[dict[str, Any]]: ...

    def counts_by_status(self, *, workspace_id: str) -> dict[str, int]: ...


class WorkspaceReconReadService:
    def __init__(self, *, recon: _ReconReader | None = None):
        self._reader = recon or WorkspaceReconService()

    def list_recon(self, q: ReconQuery) -> list[dict[str, Any]]:
        query = ReconQuery(
            workspace_id=q.workspace_id,
            status=q.status,
            logical_table_name=q.logical_table_name,
            limit=q.limit,
            offset=q.offset,
        )
        return self._reader.list_recon(query)

    def counts_by_status(self, *, workspace_id: str) -> dict[str, int]:
        return self._reader.counts_by_status(workspace_id=workspace_id)
