from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort


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
    can_edit: bool
    access_via: str


@dataclass(frozen=True)
class RecentQueryItem:
    id: str
    title: str
    updated_at: Optional[datetime]
    scope: str
    folder_id: Optional[str]


@dataclass(frozen=True)
class _ReadContext:
    workspace_id: str
    user_id: str
    is_admin: bool


class _SavedQueryReadRepository:
    def __init__(self, *, ctx: _ReadContext, sql: ForgeQueryPort):
        self._ctx = ctx
        self._sql = sql

    def fetch_query_row(self, *, query_id: str) -> Optional[Dict[str, Any]]:
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
        return dict(rows[0]) if rows else None

    def fetch_share_access(self, *, query_id: str) -> Dict[str, bool]:
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
            {"qid": query_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
        )

        row = rows[0] if rows else {}
        has_access = int((row or {}).get("n") or 0) > 0
        can_edit = int((row or {}).get("can_edit") or 0) > 0
        return {"has_access": has_access, "can_edit": can_edit}

    def fetch_recent(self, *, limit: int) -> List[Dict[str, Any]]:
        return self._sql.execute_query_mappings(
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
                (q.scope = 'LIBRARY' AND q.workspace_id IS NULL)
                OR
                (q.workspace_id = :ws AND q.owner_user_id = :uid)
                OR
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
            {"ws": self._ctx.workspace_id, "uid": self._ctx.user_id, "lim": limit},
        )


class SavedQueryReadService:
    def __init__(self, *, workspace_id: str, user_id: str, is_admin: bool = False, sql: Optional[ForgeQueryPort] = None):
        if not user_id:
            raise ForgeError("user_id is required", status_code=400)
        if workspace_id is None:
            raise ForgeError("workspace_id is required", status_code=400)

        self._ctx = _ReadContext(workspace_id=workspace_id, user_id=user_id, is_admin=bool(is_admin))
        self._sql = sql or ForgeMetaSQL()
        self._repo = _SavedQueryReadRepository(ctx=self._ctx, sql=self._sql)

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

    def get_query(self, query_id: str) -> Dict[str, Any]:
        query = self._fetch_query(query_id)
        is_library = query["scope"] == "LIBRARY" and query["workspace_id"] is None

        if is_library:
            return _to_payload(
                SavedQueryReadResult(
                    query_id=str(query["query_id"]),
                    workspace_id=None,
                    scope=str(query["scope"]),
                    owner_user_id=(str(query["owner_user_id"]) if query.get("owner_user_id") else None),
                    folder_id=(str(query["folder_id"]) if query.get("folder_id") else None),
                    title=str(query["title"]),
                    description=(str(query["description"]) if query.get("description") else None),
                    sql_json=query["sql_json"],
                    created_at=query.get("created_at"),
                    updated_at=query.get("updated_at"),
                    can_edit=self._ctx.is_admin,
                    access_via=("admin" if self._ctx.is_admin else "library"),
                )
            )

        if not self._ctx.workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)
        if str(query["workspace_id"]) != str(self._ctx.workspace_id):
            raise ForgeError("Query not found in this workspace", status_code=404)

        owner_user_id = str(query["owner_user_id"]) if query.get("owner_user_id") else None
        if owner_user_id == self._ctx.user_id:
            return _to_payload(
                SavedQueryReadResult(
                    query_id=str(query["query_id"]),
                    workspace_id=str(query["workspace_id"]),
                    scope=str(query["scope"]),
                    owner_user_id=owner_user_id,
                    folder_id=(str(query["folder_id"]) if query.get("folder_id") else None),
                    title=str(query["title"]),
                    description=(str(query["description"]) if query.get("description") else None),
                    sql_json=query["sql_json"],
                    created_at=query.get("created_at"),
                    updated_at=query.get("updated_at"),
                    can_edit=True,
                    access_via="owner",
                )
            )

        share_access = self._fetch_share_access(query_id=str(query["query_id"]))
        if not share_access["has_access"]:
            raise ForgeError("Saved query not found", status_code=404)

        return _to_payload(
            SavedQueryReadResult(
                query_id=str(query["query_id"]),
                workspace_id=str(query["workspace_id"]),
                scope=str(query["scope"]),
                owner_user_id=owner_user_id,
                folder_id=(str(query["folder_id"]) if query.get("folder_id") else None),
                title=str(query["title"]),
                description=(str(query["description"]) if query.get("description") else None),
                sql_json=query["sql_json"],
                created_at=query.get("created_at"),
                updated_at=query.get("updated_at"),
                can_edit=bool(share_access["can_edit"]),
                access_via="share",
            )
        )

    def _fetch_query(self, query_id: str) -> Dict[str, Any]:
        if not query_id or not isinstance(query_id, str):
            raise ForgeError("Invalid query_id", status_code=400)

        row = self._repo.fetch_query_row(query_id=query_id)
        if not row:
            raise ForgeError("Saved query not found", status_code=404)

        raw_sql_json = row.get("sql_json")
        if raw_sql_json is None:
            raise ForgeError("Saved query is missing sql_json", status_code=500)

        parsed = raw_sql_json
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except json.JSONDecodeError as exc:
                raise ForgeError("Saved query sql_json is invalid JSON", status_code=500) from exc

        if not isinstance(parsed, dict):
            raise ForgeError("Saved query sql_json is not an object", status_code=500)

        row["sql_json"] = parsed
        return row

    def _fetch_share_access(self, *, query_id: str) -> Dict[str, Any]:
        return self._repo.fetch_share_access(query_id=query_id)

    def fetch_recent_queries(self, *, limit: int = 20) -> Dict[str, Any]:
        try:
            candidate = int(limit)
        except Exception:  # noqa: BLE001
            candidate = 20

        if candidate <= 0:
            candidate = 20
        candidate = min(candidate, 200)

        rows = self._repo.fetch_recent(limit=candidate)
        payload_rows: List[Dict[str, Any]] = []
        for row in rows:
            updated = row.get("updated_at") or row.get("created_at")
            payload_rows.append(
                {
                    "id": str(row["id"]),
                    "title": str(row.get("title") or "Untitled"),
                    "updatedAt": updated.isoformat() if updated else None,
                    "scope": str(row.get("scope") or ""),
                    "queryType": self._tool_from_sql_json(row.get("sql_json")),
                    "folderId": (str(row["folder_id"]) if row.get("folder_id") else None),
                }
            )

        return {"rows": payload_rows}


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
