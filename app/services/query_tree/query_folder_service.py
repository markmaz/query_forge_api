from __future__ import annotations

from typing import Any, Dict, Optional

from app.exceptions.service_error import ServiceError
from app.services.query_tree.saved_query_folder_write_service import SavedQueryFolderWriteService


class QueryFolderService:
    """
    Compatibility wrapper that delegates folder CRUD/move calls to SavedQueryFolderWriteService.
    Uses scope='MINE' as defined in the current schema.
    """

    def __init__(self, *, workspace_id: str, user_id: str):
        if not workspace_id:
            raise ServiceError("workspace_id is required", status_code=400)
        if not user_id:
            raise ServiceError("user_id is required", status_code=400)
        self._delegate = SavedQueryFolderWriteService(workspace_id=workspace_id, user_id=user_id)

    def create_folder(self, *, name: str, parent_folder_id: Optional[str] = None, sort_order: int = 0) -> Dict[str, Any]:
        res = self._delegate.create_folder(name=name, parent_folder_id=parent_folder_id, sort_index=sort_order)
        return {
            "folderId": res["folderId"],
            "name": res["name"],
            "parentFolderId": res.get("parentId"),
            "sortOrder": res.get("sortIndex"),
        }

    def rename_folder(self, *, folder_id: str, name: str) -> Dict[str, Any]:
        return self._delegate.rename_folder(folder_id=_req_uuidish(folder_id, "folder_id"), name=name)

    def move_folder(
        self,
        *,
        folder_id: str,
        new_parent_folder_id: Optional[str],
        new_sort_order: Optional[int] = None,
    ) -> Dict[str, Any]:
        res = self._delegate.move_folder(
            folder_id=_req_uuidish(folder_id, "folder_id"),
            new_parent_folder_id=(_req_uuidish(new_parent_folder_id, "new_parent_folder_id") if new_parent_folder_id else None),
            new_sort_index=new_sort_order,
        )
        return {"folderId": res["folderId"], "parentFolderId": res.get("parentId"), "sortOrder": res.get("sortIndex")}

    def delete_folder(self, *, folder_id: str) -> Dict[str, Any]:
        return self._delegate.delete_folder(folder_id=_req_uuidish(folder_id, "folder_id"))


def _req_uuidish(value: Any, field: str) -> str:
    v = str(value or "").strip()
    if not v:
        raise ServiceError(f"{field} is required", status_code=400)
    if len(v) < 8:
        raise ServiceError(f"Invalid {field}", status_code=400)
    return v
