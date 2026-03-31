from __future__ import annotations

from app.services.query_tree.query_tree_folder_command_service import (
    QueryTreeFolderCommandService,
    _bind_in,
    _qf_in_params,
    _req,
)


class SavedQueryFolderWriteService(QueryTreeFolderCommandService):
    pass


__all__ = [
    "SavedQueryFolderWriteService",
    "_bind_in",
    "_qf_in_params",
    "_req",
]
