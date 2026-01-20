from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor
from app.services.domain_resolver import DomainResolver
from app.services.no_code_query_service import NoCodeQueryService
from app.services.query_tree.saved_query_folder_write_service import SavedQueryFolderWriteService
from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder


class SavedQueryWriteService:
    """
    Option B: Query write operations for Mine queries (scope='MINE').

    Trash semantics:
      - delete_query => soft delete (is_deleted=1 + deleted_at/deleted_by)
      - restore_query => undelete
      - purge_query => permanent delete (hard delete), ACL cascades via FK
    """

    def __init__(self, *, workspace_id: str, user_id: str, sql: Optional[SQLExecutor] = None):
        if not workspace_id:
            raise ServiceError("workspace_id is required", status_code=400)
        if not user_id:
            raise ServiceError("user_id is required", status_code=400)
        self._ws = workspace_id
        self._uid = user_id
        self._logger = logging.getLogger(__name__)
        self._sql = sql or MySQLSQLExecutor()

    def save_query(
        self,
        *,
        title: str,
        sql_json: Dict[str, Any],
        description: Optional[str] = None,
        folder_id: Optional[str] = None,
        query_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create or update a query owned by the current user (scope='MINE').
        """
        name = (title or "").strip()
        if not name:
            raise ServiceError("Title is required", status_code=400)
        if not isinstance(sql_json, dict):
            raise ServiceError("sql_json must be an object", status_code=400)

        fid = (str(folder_id).strip() or None) if folder_id is not None else None
        if fid:
            self._assert_folder_owner(fid)

        qid = (str(query_id).strip() or None) if query_id else None
        is_update = bool(qid)
        if not qid:
            qid = str(uuid.uuid4())

        try:
            sql_json_param = json.dumps(sql_json)
        except (TypeError, ValueError) as exc:  # noqa: BLE001
            raise ServiceError("sql_json must be JSON-serializable", status_code=400) from exc

        payload = {
            "qid": qid,
            "ws": self._ws,
            "uid": self._uid,
            "fid": fid,
            "title": name,
            "description": (description or None),
            "sql_json": sql_json_param,
        }

        if is_update:
            with self._sql.transaction() as tx:
                res = tx.execute_write(
                    """
                    UPDATE saved_query
                    SET title = :title,
                        description = :description,
                        sql_json = :sql_json,
                        folder_id = :fid,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :qid
                      AND workspace_id = :ws
                      AND scope = 'MINE'
                      AND owner_user_id = :uid
                      AND is_deleted = 0
                    """,
                    payload,
                )
                if (res or 0) == 0:
                    raise ServiceError("Saved query not found", status_code=404)
        else:
            with self._sql.transaction() as tx:
                tx.execute_write(
                    """
                    INSERT INTO saved_query (
                        id, workspace_id, scope, owner_user_id,
                        folder_id, title, description, sql_json,
                        is_deleted, created_at, updated_at
                    )
                    VALUES (
                        :qid, :ws, 'MINE', :uid,
                        :fid, :title, :description, :sql_json,
                        0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    payload,
                )

        self._create_cohort_view_if_needed(title=name, sql_json=sql_json)

        return {
            "queryId": qid,
            "workspaceId": self._ws,
            "scope": "MINE",
            "ownerUserId": self._uid,
            "folderId": fid,
            "name": name,
            "description": (description or None),
            "created": not is_update,
        }

    def _create_cohort_view_if_needed(self, *, title: str, sql_json: Dict[str, Any]) -> None:
        meta = (sql_json or {}).get("meta") if isinstance(sql_json, dict) else {}
        tool = (meta or {}).get("tool") if isinstance(meta, dict) else None
        if (tool or "").strip().lower() != "cohort_builder":
            return

        view_name = self._build_view_name(title)
        if not view_name:
            raise ServiceError("Invalid view name for cohort", status_code=400)

        ctx = WorkspaceContextBuilder().build(self._ws)
        domain_resolver = DomainResolver(workspace_id=self._ws)
        svc = NoCodeQueryService(executor=ctx.sql_exec, domain_resolver=domain_resolver)
        normalized = svc.normalize(sql_json)
        compiled = svc.compile(normalized, mode="export", limit=0, offset=0)
        rendered_sql = svc._render_sql_with_params(compiled.sql, compiled.params)

        view_sql = f"CREATE OR REPLACE VIEW workboard.{view_name} AS\n{rendered_sql}"
        self._logger.info("Creating cohort view: %s", view_name)
        ctx.sql_exec.submit_statement(view_sql, wait=True)

    def _build_view_name(self, title: str) -> str:
        def to_safe_slug(raw: str) -> str:
            s = re.sub(r"[^a-zA-Z0-9]+", "_", (raw or "").strip().lower())
            s = re.sub(r"_+", "_", s).strip("_")
            if s and s[0].isdigit():
                s = f"v_{s}"
            return s

        name_part = to_safe_slug(title)
        user_part = to_safe_slug(self._uid) or "user"
        if not name_part:
            return ""
        full = f"cohort_{name_part}_{user_part}"
        return full[:120]

    def delete_query(self, *, query_id: str) -> dict:
        qid = str(query_id or "").strip()
        if not qid:
            raise ServiceError("query_id is required", status_code=400)

        with self._sql.transaction() as tx:
            res = tx.execute_write(
                """
                UPDATE saved_query
                SET is_deleted = 1,
                    deleted_at = CURRENT_TIMESTAMP,
                    deleted_by_user_id = :uid,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :qid
                  AND workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 0
                """,
                {"qid": qid, "ws": self._ws, "uid": self._uid},
            )
            if (res or 0) == 0:
                raise ServiceError("Saved query not found", status_code=404)

        return {"queryId": qid, "deleted": True}


    def restore_query(self, *, query_id: str) -> dict:
        """
        Restores a trashed query.
        If its folder is deleted, restore the folder chain so the query returns to the same place.
        """
        qid = str(query_id or "").strip()
        if not qid:
            raise ServiceError("query_id is required", status_code=400)

        rows = self._sql.execute_query_mappings(
            """
            SELECT q.folder_id,
                q.is_deleted AS query_deleted,
                f.is_deleted AS folder_deleted
            FROM saved_query q
            LEFT JOIN saved_query_folder f ON f.id = q.folder_id
            WHERE q.id = :qid
            AND q.workspace_id = :ws
            AND q.scope = 'MINE'
            AND q.owner_user_id = :uid
            LIMIT 1
            """,
            {"qid": qid, "ws": self._ws, "uid": self._uid},
        )
        row = rows[0] if rows else None

        if not row:
            raise ServiceError("Saved query not found", status_code=404)

        folder_id = row["folder_id"]
        query_deleted = bool(row["query_deleted"]) if row["query_deleted"] is not None else False
        folder_deleted = bool(row["folder_deleted"]) if row["folder_deleted"] is not None else False

        if not query_deleted:
            # idempotent restore
            return {"queryId": qid, "restored": True, "folderId": (str(folder_id) if folder_id else None), "alreadyRestored": True}

        # If folder is deleted, restore folder chain/subtree first
        if folder_id and folder_deleted:
            SavedQueryFolderWriteService(workspace_id=self._ws, user_id=self._uid, sql=self._sql).restore_folder(
                folder_id=str(folder_id)
            )

        with self._sql.transaction() as tx:
            res = tx.execute_write(
                """
                UPDATE saved_query
                SET is_deleted = 0,
                    deleted_at = NULL,
                    deleted_by_user_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :qid
                AND workspace_id = :ws
                AND scope = 'MINE'
                AND owner_user_id = :uid
                AND is_deleted = 1
                """,
                {"qid": qid, "ws": self._ws, "uid": self._uid},
            )
            if (res or 0) == 0:
                raise ServiceError("Saved query not found in trash", status_code=404)

        return {"queryId": qid, "restored": True, "folderId": (str(folder_id) if folder_id else None)}

    def purge_query(self, *, query_id: str) -> dict:
        """
        Permanently deletes a query (hard delete). ACL rows cascade via FK.
        Only allowed for owner in MINE scope.
        """
        qid = str(query_id or "").strip()
        if not qid:
            raise ServiceError("query_id is required", status_code=400)

        with self._sql.transaction() as tx:
            res = tx.execute_write(
                """
                DELETE FROM saved_query
                WHERE id = :qid
                  AND workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 1
                """,
                {"qid": qid, "ws": self._ws, "uid": self._uid},
            )
            if (res or 0) == 0:
                raise ServiceError("Saved query not found", status_code=404)

        return {"queryId": qid, "purged": True}

    def move_query(self, *, query_id: str, folder_id: str | None) -> dict:
        qid = str(query_id or "").strip()
        if not qid:
            raise ServiceError("query_id is required", status_code=400)

        # folder_id can be None => move to root (under user root)
        if folder_id is not None:
            folder_id = str(folder_id).strip() or None
            if folder_id == f"user:{self._uid}":
                folder_id = None

        # Validate folder ownership if provided
        if folder_id:
            self._assert_folder_owner(folder_id)

        with self._sql.transaction() as tx:
            res = tx.execute_write(
                """
                UPDATE saved_query
                SET folder_id = :fid,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :qid
                  AND workspace_id = :ws
                  AND scope = 'MINE'
                  AND owner_user_id = :uid
                  AND is_deleted = 0
                """,
                {"qid": qid, "fid": folder_id, "ws": self._ws, "uid": self._uid},
            )
            if (res or 0) == 0:
                raise ServiceError("Saved query not found", status_code=404)

        return {"queryId": qid, "folderId": folder_id}

    def _assert_folder_owner(self, folder_id: str) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM saved_query_folder
            WHERE id = :fid
              AND workspace_id = :ws
              AND scope = 'MINE'
              AND owner_user_id = :uid
              AND is_deleted = 0
            LIMIT 1
            """,
            {"fid": folder_id, "ws": self._ws, "uid": self._uid},
        )
        row = rows[0] if rows else None
        if not row:
            raise ServiceError("Folder not found", status_code=404)
