from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort


@dataclass(frozen=True)
class _ShareContext:
    workspace_id: str
    user_id: str


class _SavedQueryShareRepository:
    def __init__(self, *, ctx: _ShareContext, sql: ForgeQueryPort):
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


class SavedQueryShareService:
    """Share/unshare/list ACL records for saved queries."""

    def __init__(self, *, workspace_id: str, user_id: str, sql: Optional[ForgeQueryPort] = None):
        if not workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)
        if not user_id:
            raise ForgeError("user_id is required", status_code=400)

        self._ctx = _ShareContext(workspace_id=workspace_id, user_id=user_id)
        self._sql = sql or ForgeMetaSQL()
        self._repo = _SavedQueryShareRepository(ctx=self._ctx, sql=self._sql)
        self._ws = workspace_id

    def share_to_workspace(self, *, query_id: str, can_edit: bool = False) -> Dict[str, Any]:
        query_id = _req(query_id, "query_id")
        self._assert_query_owner(query_id)

        permission = "WRITE" if can_edit else "READ"
        acl = self._upsert_acl(
            saved_query_id=query_id,
            principal_type="WORKSPACE",
            principal_id=self._ctx.workspace_id,
            permission=permission,
        )
        return {
            "aclId": acl["id"],
            "queryId": query_id,
            "principalType": "WORKSPACE",
            "principalId": self._ctx.workspace_id,
            "permission": permission,
            "canEdit": permission == "WRITE",
        }

    def share_to_user(self, *, query_id: str, shared_with_user_id: str, can_edit: bool = False) -> Dict[str, Any]:
        query_id = _req(query_id, "query_id")
        shared_with_user_id = _req(shared_with_user_id, "shared_with_user_id")
        self._assert_query_owner(query_id)

        permission = "WRITE" if can_edit else "READ"
        acl = self._upsert_acl(
            saved_query_id=query_id,
            principal_type="USER",
            principal_id=shared_with_user_id,
            permission=permission,
        )
        return {
            "aclId": acl["id"],
            "queryId": query_id,
            "principalType": "USER",
            "principalId": shared_with_user_id,
            "permission": permission,
            "canEdit": permission == "WRITE",
        }

    def unshare(self, *, query_id: str, share_kind: str, shared_with_user_id: Optional[str] = None) -> Dict[str, Any]:
        query_id = _req(query_id, "query_id")
        share_kind = (share_kind or "").strip().upper()
        if share_kind not in ("WORKSPACE", "USER"):
            raise ForgeError("Invalid share_kind", status_code=400)

        self._assert_query_owner(query_id)

        if share_kind == "WORKSPACE":
            principal_type = "WORKSPACE"
            principal_id = self._ctx.workspace_id
        else:
            principal_type = "USER"
            principal_id = _req(shared_with_user_id, "shared_with_user_id")

        removed = self._repo.remove_acl(query_id=query_id, principal_type=principal_type, principal_id=principal_id)
        return {"queryId": query_id, "shareKind": share_kind, "removed": (removed or 0) > 0}

    def list_shares(self, *, query_id: str) -> Dict[str, Any]:
        query_id = _req(query_id, "query_id")
        self._assert_query_owner(query_id)

        rows = self._repo.list_query_shares(query_id=query_id)
        return {
            "queryId": query_id,
            "shares": [
                {
                    "aclId": row["id"],
                    "principalType": row["principal_type"],
                    "principalId": row["principal_id"],
                    "permission": row["permission"],
                    "canEdit": row["permission"] == "WRITE",
                    "createdAt": row["created_at"].isoformat() if row.get("created_at") else None,
                }
                for row in rows
            ],
        }

    def _assert_query_owner(self, query_id: str) -> None:
        if not self._repo.owned_query_exists(query_id=query_id):
            raise ForgeError("Saved query not found", status_code=404)

    def _upsert_acl(self, *, saved_query_id: str, principal_type: str, principal_id: str, permission: str) -> Dict[str, Any]:
        existing = self._find_acl(saved_query_id=saved_query_id, principal_type=principal_type, principal_id=principal_id)
        if existing:
            self._repo.update_acl_permission(acl_id=existing["id"], permission=permission)
            existing["permission"] = permission
            return existing

        acl_id = str(uuid.uuid4())
        self._repo.insert_acl(
            acl_id=acl_id,
            saved_query_id=saved_query_id,
            principal_type=principal_type,
            principal_id=principal_id,
            permission=permission,
        )
        return {"id": acl_id, "permission": permission}

    def _find_acl(self, *, saved_query_id: str, principal_type: str, principal_id: str) -> Optional[Dict[str, Any]]:
        return self._repo.fetch_acl(
            saved_query_id=saved_query_id,
            principal_type=principal_type,
            principal_id=principal_id,
        )


def _req(v: Any, field: str) -> str:
    value = str(v or "").strip()
    if not value:
        raise ForgeError(f"{field} is required", status_code=400)
    return value
