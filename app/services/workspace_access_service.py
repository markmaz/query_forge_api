from __future__ import annotations

from typing import Optional

from flask import g, has_request_context

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort


class WorkspaceAccessService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def user_has_workspace_access(self, *, user_id: str, workspace_id: str) -> bool:
        uid = str(user_id or "").strip()
        ws = str(workspace_id or "").strip()
        if not uid:
            raise ForgeError("Missing user identity", status_code=401)
        if not ws:
            raise ForgeError("Missing X-Workspace-Id header", status_code=400)

        rows = self._sql.execute_query(
            """
            SELECT 1
            FROM user_workspace_map
            WHERE user_id = :uid AND workspace_id = :ws
            LIMIT 1
            """,
            {"uid": uid, "ws": ws},
        )
        return bool(rows)

    def assert_workspace_access(self, *, user_id: str, workspace_id: str) -> str:
        uid = str(user_id or "").strip()
        ws = str(workspace_id or "").strip()
        if not uid:
            raise ForgeError("Missing user identity", status_code=401)
        if not ws:
            raise ForgeError("Missing X-Workspace-Id header", status_code=400)

        cache_key = (uid, ws)
        if has_request_context():
            cache = getattr(g, "_workspace_access_cache", None)
            if cache is None:
                cache = set()
                g._workspace_access_cache = cache
            if cache_key in cache:
                return ws

        if not self.user_has_workspace_access(user_id=uid, workspace_id=ws):
            raise ForgeError("You do not have access to this workspace", status_code=403)

        if has_request_context():
            cache = getattr(g, "_workspace_access_cache", None)
            if cache is None:
                cache = set()
                g._workspace_access_cache = cache
            cache.add(cache_key)
        return ws
