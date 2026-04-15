from __future__ import annotations

from typing import Any, Dict, Optional

from app.ports.sql_executor import ForgeQueryPort
from app.services.query_tree.saved_query_share_models import ShareContext


class SavedQueryShareRepository:
    def __init__(self, *, ctx: ShareContext, sql: ForgeQueryPort):
        self._ctx = ctx
        self._sql = sql

    def owned_query_exists(self, *, query_id: str) -> bool:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM saved_query
            WHERE id = :qid
              AND workspace_id = :ws
              AND scope = 'MINE'
              AND owner_user_id = :uid
              AND is_deleted = 0
            LIMIT 1
            """,
            {"qid": query_id, "ws": self._ctx.workspace_id, "uid": self._ctx.user_id},
        )
        return bool(rows)

    def fetch_acl(self, *, saved_query_id: str, principal_type: str, principal_id: str) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, permission
            FROM saved_query_acl
            WHERE saved_query_id = :qid
              AND workspace_id = :ws
              AND principal_type = :ptype
              AND principal_id = :pid
            LIMIT 1
            """,
            {
                "qid": saved_query_id,
                "ws": self._ctx.workspace_id,
                "ptype": principal_type,
                "pid": principal_id,
            },
        )
        return dict(rows[0]) if rows else None

    def update_acl_permission(self, *, acl_id: str, permission: str) -> None:
        with self._sql.transaction() as tx:
            tx.execute_write(
                """
                UPDATE saved_query_acl
                SET permission = :perm
                WHERE id = :id
                """,
                {"id": acl_id, "perm": permission},
            )

    def insert_acl(
        self,
        *,
        acl_id: str,
        saved_query_id: str,
        principal_type: str,
        principal_id: str,
        permission: str,
    ) -> None:
        with self._sql.transaction() as tx:
            tx.execute_write(
                """
                INSERT INTO saved_query_acl (
                  id, saved_query_id, workspace_id,
                  principal_type, principal_id, permission,
                  created_at
                )
                VALUES (
                  :id, :qid, :ws,
                  :ptype, :pid, :perm,
                  CURRENT_TIMESTAMP
                )
                """,
                {
                    "id": acl_id,
                    "qid": saved_query_id,
                    "ws": self._ctx.workspace_id,
                    "ptype": principal_type,
                    "pid": principal_id,
                    "perm": permission,
                },
            )

    def remove_acl(self, *, query_id: str, principal_type: str, principal_id: str) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                """
                DELETE FROM saved_query_acl
                WHERE saved_query_id = :qid
                  AND workspace_id = :ws
                  AND principal_type = :ptype
                  AND principal_id = :pid
                """,
                {
                    "qid": query_id,
                    "ws": self._ctx.workspace_id,
                    "ptype": principal_type,
                    "pid": principal_id,
                },
            )

    def list_query_shares(self, *, query_id: str) -> list[Dict[str, Any]]:
        return self._sql.execute_query_mappings(
            """
            SELECT id, principal_type, principal_id, permission, created_at
            FROM saved_query_acl
            WHERE saved_query_id = :qid
              AND workspace_id = :ws
            ORDER BY created_at ASC
            """,
            {"qid": query_id, "ws": self._ctx.workspace_id},
        )
