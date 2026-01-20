from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SavedQueryReadResult:
    query_id: str
    workspace_id: Optional[str]
    scope: str

    owner_user_id: Optional[str]
    folder_id: Optional[str]

    title: str
    description: Optional[str]

    sql_json: Dict[str, Any]

    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    # access metadata
    can_edit: bool
    access_via: str  # "owner" | "share" | "admin" | "library"

@dataclass(frozen=True)
class RecentQueryItem:
    id: str
    title: str
    updated_at: Optional[datetime]
    scope: str
    folder_id: Optional[str]

class SavedQueryReadService:
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


    """Read (hydrate) a saved query, enforcing access rules.

    Access rules:
      - Library queries (scope='LIBRARY' AND workspace_id IS NULL): readable by any caller; can_edit only if admin.
      - Non-library queries: workspace_id must match caller workspace_id
      - A user can read if:
          * they are the owner
          * or the query is shared to them (workspace share or user share) via saved_query_acl
      - can_edit is true if:
          * owner, or
          * share row has permission WRITE, or
          * admin reading library

    Notes:
      - This service returns sql_json to rehydrate the query builder.
      - It does NOT execute SQL.
    """

    def __init__(self, *, workspace_id: str, user_id: str, is_admin: bool = False, sql: Optional[SQLExecutor] = None):
        if not user_id:
            raise ServiceError("user_id is required", status_code=400)
        # workspace_id may be unused when reading LIBRARY, but keep validation consistent
        if workspace_id is None:
            raise ServiceError("workspace_id is required", status_code=400)

        self._workspace_id = workspace_id
        self._user_id = user_id
        self._is_admin = bool(is_admin)
        self._sql = sql or MySQLSQLExecutor()

    def get_query(self, query_id: str) -> Dict[str, Any]:
        q = self._fetch_query(query_id)

        # Determine if this is a LIBRARY query
        is_library = (q["scope"] == "LIBRARY" and q["workspace_id"] is None)

        if is_library:
            result = SavedQueryReadResult(
                query_id=str(q["query_id"]),
                workspace_id=None,
                scope=str(q["scope"]),
                owner_user_id=str(q["owner_user_id"]) if q["owner_user_id"] else None,
                folder_id=str(q["folder_id"]) if q["folder_id"] else None,
                title=str(q["title"]),
                description=str(q["description"]) if q["description"] else None,
                sql_json=q["sql_json"],
                created_at=q.get("created_at"),
                updated_at=q.get("updated_at"),
                can_edit=bool(self._is_admin),
                access_via=("admin" if self._is_admin else "library"),
            )
            return _to_payload(result)

        # Non-library must be in caller's workspace
        if not self._workspace_id:
            raise ServiceError("workspace_id is required", status_code=400)

        if str(q["workspace_id"]) != str(self._workspace_id):
            raise ServiceError("Query not found in this workspace", status_code=404)

        # Owner access
        owner_user_id = str(q["owner_user_id"]) if q["owner_user_id"] else None
        if owner_user_id and owner_user_id == self._user_id:
            result = SavedQueryReadResult(
                query_id=str(q["query_id"]),
                workspace_id=str(q["workspace_id"]),
                scope=str(q["scope"]),
                owner_user_id=owner_user_id,
                folder_id=str(q["folder_id"]) if q["folder_id"] else None,
                title=str(q["title"]),
                description=str(q["description"]) if q["description"] else None,
                sql_json=q["sql_json"],
                created_at=q.get("created_at"),
                updated_at=q.get("updated_at"),
                can_edit=True,
                access_via="owner",
            )
            return _to_payload(result)

        # Shared access
        share = self._fetch_share_access(query_id=str(q["query_id"]))
        if not share["has_access"]:
            # Hide existence across users
            raise ServiceError("Saved query not found", status_code=404)

        result = SavedQueryReadResult(
            query_id=str(q["query_id"]),
            workspace_id=str(q["workspace_id"]),
            scope=str(q["scope"]),
            owner_user_id=owner_user_id,
            folder_id=str(q["folder_id"]) if q["folder_id"] else None,
            title=str(q["title"]),
            description=str(q["description"]) if q["description"] else None,
            sql_json=q["sql_json"],
            created_at=q.get("created_at"),
            updated_at=q.get("updated_at"),
            can_edit=bool(share["can_edit"]),
            access_via="share",
        )
        return _to_payload(result)

    # -------------------------
    # DB
    # -------------------------
    def _fetch_query(self, query_id: str) -> Dict[str, Any]:
        if not query_id or not isinstance(query_id, str):
            raise ServiceError("Invalid query_id", status_code=400)

        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id AS query_id,
              workspace_id,
              scope,
              owner_user_id,
              folder_id,
              title,
              description,
              sql_json,
              created_at,
              updated_at
            FROM saved_query
            WHERE id = :qid
              AND is_deleted = 0
            LIMIT 1
            """,
            {"qid": query_id},
        )
        row = rows[0] if rows else None

        if not row:
            raise ServiceError("Saved query not found", status_code=404)

        # sql_json should be a dict already via SQLAlchemy JSON -> Python, but guard anyway
        sj = row["sql_json"]
        if sj is None:
            raise ServiceError("Saved query is missing sql_json", status_code=500)
        if isinstance(sj, str):
            try:
                sj = json.loads(sj)
            except json.JSONDecodeError as exc:
                raise ServiceError("Saved query sql_json is invalid JSON", status_code=500) from exc
        if not isinstance(sj, dict):
            raise ServiceError("Saved query sql_json is not an object", status_code=500)

        out = dict(row)
        out["sql_json"] = sj
        return out

    def _fetch_share_access(self, *, query_id: str) -> Dict[str, Any]:
        # Determine whether user has access to the query via ACL rows in this workspace.
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              MAX(CASE WHEN a.permission = 'WRITE' THEN 1 ELSE 0 END) AS can_edit,
              COUNT(1) AS n
            FROM saved_query_acl a
            WHERE a.saved_query_id = :qid
              AND a.workspace_id = :ws
              AND (
                (a.principal_type = 'WORKSPACE' AND a.principal_id = :ws)
                OR
                (a.principal_type = 'USER' AND a.principal_id = :uid)
              )
            """,
            {"qid": query_id, "ws": self._workspace_id, "uid": self._user_id},
        )
        row = rows[0] if rows else None

        if not row:
            return {"has_access": False, "can_edit": False}

        n = int(row.get("n") or 0)
        can_edit = bool(int(row.get("can_edit") or 0))
        return {"has_access": n > 0, "can_edit": can_edit}

    def fetch_recent_queries(self, *, limit: int = 20) -> Dict[str, Any]:
        """
        Returns a "recent" list for the left drawer.
        Includes queries the user can READ:
            - library (scope=LIBRARY, workspace_id IS NULL)
            - mine (owner in this workspace)
            - shared (ACL row for workspace or user in this workspace)

        Excludes deleted queries (is_deleted=0).
        Ordered by updated_at desc (fallback created_at).
        """
        try:
            lim = int(limit)
        except Exception:  # noqa: BLE001
            lim = 20
        if lim <= 0:
            lim = 20
        lim = min(lim, 200)

        # If workspace_id is None that's invalid per your ctor; but keep safe.
        ws = self._workspace_id
        uid = self._user_id

        rows = self._sql.execute_query_mappings(
            """
            SELECT
                q.id AS id,
                q.title AS title,
                q.updated_at AS updated_at,
                q.created_at AS created_at,
                q.scope AS scope,
                q.sql_json AS sql_json,
                q.folder_id AS folder_id
            FROM saved_query q
            WHERE q.is_deleted = 0
                AND (
                -- 1) Library (global)
                (q.scope = 'LIBRARY' AND q.workspace_id IS NULL)

                OR

                -- 2) Owner in this workspace (MINE)
                (q.workspace_id = :ws AND q.owner_user_id = :uid)

                OR

                -- 3) Shared to workspace or user in this workspace (via ACL)
                (
                    q.workspace_id = :ws
                    AND EXISTS (
                    SELECT 1
                    FROM saved_query_acl a
                    WHERE a.saved_query_id = q.id
                        AND a.workspace_id = :ws
                        AND (
                        (a.principal_type = 'WORKSPACE' AND a.principal_id = :ws)
                        OR
                        (a.principal_type = 'USER' AND a.principal_id = :uid)
                        )
                    )
                )
                )
            ORDER BY COALESCE(q.updated_at, q.created_at) DESC
            LIMIT :lim
            """,
            {"ws": ws, "uid": uid, "lim": lim},
        )

        def _iso(dt: Optional[datetime]) -> Optional[str]:
            return dt.isoformat() if dt else None

        # Shape matches your frontend RecentItem
        items: List[Dict[str, Any]] = []
        for r in rows:
            updated = r.get("updated_at") or r.get("created_at")
            items.append(
                {
                    "id": str(r["id"]),
                    "title": str(r["title"] or "Untitled"),
                    "updatedAt": _iso(updated),
                    "scope": str(r["scope"] or ""),
                    "queryType": self._tool_from_sql_json(r.get("sql_json")),
                    "folderId": (str(r["folder_id"]) if r.get("folder_id") else None),
                }
            )

        return {"rows": items}


def _to_payload(r: SavedQueryReadResult) -> Dict[str, Any]:
    return {
        "queryId": r.query_id,
        "workspaceId": r.workspace_id,
        "scope": r.scope,
        "ownerUserId": r.owner_user_id,
        "folderId": r.folder_id,
        "name": r.title,
        "description": r.description,
        "sqlJson": r.sql_json,
        "createdAt": r.created_at.isoformat() if r.created_at else None,
        "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
        "canEdit": bool(r.can_edit),
        "accessVia": r.access_via,
    }
