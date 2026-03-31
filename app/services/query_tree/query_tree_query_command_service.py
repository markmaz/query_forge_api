from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.query_tree.saved_query_folder_write_service import SavedQueryFolderWriteService


@dataclass(frozen=True)
class _WriteContext:
    workspace_id: str
    user_id: str


class _SavedQueryWriteRepository:
    def __init__(self, *, ctx: _WriteContext, sql: ForgeQueryPort):
        self._ctx = ctx
        self._sql = sql

    def update_query(self, *, query_id: str, title: str, description: Optional[str], sql_json_payload: str, folder_id: Optional[str]) -> int:
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
                  AND workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 0
                """,
                {"qid": query_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id, "fid": folder_id, "title": title, "description": description, "sql_json": sql_json_payload},
            )

    def insert_query(self, *, query_id: str, title: str, description: Optional[str], sql_json_payload: str, folder_id: Optional[str]) -> None:
        with self._sql.transaction() as tx:
            tx.execute_write(
                """
                INSERT INTO saved_query (
                  id, workspace_id, scope, owner_user_id,
                  folder_id, title, description, sql_json,
                  is_deleted, created_at, updated_at
                )
                VALUES (
                  :qid, :ws, 'MINE', :uid,
                  :fid, :title, :description, :sql_json,
                  0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """,
                {"qid": query_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id, "fid": folder_id, "title": title, "description": description, "sql_json": sql_json_payload},
            )

    def assert_folder_owned(self, *, folder_id: str) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM saved_query_folder
            WHERE id = :fid
              AND workspace_id = :ws
              AND scope = 'MINE'
              AND owner_user_id = :uid
              AND is_deleted = 0
            LIMIT 1
            """,
            {"fid": folder_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
        )
        if not rows:
            raise ForgeError("Folder not found", status_code=404)

    def soft_delete_query(self, *, query_id: str) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                """
                UPDATE saved_query
                SET is_deleted = 1,
                    deleted_at = CURRENT_TIMESTAMP,
                    deleted_by_user_id = :uid,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :qid
                  AND workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 0
                """,
                {"qid": query_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
            )

    def fetch_query_restore_state(self, *, query_id: str) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              q.folder_id,
              q.is_deleted AS query_deleted,
              f.is_deleted AS folder_deleted
            FROM saved_query q
            LEFT JOIN saved_query_folder f ON f.id = q.folder_id
            WHERE q.id = :qid
              AND q.workspace_id = :ws
              AND q.scope = 'MINE'
              AND q.owner_user_id = :uid
            LIMIT 1
            """,
            {"qid": query_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
        )
        return dict(rows[0]) if rows else None

    def restore_query(self, *, query_id: str) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                """
                UPDATE saved_query
                SET is_deleted = 0,
                    deleted_at = NULL,
                    deleted_by_user_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :qid
                  AND workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 1
                """,
                {"qid": query_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
            )

    def purge_query(self, *, query_id: str) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                """
                DELETE FROM saved_query
                WHERE id = :qid
                  AND workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 1
                """,
                {"qid": query_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
            )

    def move_query(self, *, query_id: str, folder_id: Optional[str]) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                """
                UPDATE saved_query
                SET folder_id = :fid,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :qid
                  AND workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 0
                """,
                {"qid": query_id, "fid": folder_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
            )


class QueryTreeQueryCommandService:
    def __init__(self, *, workspace_id: str, user_id: str, sql: Optional[ForgeQueryPort] = None):
        if not workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)
        if not user_id:
            raise ForgeError("user_id is required", status_code=400)
        self._ws = workspace_id
        self._uid = user_id
        self._sql = sql or ForgeMetaSQL()
        self._ctx = _WriteContext(workspace_id=workspace_id, user_id=user_id)
        self._repo = _SavedQueryWriteRepository(ctx=self._ctx, sql=self._sql)

    def save_query(self, *, title: str, sql_json: Dict[str, Any], description: Optional[str] = None, folder_id: Optional[str] = None, query_id: Optional[str] = None) -> Dict[str, Any]:
        clean_title = (title or "").strip()
        if not clean_title:
            raise ForgeError("Title is required", status_code=400)
        if not isinstance(sql_json, dict):
            raise ForgeError("sql_json must be an object", status_code=400)
        clean_folder_id = (str(folder_id).strip() or None) if folder_id is not None else None
        if clean_folder_id:
            self._assert_folder_owner(clean_folder_id)
        clean_query_id = (str(query_id).strip() or None) if query_id else None
        is_update = bool(clean_query_id)
        if not clean_query_id:
            clean_query_id = str(uuid.uuid4())
        try:
            sql_json_payload = json.dumps(sql_json)
        except (TypeError, ValueError) as exc:
            raise ForgeError("sql_json must be JSON-serializable", status_code=400) from exc

        if is_update:
            updated = self._repo.update_query(query_id=clean_query_id, title=clean_title, description=(description or None), sql_json_payload=sql_json_payload, folder_id=clean_folder_id)
            if (updated or 0) == 0:
                raise ForgeError("Saved query not found", status_code=404)
        else:
            self._repo.insert_query(query_id=clean_query_id, title=clean_title, description=(description or None), sql_json_payload=sql_json_payload, folder_id=clean_folder_id)

        return {"queryId": clean_query_id, "workspaceId": self._ws, "scope": "MINE", "ownerUserId": self._uid, "folderId": clean_folder_id, "name": clean_title, "description": (description or None), "created": not is_update}

    def delete_query(self, *, query_id: str) -> Dict[str, Any]:
        query_id = str(query_id or "").strip()
        if not query_id:
            raise ForgeError("query_id is required", status_code=400)
        deleted = self._repo.soft_delete_query(query_id=query_id)
        if (deleted or 0) == 0:
            raise ForgeError("Saved query not found", status_code=404)
        return {"queryId": query_id, "deleted": True}

    def restore_query(self, *, query_id: str) -> Dict[str, Any]:
        query_id = str(query_id or "").strip()
        if not query_id:
            raise ForgeError("query_id is required", status_code=400)
        state = self._repo.fetch_query_restore_state(query_id=query_id)
        if not state:
            raise ForgeError("Saved query not found", status_code=404)
        folder_id = state.get("folder_id")
        query_deleted = bool(state.get("query_deleted")) if state.get("query_deleted") is not None else False
        folder_deleted = bool(state.get("folder_deleted")) if state.get("folder_deleted") is not None else False
        if not query_deleted:
            return {"queryId": query_id, "restored": True, "folderId": str(folder_id) if folder_id else None, "alreadyRestored": True}
        if folder_id and folder_deleted:
            SavedQueryFolderWriteService(workspace_id=self._ws, user_id=self._uid, sql=self._sql).restore_folder(folder_id=str(folder_id))
        restored = self._repo.restore_query(query_id=query_id)
        if (restored or 0) == 0:
            raise ForgeError("Saved query not found in trash", status_code=404)
        return {"queryId": query_id, "restored": True, "folderId": str(folder_id) if folder_id else None}

    def purge_query(self, *, query_id: str) -> Dict[str, Any]:
        query_id = str(query_id or "").strip()
        if not query_id:
            raise ForgeError("query_id is required", status_code=400)
        purged = self._repo.purge_query(query_id=query_id)
        if (purged or 0) == 0:
            raise ForgeError("Saved query not found", status_code=404)
        return {"queryId": query_id, "purged": True}

    def move_query(self, *, query_id: str, folder_id: str | None) -> Dict[str, Any]:
        query_id = str(query_id or "").strip()
        if not query_id:
            raise ForgeError("query_id is required", status_code=400)
        if folder_id is not None:
            folder_id = str(folder_id).strip() or None
            if folder_id == f"user:{self._uid}":
                folder_id = None
        if folder_id:
            self._assert_folder_owner(folder_id)
        moved = self._repo.move_query(query_id=query_id, folder_id=folder_id)
        if (moved or 0) == 0:
            raise ForgeError("Saved query not found", status_code=404)
        return {"queryId": query_id, "folderId": folder_id}

    def _assert_folder_owner(self, folder_id: str) -> None:
        self._repo.assert_folder_owned(folder_id=folder_id)
