from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor

logger = logging.getLogger(__name__)

TreeView = Literal["my", "shared", "library", "trash"]


@dataclass(frozen=True)
class FolderRow:
    folder_id: str
    parent_folder_id: Optional[str]
    name: str
    sort_order: int
    deleted_at: Optional[datetime] = None


@dataclass(frozen=True)
class QueryRow:
    query_id: str
    folder_id: Optional[str]
    name: str
    owner_user_id: Optional[str]
    scope: str
    updated_at: Optional[datetime]
    tool: Optional[str] = None
    deleted_at: Optional[datetime] = None


class SavedQueryTreeService:
    """
    Option B / ACL-based schema

    DDL mapping:
      saved_query_folder.id -> folder_id
      saved_query_folder.parent_id -> parent_folder_id
      saved_query_folder.sort_index -> sort_order

      saved_query.id -> query_id
      saved_query.title -> name

      Shared view comes from saved_query_acl:
        - USER share: principal_type='USER' AND principal_id = :user_id
        - WORKSPACE share: principal_type='WORKSPACE' AND principal_id = :workspace_id
        - canEdit = permission == 'WRITE'
    """

    def __init__(self, *, workspace_id: str, user_id: str, user_display_name: str, sql: Optional[SQLExecutor] = None):
        if not workspace_id:
            raise ServiceError("workspace_id is required", status_code=400)
        if not user_id:
            raise ServiceError("user_id is required", status_code=400)
        if not user_display_name:
            raise ServiceError("user_display_name is required", status_code=400)

        self._workspace_id = workspace_id
        self._user_id = user_id
        self._user_display_name = user_display_name
        self._sql = sql or MySQLSQLExecutor()

    def _tool_from_sql_json(self, sql_json: Optional[str]) -> Optional[str]:
        if not sql_json:
            return None
        try:
            data = json.loads(sql_json) if isinstance(sql_json, str) else sql_json
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        meta = data.get("meta") if isinstance(data, dict) else None
        tool = meta.get("tool") if isinstance(meta, dict) else None
        if tool:
            return str(tool)
        return None

    def get_tree(self, *, view: TreeView) -> Dict[str, Any]:
        view = (view or "").strip().lower()
        if view not in ("my", "shared", "library", "trash"):
            raise ServiceError("Invalid view. Must be one of: my, shared, library, trash", status_code=400)

        if view == "shared":
            return self._get_shared_tree()

        if view == "my":
            folders = self._fetch_folders_my()
            queries = self._fetch_queries_my()
            roots = self._build_tree(folders, queries)

            user_root = {
                "nodeType": "folder",
                "id": f"user:{self._user_id}",
                "name": self._user_display_name,
                "parentId": None,
                "sortIndex": -2147483648,
                "isRoot": True,
                "children": roots,
            }
            return {"view": "my", "rootNodes": [user_root]}
        
        if view == "trash":
            return self._get_trash_tree()

        folders = self._fetch_folders_library()
        queries = self._fetch_queries_library()
        return {"view": "library", "rootNodes": self._build_tree(folders, queries)}

    # -------------------------
    # MY (scope=MINE)
    # -------------------------
    def _fetch_folders_my(self) -> List[FolderRow]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              f.id AS folder_id,
              f.parent_id AS parent_folder_id,
              f.name,
              f.sort_index AS sort_order
            FROM saved_query_folder f
            WHERE f.workspace_id = :ws
              AND f.scope = 'MINE'
              AND f.owner_user_id = :uid
              AND f.is_deleted = 0
            ORDER BY f.sort_index ASC, f.name ASC
            """,
            {"ws": self._workspace_id, "uid": self._user_id},
        )

        return [
            FolderRow(
                folder_id=str(r["folder_id"]),
                parent_folder_id=(str(r["parent_folder_id"]) if r["parent_folder_id"] else None),
                name=str(r["name"]),
                sort_order=int(r["sort_order"] or 0),
            )
            for r in rows
        ]

    def _fetch_queries_my(self) -> List[QueryRow]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              q.id AS query_id,
              q.folder_id,
              q.title AS name,
              q.owner_user_id,
              q.scope,
              q.updated_at,
              q.sql_json
            FROM saved_query q
            WHERE q.workspace_id = :ws
              AND q.scope = 'MINE'
              AND q.owner_user_id = :uid
              AND q.is_deleted = 0
            ORDER BY q.title ASC
            """,
            {"ws": self._workspace_id, "uid": self._user_id},
        )

        return [
            QueryRow(
                query_id=str(r["query_id"]),
                folder_id=(str(r["folder_id"]) if r["folder_id"] else None),
                name=str(r["name"]),
                owner_user_id=str(r["owner_user_id"]) if r["owner_user_id"] else None,
                scope=str(r["scope"]),
                updated_at=r["updated_at"],
                tool=self._tool_from_sql_json(r.get("sql_json")),
            )
            for r in rows
        ]

    # -------------------------
    # LIBRARY (scope=LIBRARY AND workspace_id IS NULL)
    # -------------------------
    def _fetch_folders_library(self) -> List[FolderRow]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              f.id AS folder_id,
              f.parent_id AS parent_folder_id,
              f.name,
              f.sort_index AS sort_order
            FROM saved_query_folder f
            WHERE f.scope = 'LIBRARY'
              AND f.workspace_id IS NULL
              AND f.owner_user_id IS NULL
              AND f.is_deleted = 0
            ORDER BY f.sort_index ASC, f.name ASC
            """
        )

        return [
            FolderRow(
                folder_id=str(r["folder_id"]),
                parent_folder_id=(str(r["parent_folder_id"]) if r["parent_folder_id"] else None),
                name=str(r["name"]),
                sort_order=int(r["sort_order"] or 0),
            )
            for r in rows
        ]

    def _fetch_queries_library(self) -> List[QueryRow]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              q.id AS query_id,
              q.folder_id,
              q.title AS name,
              q.owner_user_id,
              q.scope,
              q.updated_at,
              q.sql_json
            FROM saved_query q
            WHERE q.scope = 'LIBRARY'
              AND q.workspace_id IS NULL
              AND q.owner_user_id IS NULL
              AND q.is_deleted = 0
            ORDER BY q.title ASC
            """
        )

        return [
            QueryRow(
                query_id=str(r["query_id"]),
                folder_id=(str(r["folder_id"]) if r["folder_id"] else None),
                name=str(r["name"]),
                owner_user_id=str(r["owner_user_id"]) if r["owner_user_id"] else None,
                scope=str(r["scope"]),
                updated_at=r["updated_at"],
                tool=self._tool_from_sql_json(r.get("sql_json")),
            )
            for r in rows
        ]

    # -------------------------
    # SHARED (ACL)
    # -------------------------
    def _get_shared_tree(self) -> Dict[str, Any]:
        # folderless list; dedupe by query_id; canEdit if ANY acl row grants WRITE
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              q.id AS query_id,
              q.title AS name,
              q.owner_user_id,
              q.scope,
              q.updated_at,
              q.sql_json,
              MAX(CASE WHEN a.permission = 'WRITE' THEN 1 ELSE 0 END) AS can_edit
            FROM saved_query_acl a
            JOIN saved_query q
              ON q.id = a.saved_query_id
            WHERE q.workspace_id = :ws
              AND q.is_deleted = 0
              AND (
                (a.principal_type = 'WORKSPACE' AND a.principal_id = :ws)
                OR
                (a.principal_type = 'USER' AND a.principal_id = :uid)
              )
            GROUP BY q.id, q.title, q.owner_user_id, q.scope, q.updated_at, q.sql_json
            ORDER BY q.title ASC
            """,
            {"ws": self._workspace_id, "uid": self._user_id},
        )

        root_nodes: List[Dict[str, Any]] = []
        for r in rows:
            root_nodes.append(
                {
                    "nodeType": "query",
                    "id": str(r["query_id"]),
                    "name": str(r["name"]),
                    "folderId": None,
                    "updatedAt": r["updated_at"].isoformat() if r["updated_at"] else None,
                    "ownerUserId": str(r["owner_user_id"]) if r["owner_user_id"] else None,
                    "scope": str(r["scope"]),
                    "canEdit": bool(r["can_edit"]),
                    "queryType": self._tool_from_sql_json(r.get("sql_json")),
                }
            )

        return {"view": "shared", "rootNodes": root_nodes}


    def _build_tree(self, folders: List[FolderRow], queries: List[QueryRow]) -> List[Dict[str, Any]]:
        children: Dict[Optional[str], List[Dict[str, Any]]] = defaultdict(list)

        folder_nodes: Dict[str, Dict[str, Any]] = {}
        for f in folders:
            node = {
                "nodeType": "folder",
                "id": f.folder_id,
                "name": f.name,
                "parentId": f.parent_folder_id,
                "sortIndex": f.sort_order,
                "children": [],
            }
            folder_nodes[f.folder_id] = node
            children[f.parent_folder_id].append(node)

        for q in queries:
            qnode = {
                "nodeType": "query",
                "id": q.query_id,
                "name": q.name,
                "folderId": q.folder_id,
                "updatedAt": q.updated_at.isoformat() if q.updated_at else None,
                "ownerUserId": q.owner_user_id,
                "scope": q.scope,
                "queryType": q.tool,
            }
            children[q.folder_id].append(qnode)

        def sort_key(n: Dict[str, Any]):
            return (
                0 if n.get("nodeType") == "folder" else 1,
                int(n.get("sortIndex", 0) or 0),
                (n.get("name") or "").lower(),
            )

        for folder_id, fnode in folder_nodes.items():
            fnode["children"] = sorted(children.get(folder_id, []), key=sort_key)

        return sorted(children.get(None, []), key=sort_key)

    # -------------------------
    # TRASH (MINE only)
    # -------------------------
    def _get_trash_tree(self) -> Dict[str, Any]:
        folders = self._fetch_folders_trash()
        queries = self._fetch_queries_trash()

        root_nodes = self._build_trash_tree(folders, queries)

        trash_root = {
            "nodeType": "folder",
            "id": f"trash:{self._user_id}",
            "name": "Trash",
            "parentId": None,
            "sortIndex": -2147483648,
            "isRoot": True,
            "children": root_nodes,
        }
        return {"view": "trash", "rootNodes": [trash_root]}

    def _fetch_folders_trash(self) -> List[FolderRow]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
                id AS folder_id,
                parent_id AS parent_folder_id,
                name,
                sort_index AS sort_order,
                deleted_at
            FROM saved_query_folder
            WHERE workspace_id = :ws
                AND scope = 'MINE'
                AND owner_user_id = :uid
                AND is_deleted = 1
            ORDER BY sort_index ASC, name ASC
            """,
            {"ws": self._workspace_id, "uid": self._user_id},
        )

        return [
            FolderRow(
                folder_id=str(r["folder_id"]),
                parent_folder_id=(str(r["parent_folder_id"]) if r["parent_folder_id"] else None),
                name=str(r["name"]),
                sort_order=int(r["sort_order"] or 0),
                deleted_at=r.get("deleted_at"),
            )
            for r in rows
        ]

    def _fetch_queries_trash(self) -> List[QueryRow]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
                id AS query_id,
                folder_id,
                title AS name,
                owner_user_id,
                scope,
                updated_at,
                sql_json,
                deleted_at
            FROM saved_query
            WHERE workspace_id = :ws
                AND scope = 'MINE'
                AND owner_user_id = :uid
                AND is_deleted = 1
            ORDER BY deleted_at DESC, title ASC
            """,
            {"ws": self._workspace_id, "uid": self._user_id},
        )

        return [
            QueryRow(
                query_id=str(r["query_id"]),
                folder_id=(str(r["folder_id"]) if r["folder_id"] else None),
                name=str(r["name"]),
                owner_user_id=str(r["owner_user_id"]) if r["owner_user_id"] else None,
                scope=str(r["scope"]),
                updated_at=r.get("updated_at"),
                tool=self._tool_from_sql_json(r.get("sql_json")),
                deleted_at=r.get("deleted_at"),
            )
            for r in rows
        ]

    def _build_trash_tree(self, folders: List[FolderRow], queries: List[QueryRow]) -> List[Dict[str, Any]]:
        """
        Build a Trash tree.

        Rules:
        - Only deleted folders are rendered as folders.
        - A deleted query attaches under its folder only if that folder is also deleted (in this trash set).
        - Otherwise, deleted query shows at trash root.
        """

        children: Dict[Optional[str], List[Dict[str, Any]]] = defaultdict(list)
        folder_nodes: Dict[str, Dict[str, Any]] = {}

        trashed_folder_ids = {f.folder_id for f in folders}

        # folder nodes
        for f in folders:
            node = {
                "nodeType": "folder",
                "id": f.folder_id,
                "name": f.name,
                "parentId": f.parent_folder_id if f.parent_folder_id in trashed_folder_ids else None,
                "sortIndex": f.sort_order,
                "deletedAt": f.deleted_at.isoformat() if f.deleted_at else None,
                "children": [],
            }
            folder_nodes[f.folder_id] = node
            children[node["parentId"]].append(node)

        # query nodes
        for q in queries:
            attach_parent = q.folder_id if (q.folder_id and q.folder_id in trashed_folder_ids) else None
            qnode = {
                "nodeType": "query",
                "id": q.query_id,
                "name": q.name,
                "folderId": q.folder_id,
                "updatedAt": q.updated_at.isoformat() if q.updated_at else None,
                "deletedAt": q.deleted_at.isoformat() if q.deleted_at else None,
                "ownerUserId": q.owner_user_id,
                "scope": q.scope,
                "isDeleted": True,
                "queryType": q.tool,
            }
            children[attach_parent].append(qnode)

        def sort_key(n: Dict[str, Any]):
            # folders first; then newest deleted queries first; then name
            if n.get("nodeType") == "folder":
                return (0, int(n.get("sortIndex", 0) or 0), (n.get("name") or "").lower())
            # queries: prefer deletedAt desc (None last)
            da = n.get("deletedAt") or ""
            return (1, -1 if da else 0, da, (n.get("name") or "").lower())

        # attach children to folders
        for folder_id, fnode in folder_nodes.items():
            fnode["children"] = sorted(children.get(folder_id, []), key=sort_key)

        # roots
        return sorted(children.get(None, []), key=sort_key)
