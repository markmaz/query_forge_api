from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor


class SavedQueryShareService:
    """
    Option B (ACL-based) sharing.

    Writes rows to saved_query_acl:
      - principal_type: USER | WORKSPACE (ROLE optional later)
      - principal_id:  USER => user UUID (string), WORKSPACE => workspace_id (string)
      - permission: READ | WRITE

    Policy:
      - Only owner of a MINE query in this workspace can manage shares.
      - Sharing does not change saved_query.scope (stays MINE).
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
    # Share helpers (public)
    # -------------------------
    def share_to_workspace(self, *, query_id: str, can_edit: bool = False) -> Dict[str, Any]:
        qid = _req(query_id, "query_id")
        self._assert_query_owner(qid)

        principal_type = "WORKSPACE"
        principal_id = self._ws
        permission = "WRITE" if can_edit else "READ"

        acl = self._upsert_acl(saved_query_id=qid, principal_type=principal_type, principal_id=principal_id, permission=permission)
        return {
            "aclId": acl["id"],
            "queryId": qid,
            "principalType": principal_type,
            "principalId": principal_id,
            "permission": permission,
            "canEdit": (permission == "WRITE"),
        }

    def share_to_user(self, *, query_id: str, shared_with_user_id: str, can_edit: bool = False) -> Dict[str, Any]:
        qid = _req(query_id, "query_id")
        target = _req(shared_with_user_id, "shared_with_user_id")
        self._assert_query_owner(qid)

        principal_type = "USER"
        principal_id = target
        permission = "WRITE" if can_edit else "READ"

        acl = self._upsert_acl(saved_query_id=qid, principal_type=principal_type, principal_id=principal_id, permission=permission)
        return {
            "aclId": acl["id"],
            "queryId": qid,
            "principalType": principal_type,
            "principalId": principal_id,
            "permission": permission,
            "canEdit": (permission == "WRITE"),
        }

    def unshare(self, *, query_id: str, share_kind: str, shared_with_user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        share_kind: WORKSPACE | USER
        For USER, shared_with_user_id is required.
        """
        qid = _req(query_id, "query_id")
        kind = (share_kind or "").strip().upper()
        if kind not in ("WORKSPACE", "USER"):
            raise ServiceError("Invalid share_kind", status_code=400)

        self._assert_query_owner(qid)

        if kind == "WORKSPACE":
            principal_type = "WORKSPACE"
            principal_id = self._ws
        else:
            principal_type = "USER"
            principal_id = _req(shared_with_user_id, "shared_with_user_id")

        with self._sql.transaction() as tx:
            res = tx.execute_write(
                """
                DELETE FROM saved_query_acl
                WHERE saved_query_id = :qid
                  AND workspace_id = :ws
                  AND principal_type = :ptype
                  AND principal_id = :pid
                """,
                {"qid": qid, "ws": self._ws, "ptype": principal_type, "pid": principal_id},
            )

        return {"queryId": qid, "shareKind": kind, "removed": (res or 0) > 0}

    def list_shares(self, *, query_id: str) -> Dict[str, Any]:
        qid = _req(query_id, "query_id")
        self._assert_query_owner(qid)

        rows = self._sql.execute_query_mappings(
            """
            SELECT id, principal_type, principal_id, permission, created_at
            FROM saved_query_acl
            WHERE saved_query_id = :qid
              AND workspace_id = :ws
            ORDER BY created_at ASC
            """,
            {"qid": qid, "ws": self._ws},
        )

        return {
            "queryId": qid,
            "shares": [
                {
                    "aclId": r["id"],
                    "principalType": r["principal_type"],
                    "principalId": r["principal_id"],
                    "permission": r["permission"],
                    "canEdit": (r["permission"] == "WRITE"),
                    "createdAt": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ],
        }

    # -------------------------
    # Internal helpers
    # -------------------------
    def _assert_query_owner(self, query_id: str) -> None:
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
            {"qid": query_id, "ws": self._ws, "uid": self._uid},
        )
        if not rows:
            raise ServiceError("Saved query not found", status_code=404)

    def _upsert_acl(self, *, saved_query_id: str, principal_type: str, principal_id: str, permission: str) -> Dict[str, Any]:
        # Your DDL has uq_sqa_unique on (saved_query_id, principal_type, principal_id)
        existing = self._find_acl(saved_query_id=saved_query_id, principal_type=principal_type, principal_id=principal_id)
        if existing:
            with self._sql.transaction() as tx:
                tx.execute_write(
                    """
                    UPDATE saved_query_acl
                    SET permission = :perm
                    WHERE id = :id
                    """,
                    {"id": existing["id"], "perm": permission},
                )
            existing["permission"] = permission
            return existing

        acl_id = str(uuid.uuid4())
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
                    "ws": self._ws,
                    "ptype": principal_type,
                    "pid": principal_id,
                    "perm": permission,
                },
            )

        return {"id": acl_id, "permission": permission}

    def _find_acl(self, *, saved_query_id: str, principal_type: str, principal_id: str) -> Optional[Dict[str, Any]]:
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
            {"qid": saved_query_id, "ws": self._ws, "ptype": principal_type, "pid": principal_id},
        )
        row = rows[0] if rows else None
        return dict(row) if row else None


def _req(v: Any, field: str) -> str:
    s = str(v or "").strip()
    if not s:
        raise ServiceError(f"{field} is required", status_code=400)
    return s
