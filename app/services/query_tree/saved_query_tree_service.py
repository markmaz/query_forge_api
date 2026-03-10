from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

TreeView = Literal["my", "shared", "library", "trash"]


@dataclass(frozen=True)
class ForgeFolderRow:
    folder_id: str
    parent_folder_id: Optional[str]
    name: str
    sort_order: int
    deleted_at: Optional[datetime] = None


@dataclass(frozen=True)
class ForgeQueryRow:
    query_id: str
    folder_id: Optional[str]
    name: str
    owner_user_id: Optional[str]
    scope: str
    updated_at: Optional[datetime]
    tool: Optional[str] = None
    deleted_at: Optional[datetime] = None


@dataclass(frozen=True)
class _TreeContext:
    workspace_id: str
    user_id: str
    user_display_name: str


class _TreeRepository:
    def __init__(self, *, ctx: _TreeContext, sql: ForgeQueryPort):
        self._ctx = ctx
        self._sql = sql

    def fetch_my_folders(self) -> List[ForgeFolderRow]:
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
            {"ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
        )
        return [
            ForgeFolderRow(
                folder_id=str(row["folder_id"]),
                parent_folder_id=(str(row["parent_folder_id"]) if row["parent_folder_id"] else None),
                name=str(row["name"]),
                sort_order=int(row.get("sort_order") or 0),
            )
            for row in rows
        ]

    def fetch_my_queries(self, *, tool_parser) -> List[ForgeQueryRow]:
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
            {"ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
        )
        return [
            ForgeQueryRow(
                query_id=str(row["query_id"]),
                folder_id=(str(row["folder_id"]) if row["folder_id"] else None),
                name=str(row["name"]),
                owner_user_id=(str(row["owner_user_id"]) if row["owner_user_id"] else None),
                scope=str(row["scope"]),
                updated_at=row.get("updated_at"),
                tool=tool_parser(row.get("sql_json")),
            )
            for row in rows
        ]

    def fetch_library_folders(self) -> List[ForgeFolderRow]:
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
            ForgeFolderRow(
                folder_id=str(row["folder_id"]),
                parent_folder_id=(str(row["parent_folder_id"]) if row["parent_folder_id"] else None),
                name=str(row["name"]),
                sort_order=int(row.get("sort_order") or 0),
            )
            for row in rows
        ]

    def fetch_library_queries(self, *, tool_parser) -> List[ForgeQueryRow]:
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
            ForgeQueryRow(
                query_id=str(row["query_id"]),
                folder_id=(str(row["folder_id"]) if row["folder_id"] else None),
                name=str(row["name"]),
                owner_user_id=(str(row["owner_user_id"]) if row["owner_user_id"] else None),
                scope=str(row["scope"]),
                updated_at=row.get("updated_at"),
                tool=tool_parser(row.get("sql_json")),
            )
            for row in rows
        ]

    def fetch_shared_rows(self) -> List[Dict[str, Any]]:
        return self._sql.execute_query_mappings(
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
            {"ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
        )

    def fetch_trash_folders(self) -> List[ForgeFolderRow]:
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
            {"ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
        )
        return [
            ForgeFolderRow(
                folder_id=str(row["folder_id"]),
                parent_folder_id=(str(row["parent_folder_id"]) if row["parent_folder_id"] else None),
                name=str(row["name"]),
                sort_order=int(row.get("sort_order") or 0),
                deleted_at=row.get("deleted_at"),
            )
            for row in rows
        ]

    def fetch_trash_queries(self, *, tool_parser) -> List[ForgeQueryRow]:
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
            {"ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
        )
        return [
            ForgeQueryRow(
                query_id=str(row["query_id"]),
                folder_id=(str(row["folder_id"]) if row["folder_id"] else None),
                name=str(row["name"]),
                owner_user_id=(str(row["owner_user_id"]) if row["owner_user_id"] else None),
                scope=str(row["scope"]),
                updated_at=row.get("updated_at"),
                tool=tool_parser(row.get("sql_json")),
                deleted_at=row.get("deleted_at"),
            )
            for row in rows
        ]


class _TreeAssembler:
    @staticmethod
    def assemble(folders: List[ForgeFolderRow], queries: List[ForgeQueryRow]) -> List[Dict[str, Any]]:
        children: Dict[Optional[str], List[Dict[str, Any]]] = defaultdict(list)
        folder_nodes: Dict[str, Dict[str, Any]] = {}

        for folder in folders:
            node = {
                "nodeType": "folder",
                "id": folder.folder_id,
                "name": folder.name,
                "parentId": folder.parent_folder_id,
                "sortIndex": folder.sort_order,
                "children": [],
            }
            folder_nodes[folder.folder_id] = node
            children[folder.parent_folder_id].append(node)

        for query in queries:
            children[query.folder_id].append(
                {
                    "nodeType": "query",
                    "id": query.query_id,
                    "name": query.name,
                    "folderId": query.folder_id,
                    "updatedAt": query.updated_at.isoformat() if query.updated_at else None,
                    "ownerUserId": query.owner_user_id,
                    "scope": query.scope,
                    "queryType": query.tool,
                }
            )

        for folder_id, node in folder_nodes.items():
            node["children"] = sorted(children.get(folder_id, []), key=_tree_sort_key)

        return sorted(children.get(None, []), key=_tree_sort_key)

    @staticmethod
    def assemble_trash(folders: List[ForgeFolderRow], queries: List[ForgeQueryRow]) -> List[Dict[str, Any]]:
        children: Dict[Optional[str], List[Dict[str, Any]]] = defaultdict(list)
        folder_nodes: Dict[str, Dict[str, Any]] = {}
        trashed_folder_ids = {folder.folder_id for folder in folders}

        for folder in folders:
            parent_id = folder.parent_folder_id if folder.parent_folder_id in trashed_folder_ids else None
            node = {
                "nodeType": "folder",
                "id": folder.folder_id,
                "name": folder.name,
                "parentId": parent_id,
                "sortIndex": folder.sort_order,
                "deletedAt": folder.deleted_at.isoformat() if folder.deleted_at else None,
                "children": [],
            }
            folder_nodes[folder.folder_id] = node
            children[parent_id].append(node)

        for query in queries:
            attach_parent = query.folder_id if query.folder_id in trashed_folder_ids else None
            children[attach_parent].append(
                {
                    "nodeType": "query",
                    "id": query.query_id,
                    "name": query.name,
                    "folderId": query.folder_id,
                    "updatedAt": query.updated_at.isoformat() if query.updated_at else None,
                    "deletedAt": query.deleted_at.isoformat() if query.deleted_at else None,
                    "ownerUserId": query.owner_user_id,
                    "scope": query.scope,
                    "isDeleted": True,
                    "queryType": query.tool,
                }
            )

        for folder_id, node in folder_nodes.items():
            node["children"] = sorted(children.get(folder_id, []), key=_trash_sort_key)

        return sorted(children.get(None, []), key=_trash_sort_key)


class SavedQueryTreeService:
    def __init__(self, *, workspace_id: str, user_id: str, user_display_name: str, sql: Optional[ForgeQueryPort] = None):
        if not workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)
        if not user_id:
            raise ForgeError("user_id is required", status_code=400)
        if not user_display_name:
            raise ForgeError("user_display_name is required", status_code=400)

        self._ctx = _TreeContext(workspace_id=workspace_id, user_id=user_id, user_display_name=user_display_name)
        self._sql = sql or ForgeMetaSQL()
        self._repo = _TreeRepository(ctx=self._ctx, sql=self._sql)

    def get_tree(self, *, view: TreeView) -> Dict[str, Any]:
        normalized = (view or "").strip().lower()
        builders = {
            "my": self._build_my_view,
            "shared": self._get_shared_tree,
            "library": self._build_library_view,
            "trash": self._get_trash_tree,
        }
        build = builders.get(normalized)
        if build is None:
            raise ForgeError("Invalid view. Must be one of: my, shared, library, trash", status_code=400)
        return build()

    def _tool_from_sql_json(self, sql_json: Optional[Any]) -> Optional[str]:
        if sql_json is None:
            return None
        payload = sql_json
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                return None
        if not isinstance(payload, dict):
            return None
        meta = payload.get("meta")
        if not isinstance(meta, dict):
            return None
        tool = meta.get("tool")
        return str(tool) if tool else None

    def _build_my_view(self) -> Dict[str, Any]:
        roots = self._build_tree(self._fetch_folders_my(), self._fetch_queries_my())
        user_root = {
            "nodeType": "folder",
            "id": f"user:{self._ctx.user_id}",
            "name": self._ctx.user_display_name,
            "parentId": None,
            "sortIndex": -2147483648,
            "isRoot": True,
            "children": roots,
        }
        return {"view": "my", "rootNodes": [user_root]}

    def _build_library_view(self) -> Dict[str, Any]:
        return {
            "view": "library",
            "rootNodes": self._build_tree(self._fetch_folders_library(), self._fetch_queries_library()),
        }

    def _fetch_folders_my(self) -> List[ForgeFolderRow]:
        return self._repo.fetch_my_folders()

    def _fetch_queries_my(self) -> List[ForgeQueryRow]:
        return self._repo.fetch_my_queries(tool_parser=self._tool_from_sql_json)

    def _fetch_folders_library(self) -> List[ForgeFolderRow]:
        return self._repo.fetch_library_folders()

    def _fetch_queries_library(self) -> List[ForgeQueryRow]:
        return self._repo.fetch_library_queries(tool_parser=self._tool_from_sql_json)

    def _get_shared_tree(self) -> Dict[str, Any]:
        qf_root_nodes: List[Dict[str, Any]] = []
        for row in self._repo.fetch_shared_rows():
            qf_root_nodes.append(
                {
                    "nodeType": "query",
                    "id": str(row["query_id"]),
                    "name": str(row["name"]),
                    "folderId": None,
                    "updatedAt": row["updated_at"].isoformat() if row.get("updated_at") else None,
                    "ownerUserId": str(row["owner_user_id"]) if row.get("owner_user_id") else None,
                    "scope": str(row["scope"]),
                    "canEdit": bool(row.get("can_edit")),
                    "queryType": self._tool_from_sql_json(row.get("sql_json")),
                }
            )
        return {"view": "shared", "rootNodes": qf_root_nodes}

    def _build_tree(self, folders: List[ForgeFolderRow], queries: List[ForgeQueryRow]) -> List[Dict[str, Any]]:
        return _TreeAssembler.assemble(folders, queries)

    def _get_trash_tree(self) -> Dict[str, Any]:
        qf_root_nodes = self._build_trash_tree(self._fetch_folders_trash(), self._fetch_queries_trash())
        trash_root = {
            "nodeType": "folder",
            "id": f"trash:{self._ctx.user_id}",
            "name": "Trash",
            "parentId": None,
            "sortIndex": -2147483648,
            "isRoot": True,
            "children": qf_root_nodes,
        }
        return {"view": "trash", "rootNodes": [trash_root]}

    def _fetch_folders_trash(self) -> List[ForgeFolderRow]:
        return self._repo.fetch_trash_folders()

    def _fetch_queries_trash(self) -> List[ForgeQueryRow]:
        return self._repo.fetch_trash_queries(tool_parser=self._tool_from_sql_json)

    def _build_trash_tree(self, folders: List[ForgeFolderRow], queries: List[ForgeQueryRow]) -> List[Dict[str, Any]]:
        return _TreeAssembler.assemble_trash(folders, queries)


def _tree_sort_key(node: Dict[str, Any]) -> Any:
    return (
        0 if node.get("nodeType") == "folder" else 1,
        int(node.get("sortIndex", 0) or 0),
        (node.get("name") or "").lower(),
    )


def _trash_sort_key(node: Dict[str, Any]) -> Any:
    if node.get("nodeType") == "folder":
        return (0, int(node.get("sortIndex", 0) or 0), (node.get("name") or "").lower())

    deleted_at = node.get("deletedAt") or ""
    return (1, -1 if deleted_at else 0, deleted_at, (node.get("name") or "").lower())
