from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.query_tree.saved_query_read_service import SavedQueryReadService


@dataclass(frozen=True)
class _LibraryContext:
    workspace_id: str
    user_id: str


class _SavedQueryLibraryRepository:
    def __init__(self, *, ctx: _LibraryContext, sql: ForgeQueryPort):
        self._ctx = ctx
        self._sql = sql

    def folder_exists(self, *, folder_id: str) -> bool:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM saved_query_folder
            WHERE id = :fid
              AND scope = 'LIBRARY'
              AND workspace_id IS NULL
              AND owner_user_id IS NULL
              AND is_deleted = 0
            LIMIT 1
            """,
            {"fid": folder_id},
        )
        return bool(rows)

    def query_exists(self, *, query_id: str) -> bool:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM saved_query
            WHERE id = :qid
              AND scope = 'LIBRARY'
              AND workspace_id IS NULL
              AND owner_user_id IS NULL
              AND is_deleted = 0
            LIMIT 1
            """,
            {"qid": query_id},
        )
        return bool(rows)

    def insert_folder(self, *, folder_id: str, name: str, parent_id: Optional[str], sort_index: int) -> None:
        with self._sql.transaction() as tx:
            tx.execute_write(
                """
                INSERT INTO saved_query_folder (
                  id, scope, workspace_id, owner_user_id,
                  parent_id, name, sort_index,
                  is_deleted, created_at, updated_at
                )
                VALUES (
                  :id, 'LIBRARY', NULL, NULL,
                  :parent_id, :name, :sort_index,
                  0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """,
                {
                    "id": folder_id,
                    "parent_id": parent_id,
                    "name": name,
                    "sort_index": sort_index,
                },
            )

    def rename_folder(self, *, folder_id: str, name: str) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                """
                UPDATE saved_query_folder
                SET name = :name,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :fid
                  AND scope = 'LIBRARY'
                  AND workspace_id IS NULL
                  AND owner_user_id IS NULL
                  AND is_deleted = 0
                """,
                {"fid": folder_id, "name": name},
            )

    def move_folder(self, *, folder_id: str, parent_id: Optional[str], sort_index: Optional[int]) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                """
                UPDATE saved_query_folder
                SET parent_id = :parent_id,
                    sort_index = COALESCE(:sort_index, sort_index),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :fid
                  AND scope = 'LIBRARY'
                  AND workspace_id IS NULL
                  AND owner_user_id IS NULL
                  AND is_deleted = 0
                """,
                {"fid": folder_id, "parent_id": parent_id, "sort_index": sort_index},
            )

    def delete_folder(self, *, folder_id: str) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                """
                DELETE FROM saved_query_folder
                WHERE id = :fid
                  AND scope = 'LIBRARY'
                  AND workspace_id IS NULL
                  AND owner_user_id IS NULL
                  AND is_deleted = 0
                """,
                {"fid": folder_id},
            )

    def child_folder_count(self, *, folder_id: str) -> int:
        rows = self._sql.execute_query_mappings(
            """
            SELECT COUNT(1) AS n
            FROM saved_query_folder
            WHERE parent_id = :fid
              AND scope = 'LIBRARY'
              AND workspace_id IS NULL
              AND owner_user_id IS NULL
              AND is_deleted = 0
            """,
            {"fid": folder_id},
        )
        return int((rows[0] if rows else {}).get("n") or 0)

    def child_query_count(self, *, folder_id: str) -> int:
        rows = self._sql.execute_query_mappings(
            """
            SELECT COUNT(1) AS n
            FROM saved_query
            WHERE folder_id = :fid
              AND scope = 'LIBRARY'
              AND workspace_id IS NULL
              AND owner_user_id IS NULL
              AND is_deleted = 0
            """,
            {"fid": folder_id},
        )
        return int((rows[0] if rows else {}).get("n") or 0)

    def parent_id_for_folder(self, *, folder_id: str) -> Optional[str]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT parent_id
            FROM saved_query_folder
            WHERE id = :fid
              AND scope = 'LIBRARY'
              AND workspace_id IS NULL
              AND owner_user_id IS NULL
            LIMIT 1
            """,
            {"fid": folder_id},
        )
        row = rows[0] if rows else None
        return str(row["parent_id"]) if row and row.get("parent_id") else None

    def insert_query(
        self,
        *,
        query_id: str,
        title: str,
        description: Optional[str],
        sql_json_payload: str,
        folder_id: Optional[str],
    ) -> None:
        with self._sql.transaction() as tx:
            tx.execute_write(
                """
                INSERT INTO saved_query (
                  id, workspace_id, scope, owner_user_id,
                  folder_id, title, description, sql_json,
                  is_deleted, created_at, updated_at
                )
                VALUES (
                  :qid, NULL, 'LIBRARY', NULL,
                  :fid, :title, :description, :sql_json,
                  0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """,
                {
                    "qid": query_id,
                    "fid": folder_id,
                    "title": title,
                    "description": description,
                    "sql_json": sql_json_payload,
                },
            )

    def update_query(
        self,
        *,
        query_id: str,
        title: str,
        description: Optional[str],
        sql_json_payload: str,
        folder_id: Optional[str],
    ) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                """
                UPDATE saved_query
                SET title = :title,
                    description = :description,
                    sql_json = :sql_json,
                    folder_id = :fid,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :qid
                  AND scope = 'LIBRARY'
                  AND workspace_id IS NULL
                  AND owner_user_id IS NULL
                  AND is_deleted = 0
                """,
                {
                    "qid": query_id,
                    "fid": folder_id,
                    "title": title,
                    "description": description,
                    "sql_json": sql_json_payload,
                },
            )

    def move_query(self, *, query_id: str, folder_id: Optional[str]) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                """
                UPDATE saved_query
                SET folder_id = :fid,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :qid
                  AND scope = 'LIBRARY'
                  AND workspace_id IS NULL
                  AND owner_user_id IS NULL
                  AND is_deleted = 0
                """,
                {"qid": query_id, "fid": folder_id},
            )

    def delete_query(self, *, query_id: str) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                """
                DELETE FROM saved_query
                WHERE id = :qid
                  AND scope = 'LIBRARY'
                  AND workspace_id IS NULL
                  AND owner_user_id IS NULL
                  AND is_deleted = 0
                """,
                {"qid": query_id},
            )


class SavedQueryLibraryService:
    def __init__(
        self,
        *,
        workspace_id: str,
        user_id: str,
        allow_publish: bool = False,
        allow_manage: bool = False,
        allow_delete_query: bool = False,
        sql: Optional[ForgeQueryPort] = None,
    ):
        if not workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)
        if not user_id:
            raise ForgeError("user_id is required", status_code=400)

        self._ws = workspace_id
        self._uid = user_id
        self._allow_publish = bool(allow_publish)
        self._allow_manage = bool(allow_manage)
        self._allow_delete_query = bool(allow_delete_query or allow_manage)
        self._sql = sql or ForgeMetaSQL()
        self._ctx = _LibraryContext(workspace_id=workspace_id, user_id=user_id)
        self._repo = _SavedQueryLibraryRepository(ctx=self._ctx, sql=self._sql)

    def folder_exists(self, folder_id: str) -> bool:
        folder_id = str(folder_id or "").strip()
        return bool(folder_id) and self._repo.folder_exists(folder_id=folder_id)

    def query_exists(self, query_id: str) -> bool:
        query_id = str(query_id or "").strip()
        return bool(query_id) and self._repo.query_exists(query_id=query_id)

    def create_folder(self, *, name: str, parent_folder_id: Optional[str] = None, sort_index: int = 0) -> Dict[str, Any]:
        self._assert_manage_allowed()
        clean_name = (name or "").strip()
        if not clean_name:
            raise ForgeError("Folder name is required", status_code=400)
        if len(clean_name) > 255:
            raise ForgeError("Folder name is too long", status_code=400)

        parent_id = (str(parent_folder_id).strip() or None) if parent_folder_id is not None else None
        if parent_id and not self._repo.folder_exists(folder_id=parent_id):
            raise ForgeError("Folder not found", status_code=404)

        folder_id = str(uuid.uuid4())
        self._repo.insert_folder(
            folder_id=folder_id,
            name=clean_name,
            parent_id=parent_id,
            sort_index=int(sort_index or 0),
        )
        return {"folderId": folder_id, "name": clean_name, "parentId": parent_id, "sortIndex": int(sort_index or 0)}

    def rename_folder(self, *, folder_id: str, name: str) -> Dict[str, Any]:
        self._assert_manage_allowed()
        folder_id = _req(folder_id, "folder_id")
        clean_name = (name or "").strip()
        if not clean_name:
            raise ForgeError("Folder name is required", status_code=400)
        if len(clean_name) > 255:
            raise ForgeError("Folder name is too long", status_code=400)
        self._assert_library_folder_exists(folder_id)
        updated = self._repo.rename_folder(folder_id=folder_id, name=clean_name)
        if (updated or 0) == 0:
            raise ForgeError("Folder not found", status_code=404)
        return {"folderId": folder_id, "name": clean_name}

    def move_folder(self, *, folder_id: str, parent_id: Optional[str], sort_index: Optional[int] = None) -> Dict[str, Any]:
        self._assert_manage_allowed()
        folder_id = _req(folder_id, "folder_id")
        normalized_parent = (str(parent_id).strip() or None) if parent_id is not None else None
        self._assert_library_folder_exists(folder_id)
        if normalized_parent:
            self._assert_library_folder_exists(normalized_parent)
            if self._is_descendant(descendant_id=normalized_parent, ancestor_id=folder_id):
                raise ForgeError("Invalid move (cannot move folder into itself)", status_code=400)
        updated = self._repo.move_folder(folder_id=folder_id, parent_id=normalized_parent, sort_index=sort_index)
        if (updated or 0) == 0:
            raise ForgeError("Folder not found", status_code=404)
        return {"folderId": folder_id, "parentId": normalized_parent, "sortIndex": sort_index}

    def delete_folder(self, *, folder_id: str) -> Dict[str, Any]:
        self._assert_manage_allowed()
        folder_id = _req(folder_id, "folder_id")
        self._assert_library_folder_exists(folder_id)
        if self._repo.child_folder_count(folder_id=folder_id) > 0 or self._repo.child_query_count(folder_id=folder_id) > 0:
            raise ForgeError("Folder is not empty", status_code=400)
        deleted = self._repo.delete_folder(folder_id=folder_id)
        if (deleted or 0) == 0:
            raise ForgeError("Folder not found", status_code=404)
        return {"folderId": folder_id, "deleted": True}

    def save_query_to_library(self, *, source_query_id: str) -> Dict[str, Any]:
        self._assert_publish_allowed()
        payload = SavedQueryReadService(
            workspace_id=self._ws,
            user_id=self._uid,
            is_admin=self._allow_manage,
            sql=self._sql,
        ).get_query(_req(source_query_id, "source_query_id"))

        try:
            sql_json_payload = json.dumps(payload["sqlJson"])
        except (TypeError, ValueError) as exc:
            raise ForgeError("sql_json must be JSON-serializable", status_code=400) from exc

        new_query_id = str(uuid.uuid4())
        self._repo.insert_query(
            query_id=new_query_id,
            title=str(payload.get("name") or "Untitled"),
            description=payload.get("description"),
            sql_json_payload=sql_json_payload,
            folder_id=None,
        )
        return {
            "queryId": new_query_id,
            "sourceQueryId": source_query_id,
            "scope": "LIBRARY",
            "folderId": None,
            "name": str(payload.get("name") or "Untitled"),
            "created": True,
        }

    def update_query(
        self,
        *,
        query_id: str,
        title: str,
        sql_json: Dict[str, Any],
        description: Optional[str] = None,
        folder_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._assert_manage_allowed()
        clean_query_id = _req(query_id, "query_id")
        clean_title = (title or "").strip()
        if not clean_title:
            raise ForgeError("Title is required", status_code=400)
        if not isinstance(sql_json, dict):
            raise ForgeError("sql_json must be an object", status_code=400)
        normalized_folder_id = (str(folder_id).strip() or None) if folder_id is not None else None
        if normalized_folder_id:
            self._assert_library_folder_exists(normalized_folder_id)
        try:
            sql_json_payload = json.dumps(sql_json)
        except (TypeError, ValueError) as exc:
            raise ForgeError("sql_json must be JSON-serializable", status_code=400) from exc

        updated = self._repo.update_query(
            query_id=clean_query_id,
            title=clean_title,
            description=description or None,
            sql_json_payload=sql_json_payload,
            folder_id=normalized_folder_id,
        )
        if (updated or 0) == 0:
            raise ForgeError("Saved query not found", status_code=404)
        return {
            "queryId": clean_query_id,
            "scope": "LIBRARY",
            "folderId": normalized_folder_id,
            "name": clean_title,
            "description": description or None,
            "created": False,
        }

    def move_query(self, *, query_id: str, folder_id: Optional[str]) -> Dict[str, Any]:
        self._assert_manage_allowed()
        clean_query_id = _req(query_id, "query_id")
        normalized_folder_id = (str(folder_id).strip() or None) if folder_id is not None else None
        if normalized_folder_id:
            self._assert_library_folder_exists(normalized_folder_id)
        moved = self._repo.move_query(query_id=clean_query_id, folder_id=normalized_folder_id)
        if (moved or 0) == 0:
            raise ForgeError("Saved query not found", status_code=404)
        return {"queryId": clean_query_id, "folderId": normalized_folder_id}

    def delete_query(self, *, query_id: str) -> Dict[str, Any]:
        self._assert_library_query_delete_allowed()
        clean_query_id = _req(query_id, "query_id")
        deleted = self._repo.delete_query(query_id=clean_query_id)
        if (deleted or 0) == 0:
            raise ForgeError("Saved query not found", status_code=404)
        return {"queryId": clean_query_id, "deleted": True, "scope": "LIBRARY"}

    def _assert_publish_allowed(self) -> None:
        if not self._allow_publish:
            raise ForgeError("Library publish access required", status_code=403)

    def _assert_manage_allowed(self) -> None:
        if not self._allow_manage:
            raise ForgeError("Workspace admin access required", status_code=403)

    def _assert_library_query_delete_allowed(self) -> None:
        if not self._allow_delete_query:
            raise ForgeError("Library delete access required", status_code=403)

    def _assert_library_folder_exists(self, folder_id: str) -> None:
        if not self._repo.folder_exists(folder_id=folder_id):
            raise ForgeError("Folder not found", status_code=404)

    def _is_descendant(self, *, descendant_id: str, ancestor_id: str) -> bool:
        current = descendant_id
        for _ in range(128):
            if not current:
                return False
            if current == ancestor_id:
                return True
            current = self._repo.parent_id_for_folder(folder_id=current)
            if current is None:
                return False
        raise ForgeError("Folder hierarchy too deep", status_code=400)


def _req(v: Any, field: str) -> str:
    value = str(v or "").strip()
    if not value:
        raise ForgeError(f"{field} is required", status_code=400)
    return value
