from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.exc import IntegrityError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort


@dataclass(frozen=True)
class _FolderContext:
    workspace_id: str
    user_id: str


class _FolderRepository:
    def __init__(self, *, ctx: _FolderContext, sql: ForgeQueryPort):
        self._ctx = ctx
        self._sql = sql

    def folder_exists(self, *, folder_id: str, allow_deleted: bool) -> bool:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM saved_query_folder
            WHERE id = :fid
              AND workspace_id = :ws
              AND scope = 'MINE'
              AND owner_user_id = :uid
              AND (:allow_deleted = 1 OR is_deleted = 0)
            LIMIT 1
            """,
            {
                "fid": folder_id,
                "ws": self._ctx.workspace_id,
                "uid": self._ctx.user_id,
                "allow_deleted": 1 if allow_deleted else 0,
            },
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
                  :id, 'MINE', :ws, :uid,
                  :parent_id, :name, :sort_index,
                  0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """,
                {
                    "id": folder_id,
                    "ws": self._ctx.workspace_id,
                    "uid": self._ctx.user_id,
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
                SET name = :name, updated_at = CURRENT_TIMESTAMP
                WHERE id = :fid
                  AND workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 0
                """,
                {"fid": folder_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id, "name": name},
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
                  AND workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 0
                """,
                {
                    "fid": folder_id,
                    "ws": self._ctx.workspace_id,
                    "uid": self._ctx.user_id,
                    "parent_id": parent_id,
                    "sort_index": sort_index,
                },
            )

    def soft_delete_folder(self, *, folder_id: str) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                """
                UPDATE saved_query_folder
                SET is_deleted = 1,
                    deleted_at = CURRENT_TIMESTAMP,
                    deleted_by_user_id = :uid,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :fid
                  AND workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 0
                """,
                {"fid": folder_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
            )

    def child_folder_count(self, *, folder_id: str) -> int:
        rows = self._sql.execute_query_mappings(
            """
            SELECT COUNT(1) AS n
            FROM saved_query_folder
            WHERE parent_id = :fid
              AND workspace_id = :ws
              AND scope = 'MINE'
              AND owner_user_id = :uid
              AND is_deleted = 0
            """,
            {"fid": folder_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
        )
        row = rows[0] if rows else None
        return int((row or {}).get("n") or 0)

    def child_query_count(self, *, folder_id: str) -> int:
        rows = self._sql.execute_query_mappings(
            """
            SELECT COUNT(1) AS n
            FROM saved_query
            WHERE folder_id = :fid
              AND workspace_id = :ws
              AND scope = 'MINE'
              AND owner_user_id = :uid
              AND is_deleted = 0
            """,
            {"fid": folder_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
        )
        row = rows[0] if rows else None
        return int((row or {}).get("n") or 0)

    def parent_id_for_folder(self, *, folder_id: str) -> Optional[str]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT parent_id
            FROM saved_query_folder
            WHERE id = :fid
              AND workspace_id = :ws
              AND scope = 'MINE'
              AND owner_user_id = :uid
            LIMIT 1
            """,
            {"fid": folder_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
        )
        row = rows[0] if rows else None
        return str(row["parent_id"]) if row and row.get("parent_id") else None

    def fetch_all_folders(self, *, qf_include_deleted: bool) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, parent_id, is_deleted
            FROM saved_query_folder
            WHERE workspace_id = :ws
              AND scope = 'MINE'
              AND owner_user_id = :uid
              AND (:qf_include_deleted = 1 OR is_deleted = 0)
            """,
            {
                "ws": self._ctx.workspace_id,
                "uid": self._ctx.user_id,
                "qf_include_deleted": 1 if qf_include_deleted else 0,
            },
        )
        return [dict(row) for row in rows]

    def fetch_queries_in_folders(self, *, folder_ids: List[str], qf_include_deleted: bool) -> List[str]:
        if not folder_ids:
            return []
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT id
            FROM saved_query
            WHERE workspace_id = :ws
              AND scope = 'MINE'
              AND owner_user_id = :uid
              AND (:qf_include_deleted = 1 OR is_deleted = 0)
              AND folder_id IN ({_qf_in_params('f', len(folder_ids))})
            """,
            {
                "ws": self._ctx.workspace_id,
                "uid": self._ctx.user_id,
                "qf_include_deleted": 1 if qf_include_deleted else 0,
                **_bind_in("f", folder_ids),
            },
        )
        return [str(row["id"]) for row in rows]

    def restore_folder_ids(self, *, folder_ids: List[str]) -> None:
        if not folder_ids:
            return
        with self._sql.transaction() as tx:
            tx.execute_write(
                f"""
                UPDATE saved_query_folder
                SET is_deleted = 0,
                    deleted_at = NULL,
                    deleted_by_user_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 1
                  AND id IN ({_qf_in_params('f', len(folder_ids))})
                """,
                {
                    "ws": self._ctx.workspace_id,
                    "uid": self._ctx.user_id,
                    **_bind_in("f", folder_ids),
                },
            )

    def restore_query_ids(self, *, query_ids: List[str]) -> None:
        if not query_ids:
            return
        with self._sql.transaction() as tx:
            tx.execute_write(
                f"""
                UPDATE saved_query
                SET is_deleted = 0,
                    deleted_at = NULL,
                    deleted_by_user_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 1
                  AND id IN ({_qf_in_params('q', len(query_ids))})
                """,
                {
                    "ws": self._ctx.workspace_id,
                    "uid": self._ctx.user_id,
                    **_bind_in("q", query_ids),
                },
            )

    def trash_subtree(self, *, folder_ids: List[str], query_ids: List[str]) -> None:
        with self._sql.transaction() as tx:
            if query_ids:
                tx.execute_write(
                    f"""
                    UPDATE saved_query
                    SET is_deleted = 1,
                        deleted_at = CURRENT_TIMESTAMP,
                        deleted_by_user_id = :uid,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE workspace_id = :ws
                      AND scope = 'MINE'
                      AND owner_user_id = :uid
                      AND is_deleted = 0
                      AND id IN ({_qf_in_params('q', len(query_ids))})
                    """,
                    {"ws": self._ctx.workspace_id, "uid": self._ctx.user_id, **_bind_in("q", query_ids)},
                )

            tx.execute_write(
                f"""
                UPDATE saved_query_folder
                SET is_deleted = 1,
                    deleted_at = CURRENT_TIMESTAMP,
                    deleted_by_user_id = :uid,
                    updated_at = CURRENT_TIMESTAMP
                WHERE workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 0
                  AND id IN ({_qf_in_params('f', len(folder_ids))})
                """,
                {"ws": self._ctx.workspace_id, "uid": self._ctx.user_id, **_bind_in("f", folder_ids)},
            )

    def purge_subtree(self, *, folder_ids_sorted: List[str], query_ids: List[str]) -> None:
        with self._sql.transaction() as tx:
            if query_ids:
                tx.execute_write(
                    f"""
                    DELETE FROM saved_query
                    WHERE workspace_id = :ws
                      AND scope = 'MINE'
                      AND owner_user_id = :uid
                      AND id IN ({_qf_in_params('q', len(query_ids))})
                    """,
                    {"ws": self._ctx.workspace_id, "uid": self._ctx.user_id, **_bind_in("q", query_ids)},
                )

            if folder_ids_sorted:
                tx.execute_write(
                    f"""
                    DELETE FROM saved_query_folder
                    WHERE workspace_id = :ws
                      AND scope = 'MINE'
                      AND owner_user_id = :uid
                      AND id IN ({_qf_in_params('f', len(folder_ids_sorted))})
                    """,
                    {"ws": self._ctx.workspace_id, "uid": self._ctx.user_id, **_bind_in("f", folder_ids_sorted)},
                )


class SavedQueryFolderWriteService:
    """Folder operations for scope='MINE' with delete/trash/restore/purge behavior."""

    def __init__(self, *, workspace_id: str, user_id: str, sql: Optional[ForgeQueryPort] = None):
        if not workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)
        if not user_id:
            raise ForgeError("user_id is required", status_code=400)

        self._ctx = _FolderContext(workspace_id=workspace_id, user_id=user_id)
        self._sql = sql or ForgeMetaSQL()
        self._repo = _FolderRepository(ctx=self._ctx, sql=self._sql)
        self._ws = workspace_id
        self._uid = user_id

    def create_folder(self, *, name: str, parent_folder_id: Optional[str] = None, sort_index: int = 0) -> Dict[str, Any]:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ForgeError("Folder name is required", status_code=400)
        if len(clean_name) > 255:
            raise ForgeError("Folder name is too long", status_code=400)

        normalized_parent = (str(parent_folder_id).strip() or None) if parent_folder_id is not None else None
        normalized_parent = self._normalize_parent_id(normalized_parent)
        if normalized_parent:
            self._assert_folder_exists(normalized_parent)

        folder_id = str(uuid.uuid4())
        try:
            self._repo.insert_folder(
                folder_id=folder_id,
                name=clean_name,
                parent_id=normalized_parent,
                sort_index=int(sort_index or 0),
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if "duplicate" in msg or "unique" in msg:
                raise ForgeError("Folder already exists", status_code=400) from exc
            raise

        return {
            "folderId": folder_id,
            "name": clean_name,
            "parentId": normalized_parent,
            "sortIndex": int(sort_index or 0),
        }

    def rename_folder(self, *, folder_id: str, name: str) -> Dict[str, Any]:
        folder_id = _req(folder_id, "folder_id")
        clean_name = (name or "").strip()
        if not clean_name:
            raise ForgeError("Folder name is required", status_code=400)
        if len(clean_name) > 255:
            raise ForgeError("Folder name is too long", status_code=400)

        self._assert_folder_exists(folder_id)

        try:
            updated = self._repo.rename_folder(folder_id=folder_id, name=clean_name)
        except IntegrityError as exc:
            raise ForgeError("Folder already exists", status_code=400) from exc

        if (updated or 0) == 0:
            raise ForgeError("Folder not found", status_code=404)

        return {"folderId": folder_id, "name": clean_name}

    def move_folder(self, *, folder_id: str, qf_new_parent_folder_id: Optional[str], new_sort_index: Optional[int] = None) -> Dict[str, Any]:
        folder_id = _req(folder_id, "folder_id")
        parent_id = _req(qf_new_parent_folder_id, "qf_new_parent_folder_id") if qf_new_parent_folder_id else None
        parent_id = self._normalize_parent_id(parent_id)

        self._assert_folder_exists(folder_id)
        if parent_id:
            self._assert_folder_exists(parent_id)

        if parent_id and self._is_descendant(descendant_id=parent_id, ancestor_id=folder_id):
            raise ForgeError("Invalid move (cannot move folder into itself)", status_code=400)

        updated = self._repo.move_folder(
            folder_id=folder_id,
            parent_id=parent_id,
            sort_index=(int(new_sort_index) if new_sort_index is not None else None),
        )
        if (updated or 0) == 0:
            raise ForgeError("Folder not found", status_code=404)

        return {"folderId": folder_id, "parentId": parent_id, "sortIndex": new_sort_index}

    def delete_folder(self, *, folder_id: str) -> Dict[str, Any]:
        folder_id = _req(folder_id, "folder_id")
        self._assert_folder_exists(folder_id)

        if self._count_child_folders(folder_id=folder_id) > 0 or self._count_child_queries(folder_id=folder_id) > 0:
            raise ForgeError("Folder is not empty", status_code=400)

        updated = self._repo.soft_delete_folder(folder_id=folder_id)
        if (updated or 0) == 0:
            raise ForgeError("Folder not found", status_code=404)

        return {"folderId": folder_id, "deleted": True}

    def trash_folder(self, *, folder_id: str) -> Dict[str, Any]:
        folder_id = _req(folder_id, "folder_id")
        self._assert_folder_exists(folder_id)

        folder_ids, query_ids = self._collect_subtree(folder_id=folder_id, qf_include_deleted=False)
        if not folder_ids:
            raise ForgeError("Folder not found", status_code=404)

        self._repo.trash_subtree(folder_ids=folder_ids, query_ids=query_ids)

        return {
            "folderId": folder_id,
            "deleted": True,
            "foldersTrashed": len(folder_ids),
            "queriesTrashed": len(query_ids),
        }

    def restore_folder(self, *, folder_id: str) -> Dict[str, Any]:
        folder_id = _req(folder_id, "folder_id")
        self._assert_folder_exists(folder_id, allow_deleted=True)

        ancestor_ids = self._collect_ancestor_chain(folder_id=folder_id)
        subtree_folder_ids, subtree_query_ids = self._collect_subtree(folder_id=folder_id, qf_include_deleted=True)
        all_folder_ids = list(dict.fromkeys(ancestor_ids + subtree_folder_ids))

        self._repo.restore_folder_ids(folder_ids=all_folder_ids)
        self._repo.restore_query_ids(query_ids=subtree_query_ids)

        return {
            "folderId": folder_id,
            "restored": True,
            "foldersRestored": len(all_folder_ids),
            "queriesRestored": len(subtree_query_ids),
        }

    def purge_folder(self, *, folder_id: str) -> Dict[str, Any]:
        folder_id = _req(folder_id, "folder_id")
        self._assert_folder_exists(folder_id, allow_deleted=True)

        folder_ids, query_ids = self._collect_subtree(folder_id=folder_id, qf_include_deleted=True)
        depths = self._depths_for_ids(folder_ids)
        sorted_folders = sorted(folder_ids, key=lambda item: depths.get(item, 0), reverse=True)

        self._repo.purge_subtree(folder_ids_sorted=sorted_folders, query_ids=query_ids)
        return {
            "folderId": folder_id,
            "purged": True,
            "foldersPurged": len(folder_ids),
            "queriesPurged": len(query_ids),
        }

    def _normalize_parent_id(self, parent_id: Optional[str]) -> Optional[str]:
        if parent_id and parent_id == f"user:{self._uid}":
            return None
        return parent_id

    def _assert_folder_exists(self, folder_id: str, allow_deleted: bool = False) -> None:
        if not self._repo.folder_exists(folder_id=folder_id, allow_deleted=allow_deleted):
            raise ForgeError("Folder not found", status_code=404)

    def _count_child_folders(self, *, folder_id: str) -> int:
        return self._repo.child_folder_count(folder_id=folder_id)

    def _count_child_queries(self, *, folder_id: str) -> int:
        return self._repo.child_query_count(folder_id=folder_id)

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

    def _fetch_all_folders(self, *, qf_include_deleted: bool) -> List[Dict[str, Any]]:
        return self._repo.fetch_all_folders(qf_include_deleted=qf_include_deleted)

    def _fetch_queries_in_folders(self, *, folder_ids: List[str], qf_include_deleted: bool) -> List[str]:
        return self._repo.fetch_queries_in_folders(folder_ids=folder_ids, qf_include_deleted=qf_include_deleted)

    def _collect_subtree(self, *, folder_id: str, qf_include_deleted: bool) -> Tuple[List[str], List[str]]:
        all_folders = self._fetch_all_folders(qf_include_deleted=qf_include_deleted)
        children_map: Dict[Optional[str], List[str]] = defaultdict(list)
        for row in all_folders:
            parent_id = str(row["parent_id"]) if row.get("parent_id") else None
            children_map[parent_id].append(str(row["id"]))

        stack = [folder_id]
        visited: Set[str] = set()
        subtree_folder_ids: List[str] = []

        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            subtree_folder_ids.append(current)
            stack.extend(children_map.get(current, []))

        subtree_query_ids = self._fetch_queries_in_folders(folder_ids=subtree_folder_ids, qf_include_deleted=qf_include_deleted)
        return subtree_folder_ids, subtree_query_ids

    def _collect_ancestor_chain(self, *, folder_id: str) -> List[str]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, parent_id
            FROM saved_query_folder
            WHERE workspace_id = :ws
              AND scope = 'MINE'
              AND owner_user_id = :uid
            """,
            {"ws": self._ws, "uid": self._uid},
        )

        parent_map: Dict[str, Optional[str]] = {}
        for row in rows:
            parent_map[str(row["id"])] = str(row["parent_id"]) if row.get("parent_id") else None

        chain: List[str] = []
        current: Optional[str] = folder_id
        for _ in range(256):
            if not current:
                break
            chain.append(current)
            current = parent_map.get(current)
        chain.reverse()
        return chain

    def _depths_for_ids(self, folder_ids: List[str]) -> Dict[str, int]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, parent_id
            FROM saved_query_folder
            WHERE workspace_id = :ws
              AND scope = 'MINE'
              AND owner_user_id = :uid
            """,
            {"ws": self._ws, "uid": self._uid},
        )

        parent_map: Dict[str, Optional[str]] = {}
        for row in rows:
            parent_map[str(row["id"])] = str(row["parent_id"]) if row.get("parent_id") else None

        depths: Dict[str, int] = {}
        for folder_id in folder_ids:
            depth = 0
            current = folder_id
            seen: Set[str] = set()
            while current and current not in seen and depth < 256:
                seen.add(current)
                current = parent_map.get(current)
                depth += 1
            depths[folder_id] = depth
        return depths


def _req(v: Any, field: str) -> str:
    value = str(v or "").strip()
    if not value:
        raise ForgeError(f"{field} is required", status_code=400)
    return value


def _qf_in_params(prefix: str, n: int) -> str:
    if n <= 0:
        return "NULL"
    return ",".join(f":{prefix}{idx}" for idx in range(n))


def _bind_in(prefix: str, values: List[str]) -> Dict[str, Any]:
    return {f"{prefix}{idx}": values[idx] for idx in range(len(values))}
