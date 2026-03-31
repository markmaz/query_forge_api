from __future__ import annotations

from app.services.query_tree.query_tree_read_model_service import (
    ForgeFolderRow,
    ForgeQueryRow,
    QueryTreeReadModelService,
)


class SavedQueryTreeService(QueryTreeReadModelService):
    pass


__all__ = ["ForgeFolderRow", "ForgeQueryRow", "SavedQueryTreeService"]
