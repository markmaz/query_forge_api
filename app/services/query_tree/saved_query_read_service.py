from __future__ import annotations

from app.services.query_tree.query_tree_read_model_service import QueryTreeReadModelService, SavedQueryReadResult


class SavedQueryReadService(QueryTreeReadModelService):
    def __init__(self, *, workspace_id: str, user_id: str, is_admin: bool = False, sql=None):
        super().__init__(workspace_id=workspace_id, user_id=user_id, is_admin=is_admin, sql=sql)


__all__ = ["SavedQueryReadResult", "SavedQueryReadService"]
