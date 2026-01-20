from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.exc import IntegrityError

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor


class SavedQueryFolderWriteService:
    """
    Folder operations for MINE scope with trash/restore/purge support.

    Supported operations:
      - create_folder / rename_folder / move_folder / delete_folder (empty-only)
      - trash_folder: soft-deletes folder subtree (folders + queries)
      - restore_folder: restores folder subtree AND restores ancestor chain if needed
      - purge_folder: permanently deletes folder subtree (queries first, then folders)
    """

    def __init__(self, *, workspace_id: str, user_id: str, sql: Optional[SQLExecutor] = None):
        if not workspace_id:
            raise ServiceError("workspace_id is required", status_code=400)
        if not user_id:
            raise ServiceError("user_id is required", status_code=400)
        self._ws = workspace_id
        self._uid = user_id
        self._sql = sql or MySQLSQLExecutor()

    # -------------------------
    # Create / rename / move / delete (empty-only)
    # -------------------------
    def create_folder(self, *, name: str, parent_folder_id: Optional[str] = None, sort_index: int = 0) -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ServiceError("Folder name is required", status_code=400)
        if len(name) > 255:
            raise ServiceError("Folder name is too long", status_code=400)

        parent_id = (str(parent_folder_id).strip() or None) if parent_folder_id is not None else None
        parent_id = self._normalize_parent_id(parent_id)
        if parent_id:
            self._assert_folder_exists(parent_id)

        folder_id = str(uuid.uuid4())
        try:
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
                        "ws": self._ws,
                        "uid": self._uid,
                        "parent_id": parent_id,
                        "name": name,
                        "sort_index": int(sort_index or 0),
                    },
                )
        except Exception as exc:  # noqa: BLE001
            # Likely sibling name conflict (uq_sqf_sibling_name); surface as 400
            msg = str(exc).lower()
            if "duplicate" in msg or "unique" in msg:
                raise ServiceError("Folder already exists", status_code=400) from exc
            raise

        return {
            "folderId": folder_id,
            "name": name,
            "parentId": parent_id,
            "sortIndex": int(sort_index or 0),
        }


    def rename_folder(self, *, folder_id: str, name: str) -> Dict[str, Any]:
        fid = _req(folder_id, "folder_id")
        name = (name or "").strip()
        if not name:
            raise ServiceError("Folder name is required", status_code=400)
        if len(name) > 255:
            raise ServiceError("Folder name is too long", status_code=400)

        self._assert_folder_exists(fid)

        try:
            with self._sql.transaction() as tx:
                res = tx.execute_write(
                    """
                    UPDATE saved_query_folder
                    SET name = :name, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :fid
                    AND workspace_id = :ws
                    AND scope = 'MINE'
                    AND owner_user_id = :uid
                    AND is_deleted = 0
                    """,
                    {"fid": fid, "ws": self._ws, "uid": self._uid, "name": name},
                )
        except IntegrityError as exc:
            raise ServiceError("Folder already exists", status_code=400) from exc

        if (res or 0) == 0:
            raise ServiceError("Folder not found", status_code=404)

        return {"folderId": fid, "name": name}

    def move_folder(self, *, folder_id: str, new_parent_folder_id: Optional[str], new_sort_index: Optional[int] = None) -> Dict[str, Any]:
        fid = _req(folder_id, "folder_id")
        parent_id = _req(new_parent_folder_id, "new_parent_folder_id") if new_parent_folder_id else None
        parent_id = self._normalize_parent_id(parent_id)

        self._assert_folder_exists(fid)
        if parent_id:
            self._assert_folder_exists(parent_id)

        if parent_id and self._is_descendant(descendant_id=parent_id, ancestor_id=fid):
            raise ServiceError("Invalid move (cannot move folder into itself)", status_code=400)

        with self._sql.transaction() as tx:
            res = tx.execute_write(
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
                    "fid": fid,
                    "ws": self._ws,
                    "uid": self._uid,
                    "parent_id": parent_id,
                    "sort_index": (int(new_sort_index) if new_sort_index is not None else None),
                },
            )
            if (res or 0) == 0:
                raise ServiceError("Folder not found", status_code=404)

        return {"folderId": fid, "parentId": parent_id, "sortIndex": new_sort_index}

    def delete_folder(self, *, folder_id: str) -> Dict[str, Any]:
        """
        Soft delete a folder only if it has no active child folders or queries.
        Use trash_folder for recursive delete.
        """
        fid = _req(folder_id, "folder_id")
        self._assert_folder_exists(fid)

        if self._count_child_folders(folder_id=fid) > 0 or self._count_child_queries(folder_id=fid) > 0:
            raise ServiceError("Folder is not empty", status_code=400)

        with self._sql.transaction() as tx:
            res = tx.execute_write(
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
                {"fid": fid, "ws": self._ws, "uid": self._uid},
            )
            if (res or 0) == 0:
                raise ServiceError("Folder not found", status_code=404)

        return {"folderId": fid, "deleted": True}

    # -------------------------
    # TRASH (soft delete)
    # -------------------------
    def trash_folder(self, *, folder_id: str) -> Dict[str, Any]:
        fid = _req(folder_id, "folder_id")
        self._assert_folder_exists(fid)

        folder_ids, query_ids = self._collect_subtree(folder_id=fid, include_deleted=False)

        if not folder_ids:
            # Should not happen because folder exists, but guard against data races/bugs
            raise ServiceError("Folder not found", status_code=404)

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
                      AND id IN ({_in_params('q', len(query_ids))})
                    """,
                    {"ws": self._ws, "uid": self._uid, **_bind_in("q", query_ids)},
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
                  AND id IN ({_in_params('f', len(folder_ids))})
                """,
                {"ws": self._ws, "uid": self._uid, **_bind_in("f", folder_ids)},
            )

        return {"folderId": fid, "deleted": True, "foldersTrashed": len(folder_ids), "queriesTrashed": len(query_ids)}

    # -------------------------
    # RESTORE
    # -------------------------
    def restore_folder(self, *, folder_id: str) -> Dict[str, Any]:
        fid = _req(folder_id, "folder_id")
        # must exist (even if deleted)
        self._assert_folder_exists(fid, allow_deleted=True)

        # 1) restore ancestor chain (so folder has a visible path)
        ancestor_ids = self._collect_ancestor_chain(folder_id=fid)

        # 2) restore subtree (including deleted nodes)
        folder_ids, query_ids = self._collect_subtree(folder_id=fid, include_deleted=True)

        # union ancestors + subtree folders
        all_folder_ids = list(dict.fromkeys(ancestor_ids + folder_ids))  # stable unique

        with self._sql.transaction() as tx:
            if all_folder_ids:
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
                      AND id IN ({_in_params('f', len(all_folder_ids))})
                    """,
                    {"ws": self._ws, "uid": self._uid, **_bind_in("f", all_folder_ids)},
                )

            if query_ids:
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
                      AND id IN ({_in_params('q', len(query_ids))})
                    """,
                    {"ws": self._ws, "uid": self._uid, **_bind_in("q", query_ids)},
                )

        return {
            "folderId": fid,
            "restored": True,
            "foldersRestored": len(all_folder_ids),
            "queriesRestored": len(query_ids),
        }

    # -------------------------
    # PURGE (hard delete)
    # -------------------------
    def purge_folder(self, *, folder_id: str) -> Dict[str, Any]:
        fid = _req(folder_id, "folder_id")
        self._assert_folder_exists(fid, allow_deleted=True)

        folder_ids, query_ids = self._collect_subtree(folder_id=fid, include_deleted=True)

        # Purge order matters: queries -> folders (due to FK folder parent self-reference + query FK)
        with self._sql.transaction() as tx:
            if query_ids:
                tx.execute_write(
                    f"""
                    DELETE FROM saved_query
                    WHERE workspace_id = :ws
                      AND scope = 'MINE'
                      AND owner_user_id = :uid
                      AND id IN ({_in_params('q', len(query_ids))})
                    """,
                    {"ws": self._ws, "uid": self._uid, **_bind_in("q", query_ids)},
                )

            # Delete folders deepest-first to satisfy parent FK RESTRICT
            folder_depths = self._depths_for_ids(folder_ids)
            folder_ids_sorted = sorted(folder_ids, key=lambda x: folder_depths.get(x, 0), reverse=True)

            if folder_ids_sorted:
                tx.execute_write(
                    f"""
                    DELETE FROM saved_query_folder
                    WHERE workspace_id = :ws
                      AND scope = 'MINE'
                      AND owner_user_id = :uid
                      AND id IN ({_in_params('f', len(folder_ids_sorted))})
                    """,
                    {"ws": self._ws, "uid": self._uid, **_bind_in("f", folder_ids_sorted)},
                )

        return {"folderId": fid, "purged": True, "foldersPurged": len(folder_ids), "queriesPurged": len(query_ids)}

    # -------------------------
    # INTERNAL: graph helpers
    # -------------------------
    def _normalize_parent_id(self, parent_id: Optional[str]) -> Optional[str]:
        if parent_id and parent_id == f"user:{self._uid}":
            return None
        return parent_id

    def _assert_folder_exists(self, folder_id: str, allow_deleted: bool = False) -> None:
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
            {"fid": folder_id, "ws": self._ws, "uid": self._uid, "allow_deleted": 1 if allow_deleted else 0},
        )
        row = rows[0] if rows else None
        if not row:
            raise ServiceError("Folder not found", status_code=404)

    def _count_child_folders(self, *, folder_id: str) -> int:
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
            {"fid": folder_id, "ws": self._ws, "uid": self._uid},
        )
        row = rows[0] if rows else None
        return int(row["n"] or 0)

    def _count_child_queries(self, *, folder_id: str) -> int:
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
            {"fid": folder_id, "ws": self._ws, "uid": self._uid},
        )
        row = rows[0] if rows else None
        return int(row["n"] or 0)

    def _is_descendant(self, *, descendant_id: str, ancestor_id: str) -> bool:
        """
        Walk parent pointers to see if descendant_id is under ancestor_id.
        """
        current = descendant_id
        for _ in range(128):
            if not current:
                return False
            if current == ancestor_id:
                return True
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
                {"fid": current, "ws": self._ws, "uid": self._uid},
            )
            row = rows[0] if rows else None
            if not row:
                return False
            current = row["parent_id"]
        raise ServiceError("Folder hierarchy too deep", status_code=400)

    def _fetch_all_folders(self, *, include_deleted: bool) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, parent_id, is_deleted
            FROM saved_query_folder
            WHERE workspace_id = :ws
              AND scope = 'MINE'
              AND owner_user_id = :uid
              AND (:include_deleted = 1 OR is_deleted = 0)
            """,
            {"ws": self._ws, "uid": self._uid, "include_deleted": 1 if include_deleted else 0},
        )
        return [dict(r) for r in rows]

    def _fetch_queries_in_folders(self, *, folder_ids: List[str], include_deleted: bool) -> List[str]:
        if not folder_ids:
            return []
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT id
            FROM saved_query
            WHERE workspace_id = :ws
              AND scope = 'MINE'
              AND owner_user_id = :uid
              AND (:include_deleted = 1 OR is_deleted = 0)
              AND folder_id IN ({_in_params('f', len(folder_ids))})
            """,
            {"ws": self._ws, "uid": self._uid, "include_deleted": 1 if include_deleted else 0, **_bind_in("f", folder_ids)},
        )
        return [str(r["id"]) for r in rows]

    def _collect_subtree(self, *, folder_id: str, include_deleted: bool) -> Tuple[List[str], List[str]]:
        folders = self._fetch_all_folders(include_deleted=include_deleted)

        children: Dict[Optional[str], List[str]] = defaultdict(list)
        for r in folders:
            pid = str(r["parent_id"]) if r["parent_id"] else None
            children[pid].append(str(r["id"]))

        # BFS/DFS collect folder subtree
        out_folders: List[str] = []
        stack = [folder_id]
        seen: Set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            out_folders.append(cur)
            for ch in children.get(cur, []):
                stack.append(ch)

        query_ids = self._fetch_queries_in_folders(folder_ids=out_folders, include_deleted=include_deleted)
        return out_folders, query_ids

    def _collect_ancestor_chain(self, *, folder_id: str) -> List[str]:
        """
        Returns [root ... parent ... folder_id] for this folder (including itself),
        restricted to this user's MINE namespace, including deleted.
        """
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

        parent_of: Dict[str, Optional[str]] = {}
        for r in rows:
            parent_of[str(r["id"])] = (str(r["parent_id"]) if r["parent_id"] else None)

        chain: List[str] = []
        cur: Optional[str] = folder_id
        for _ in range(256):
            if not cur:
                break
            chain.append(cur)
            cur = parent_of.get(cur)
        chain.reverse()
        return chain

    def _depths_for_ids(self, folder_ids: List[str]) -> Dict[str, int]:
        """
        Compute depths for sorting purge order (deepest-first).
        """
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

        parent_of: Dict[str, Optional[str]] = {}
        for r in rows:
            parent_of[str(r["id"])] = (str(r["parent_id"]) if r["parent_id"] else None)

        depths: Dict[str, int] = {}
        for fid in folder_ids:
            d = 0
            cur = fid
            seen = set()
            while cur and cur not in seen and d < 256:
                seen.add(cur)
                cur = parent_of.get(cur)
                d += 1
            depths[fid] = d
        return depths


def _req(v: Any, field: str) -> str:
    s = str(v or "").strip()
    if not s:
        raise ServiceError(f"{field} is required", status_code=400)
    return s


def _in_params(prefix: str, n: int) -> str:
    if n <= 0:
        # should never be used with 0, but guard
        return "NULL"
    return ",".join([f":{prefix}{i}" for i in range(n)])


def _bind_in(prefix: str, values: List[str]) -> Dict[str, Any]:
    return {f"{prefix}{i}": values[i] for i in range(len(values))}
