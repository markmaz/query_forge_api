from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.exceptions.forge_error import ForgeError
from app.services.query_tree.saved_query_folder_write_service import SavedQueryFolderWriteService


@dataclass(frozen=True)
class _QueryFolderContext:
    workspace_id: str
    user_id: str


class QueryFolderService:
    """Compatibility facade around SavedQueryFolderWriteService with legacy field names."""

    def __init__(self, *, workspace_id: str, user_id: str):
        if not workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)
        if not user_id:
            raise ForgeError("user_id is required", status_code=400)

        self._ctx = _QueryFolderContext(workspace_id=workspace_id, user_id=user_id)
        self._writer = SavedQueryFolderWriteService(workspace_id=workspace_id, user_id=user_id)

    def create_folder(self, *, name: str, parent_folder_id: Optional[str] = None, sort_order: int = 0) -> Dict[str, Any]:
        created = self._writer.create_folder(name=name, parent_folder_id=parent_folder_id, sort_index=sort_order)
        return {
            "folderId": created["folderId"],
            "name": created["name"],
            "parentFolderId": created.get("parentId"),
            "sortOrder": created.get("sortIndex"),
        }

    def rename_folder(self, *, folder_id: str, name: str) -> Dict[str, Any]:
        return self._writer.rename_folder(folder_id=_req_uuidish(folder_id, "folder_id"), name=name)

    def move_folder(
        self,
        *,
        folder_id: str,
        new_parent_folder_id: Optional[str],
        new_sort_order: Optional[int] = None,
    ) -> Dict[str, Any]:
        moved = self._writer.move_folder(
            folder_id=_req_uuidish(folder_id, "folder_id"),
            new_parent_folder_id=(
                _req_uuidish(new_parent_folder_id, "new_parent_folder_id") if new_parent_folder_id else None
            ),
            new_sort_index=new_sort_order,
        )
        return {
            "folderId": moved["folderId"],
            "parentFolderId": moved.get("parentId"),
            "sortOrder": moved.get("sortIndex"),
        }

    def delete_folder(self, *, folder_id: str) -> Dict[str, Any]:
        return self._writer.delete_folder(folder_id=_req_uuidish(folder_id, "folder_id"))


def _req_uuidish(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ForgeError(f"{field} is required", status_code=400)
    if len(text) < 8:
        raise ForgeError(f"Invalid {field}", status_code=400)
    return text
