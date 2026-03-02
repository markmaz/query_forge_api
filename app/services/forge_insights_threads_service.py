from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor


class ForgeInsightsThreadsService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    # ---------- Projects ----------
    def create_project(
        self,
        *,
        workspace_id: str,
        user_id: str,
        name: str,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        project_name = _required_text(name, "name", max_len=255)
        project_description = _optional_text(description, max_len=10_000)

        with self._sql.transaction() as tx:
            inserted = tx.execute_insert(
                """
                INSERT INTO forge_insights_project (
                  workspace_id,
                  user_id,
                  name,
                  description
                ) VALUES (
                  :workspace_id,
                  :user_id,
                  :name,
                  :description
                )
                """,
                {
                    "workspace_id": ws,
                    "user_id": uid,
                    "name": project_name,
                    "description": project_description,
                },
            )
            project_id = int(inserted.lastrowid or 0)
            if project_id <= 0:
                raise ServiceError("failed to create forge insights project", status_code=500)
            return self._get_project_tx(tx=tx, workspace_id=ws, user_id=uid, project_id=project_id)

    def list_projects(
        self,
        *,
        workspace_id: str,
        user_id: str,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, workspace_id, user_id, name, description, is_archived, created_at, updated_at
            FROM forge_insights_project
            WHERE workspace_id = :workspace_id
              AND user_id = :user_id
              AND (:include_archived = 1 OR is_archived = 0)
            ORDER BY updated_at DESC, id DESC
            """,
            {"workspace_id": ws, "user_id": uid, "include_archived": 1 if include_archived else 0},
        )
        return [_normalize_project_row(r) for r in rows]

    def get_project(self, *, workspace_id: str, user_id: str, project_id: int) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        project_key = _required_int(project_id, "project_id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT id, workspace_id, user_id, name, description, is_archived, created_at, updated_at
            FROM forge_insights_project
            WHERE id = :project_id
              AND workspace_id = :workspace_id
              AND user_id = :user_id
            LIMIT 1
            """,
            {"project_id": project_key, "workspace_id": ws, "user_id": uid},
        )
        if not rows:
            raise ServiceError("ForgeInsights project not found", status_code=404)
        return _normalize_project_row(rows[0])

    def update_project(
        self,
        *,
        workspace_id: str,
        user_id: str,
        project_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_archived: Optional[bool] = None,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        project_key = _required_int(project_id, "project_id")
        patch_name = _optional_text(name, max_len=255)
        patch_description = _optional_text(description, max_len=10_000)
        patch_archived = _optional_bool(is_archived)

        if patch_name is None and description is None and patch_archived is None:
            raise ServiceError("no project fields supplied for update", status_code=400)

        with self._sql.transaction() as tx:
            self._assert_project_exists_tx(tx=tx, workspace_id=ws, user_id=uid, project_id=project_key)
            tx.execute_write(
                """
                UPDATE forge_insights_project
                SET name = COALESCE(:name, name),
                    description = CASE WHEN :description_set = 1 THEN :description ELSE description END,
                    is_archived = COALESCE(:is_archived, is_archived),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :project_id
                  AND workspace_id = :workspace_id
                  AND user_id = :user_id
                """,
                {
                    "project_id": project_key,
                    "workspace_id": ws,
                    "user_id": uid,
                    "name": patch_name,
                    "description": patch_description,
                    "description_set": 1 if description is not None else 0,
                    "is_archived": patch_archived,
                },
            )
            return self._get_project_tx(tx=tx, workspace_id=ws, user_id=uid, project_id=project_key)

    def delete_project(self, *, workspace_id: str, user_id: str, project_id: int) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        project_key = _required_int(project_id, "project_id")

        with self._sql.transaction() as tx:
            self._assert_project_exists_tx(tx=tx, workspace_id=ws, user_id=uid, project_id=project_key)
            tx.execute_write(
                """
                DELETE FROM forge_insights_project
                WHERE id = :project_id
                  AND workspace_id = :workspace_id
                  AND user_id = :user_id
                """,
                {"project_id": project_key, "workspace_id": ws, "user_id": uid},
            )
        return {"project_id": project_key, "deleted": True}

    # ---------- Threads ----------
    def create_thread(
        self,
        *,
        workspace_id: str,
        user_id: str,
        project_id: Optional[int] = None,
        conversation_id: Optional[str] = None,
        title: Optional[str] = None,
        preview_text: Optional[str] = None,
        is_pinned: bool = False,
        is_archived: bool = False,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        project_key = _optional_int(project_id, "project_id")
        conv_id = _optional_text(conversation_id, max_len=128) or _new_conversation_id()
        thread_title = _optional_text(title, max_len=255)
        thread_preview = _optional_text(preview_text, max_len=20_000)
        pinned = 1 if bool(is_pinned) else 0
        archived = 1 if bool(is_archived) else 0

        with self._sql.transaction() as tx:
            if project_key is not None:
                self._assert_project_exists_tx(tx=tx, workspace_id=ws, user_id=uid, project_id=project_key)
            inserted = tx.execute_insert(
                """
                INSERT INTO forge_insights_thread (
                  workspace_id,
                  user_id,
                  project_id,
                  conversation_id,
                  title,
                  preview_text,
                  is_pinned,
                  is_archived,
                  last_message_at
                ) VALUES (
                  :workspace_id,
                  :user_id,
                  :project_id,
                  :conversation_id,
                  :title,
                  :preview_text,
                  :is_pinned,
                  :is_archived,
                  CURRENT_TIMESTAMP
                )
                ON DUPLICATE KEY UPDATE
                  id = LAST_INSERT_ID(id),
                  project_id = VALUES(project_id),
                  title = COALESCE(VALUES(title), title),
                  preview_text = COALESCE(VALUES(preview_text), preview_text),
                  is_pinned = VALUES(is_pinned),
                  is_archived = VALUES(is_archived),
                  last_message_at = CURRENT_TIMESTAMP,
                  updated_at = CURRENT_TIMESTAMP
                """,
                {
                    "workspace_id": ws,
                    "user_id": uid,
                    "project_id": project_key,
                    "conversation_id": conv_id,
                    "title": thread_title,
                    "preview_text": thread_preview,
                    "is_pinned": pinned,
                    "is_archived": archived,
                },
            )
            thread_id = int(inserted.lastrowid or 0)
            if thread_id <= 0:
                # Fallback on duplicate-key path if lastrowid is unavailable.
                thread_id = self._get_thread_id_by_conversation_tx(
                    tx=tx,
                    workspace_id=ws,
                    user_id=uid,
                    conversation_id=conv_id,
                )
            return self._get_thread_tx(tx=tx, workspace_id=ws, user_id=uid, thread_id=thread_id)

    def list_threads(
        self,
        *,
        workspace_id: str,
        user_id: str,
        project_id: Optional[int] = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        project_key = _optional_int(project_id, "project_id")
        safe_limit = max(1, min(int(limit), 200))
        safe_offset = max(0, int(offset))
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              workspace_id,
              user_id,
              project_id,
              conversation_id,
              title,
              preview_text,
              is_pinned,
              is_archived,
              last_message_at,
              created_at,
              updated_at
            FROM forge_insights_thread
            WHERE workspace_id = :workspace_id
              AND user_id = :user_id
              AND (:project_filter_enabled = 0 OR project_id = :project_id)
              AND (:include_archived = 1 OR is_archived = 0)
            ORDER BY is_pinned DESC, COALESCE(last_message_at, updated_at) DESC, id DESC
            LIMIT :limit_value OFFSET :offset_value
            """,
            {
                "workspace_id": ws,
                "user_id": uid,
                "project_filter_enabled": 1 if project_key is not None else 0,
                "project_id": project_key,
                "include_archived": 1 if include_archived else 0,
                "limit_value": safe_limit,
                "offset_value": safe_offset,
            },
        )
        return [_normalize_thread_row(r) for r in rows]

    def get_thread(self, *, workspace_id: str, user_id: str, thread_id: int) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        thread_key = _required_int(thread_id, "thread_id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              workspace_id,
              user_id,
              project_id,
              conversation_id,
              title,
              preview_text,
              is_pinned,
              is_archived,
              last_message_at,
              created_at,
              updated_at
            FROM forge_insights_thread
            WHERE id = :thread_id
              AND workspace_id = :workspace_id
              AND user_id = :user_id
            LIMIT 1
            """,
            {"thread_id": thread_key, "workspace_id": ws, "user_id": uid},
        )
        if not rows:
            raise ServiceError("ForgeInsights thread not found", status_code=404)
        return _normalize_thread_row(rows[0])

    def update_thread(
        self,
        *,
        workspace_id: str,
        user_id: str,
        thread_id: int,
        project_id: Optional[int] = None,
        title: Optional[str] = None,
        preview_text: Optional[str] = None,
        is_pinned: Optional[bool] = None,
        is_archived: Optional[bool] = None,
        last_message_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        thread_key = _required_int(thread_id, "thread_id")
        project_key = _optional_int(project_id, "project_id")
        patch_title = _optional_text(title, max_len=255)
        patch_preview = _optional_text(preview_text, max_len=20_000)
        patch_pinned = _optional_bool(is_pinned)
        patch_archived = _optional_bool(is_archived)
        if (
            project_id is None
            and title is None
            and preview_text is None
            and patch_pinned is None
            and patch_archived is None
            and last_message_at is None
        ):
            raise ServiceError("no thread fields supplied for update", status_code=400)

        if project_key is not None:
            # project_id=0 is invalid and already rejected; NULL project unlink is supported via project_id=None+project_set=1
            pass

        with self._sql.transaction() as tx:
            self._assert_thread_exists_tx(tx=tx, workspace_id=ws, user_id=uid, thread_id=thread_key)
            if project_id is not None and project_key is not None:
                self._assert_project_exists_tx(tx=tx, workspace_id=ws, user_id=uid, project_id=project_key)

            tx.execute_write(
                """
                UPDATE forge_insights_thread
                SET project_id = CASE WHEN :project_set = 1 THEN :project_id ELSE project_id END,
                    title = CASE WHEN :title_set = 1 THEN :title ELSE title END,
                    preview_text = CASE WHEN :preview_set = 1 THEN :preview_text ELSE preview_text END,
                    is_pinned = COALESCE(:is_pinned, is_pinned),
                    is_archived = COALESCE(:is_archived, is_archived),
                    last_message_at = COALESCE(:last_message_at, last_message_at),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :thread_id
                  AND workspace_id = :workspace_id
                  AND user_id = :user_id
                """,
                {
                    "thread_id": thread_key,
                    "workspace_id": ws,
                    "user_id": uid,
                    "project_set": 1 if project_id is not None else 0,
                    "project_id": project_key,
                    "title_set": 1 if title is not None else 0,
                    "title": patch_title,
                    "preview_set": 1 if preview_text is not None else 0,
                    "preview_text": patch_preview,
                    "is_pinned": patch_pinned,
                    "is_archived": patch_archived,
                    "last_message_at": last_message_at,
                },
            )
            return self._get_thread_tx(tx=tx, workspace_id=ws, user_id=uid, thread_id=thread_key)

    def delete_thread(self, *, workspace_id: str, user_id: str, thread_id: int) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        thread_key = _required_int(thread_id, "thread_id")
        with self._sql.transaction() as tx:
            self._assert_thread_exists_tx(tx=tx, workspace_id=ws, user_id=uid, thread_id=thread_key)
            tx.execute_write(
                """
                DELETE FROM forge_insights_thread
                WHERE id = :thread_id
                  AND workspace_id = :workspace_id
                  AND user_id = :user_id
                """,
                {"thread_id": thread_key, "workspace_id": ws, "user_id": uid},
            )
        return {"thread_id": thread_key, "deleted": True}

    # ---------- TX helpers ----------
    def _assert_project_exists_tx(self, *, tx: Any, workspace_id: str, user_id: str, project_id: int) -> None:
        rows = tx.execute_query_mappings(
            """
            SELECT id
            FROM forge_insights_project
            WHERE id = :project_id
              AND workspace_id = :workspace_id
              AND user_id = :user_id
            LIMIT 1
            """,
            {"project_id": project_id, "workspace_id": workspace_id, "user_id": user_id},
        )
        if not rows:
            raise ServiceError("ForgeInsights project not found", status_code=404)

    def _assert_thread_exists_tx(self, *, tx: Any, workspace_id: str, user_id: str, thread_id: int) -> None:
        rows = tx.execute_query_mappings(
            """
            SELECT id
            FROM forge_insights_thread
            WHERE id = :thread_id
              AND workspace_id = :workspace_id
              AND user_id = :user_id
            LIMIT 1
            """,
            {"thread_id": thread_id, "workspace_id": workspace_id, "user_id": user_id},
        )
        if not rows:
            raise ServiceError("ForgeInsights thread not found", status_code=404)

    def _get_thread_tx(self, *, tx: Any, workspace_id: str, user_id: str, thread_id: int) -> Dict[str, Any]:
        rows = tx.execute_query_mappings(
            """
            SELECT
              id,
              workspace_id,
              user_id,
              project_id,
              conversation_id,
              title,
              preview_text,
              is_pinned,
              is_archived,
              last_message_at,
              created_at,
              updated_at
            FROM forge_insights_thread
            WHERE id = :thread_id
              AND workspace_id = :workspace_id
              AND user_id = :user_id
            LIMIT 1
            """,
            {"thread_id": thread_id, "workspace_id": workspace_id, "user_id": user_id},
        )
        if not rows:
            raise ServiceError("failed to load forge insights thread row", status_code=500)
        return _normalize_thread_row(rows[0])

    def _get_project_tx(self, *, tx: Any, workspace_id: str, user_id: str, project_id: int) -> Dict[str, Any]:
        rows = tx.execute_query_mappings(
            """
            SELECT id, workspace_id, user_id, name, description, is_archived, created_at, updated_at
            FROM forge_insights_project
            WHERE id = :project_id
              AND workspace_id = :workspace_id
              AND user_id = :user_id
            LIMIT 1
            """,
            {"project_id": project_id, "workspace_id": workspace_id, "user_id": user_id},
        )
        if not rows:
            raise ServiceError("failed to load forge insights project row", status_code=500)
        return _normalize_project_row(rows[0])

    def _get_thread_id_by_conversation_tx(
        self,
        *,
        tx: Any,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
    ) -> int:
        rows = tx.execute_query_mappings(
            """
            SELECT id
            FROM forge_insights_thread
            WHERE workspace_id = :workspace_id
              AND user_id = :user_id
              AND conversation_id = :conversation_id
            LIMIT 1
            """,
            {"workspace_id": workspace_id, "user_id": user_id, "conversation_id": conversation_id},
        )
        if not rows:
            raise ServiceError("failed to resolve forge insights thread id", status_code=500)
        return int(rows[0]["id"])


def _new_conversation_id() -> str:
    return f"fi_{uuid.uuid4().hex}"


def _required_text(value: Any, field_name: str, *, max_len: int) -> str:
    text = str(value or "").strip()
    if text == "":
        raise ServiceError(f"{field_name} is required", status_code=400)
    if len(text) > max_len:
        raise ServiceError(f"{field_name} must be {max_len} characters or fewer", status_code=400)
    return text


def _optional_text(value: Any, *, max_len: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    if len(text) > max_len:
        raise ServiceError(f"value must be {max_len} characters or fewer", status_code=400)
    return text


def _required_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except Exception as exc:
        raise ServiceError(f"{field_name} must be an integer", status_code=400) from exc
    if parsed <= 0:
        raise ServiceError(f"{field_name} must be > 0", status_code=400)
    return parsed


def _optional_int(value: Any, field_name: str) -> Optional[int]:
    if value is None:
        return None
    return _required_int(value, field_name)


def _optional_bool(value: Any) -> Optional[int]:
    if value is None:
        return None
    return 1 if bool(value) else 0


def _normalize_project_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "workspace_id": str(row["workspace_id"]),
        "user_id": str(row["user_id"]),
        "name": str(row["name"]),
        "description": row.get("description"),
        "is_archived": bool(int(row.get("is_archived") or 0)),
        "created_at": _coerce_datetime(row.get("created_at"), "created_at"),
        "updated_at": _coerce_datetime(row.get("updated_at"), "updated_at"),
    }


def _normalize_thread_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "workspace_id": str(row["workspace_id"]),
        "user_id": str(row["user_id"]),
        "project_id": (int(row["project_id"]) if row.get("project_id") is not None else None),
        "conversation_id": str(row["conversation_id"]),
        "title": row.get("title"),
        "preview_text": row.get("preview_text"),
        "is_pinned": bool(int(row.get("is_pinned") or 0)),
        "is_archived": bool(int(row.get("is_archived") or 0)),
        "last_message_at": (
            _coerce_datetime(row.get("last_message_at"), "last_message_at")
            if row.get("last_message_at") is not None
            else None
        ),
        "created_at": _coerce_datetime(row.get("created_at"), "created_at"),
        "updated_at": _coerce_datetime(row.get("updated_at"), "updated_at"),
    }


def _coerce_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    raise ServiceError(f"invalid {field_name} value returned from database", status_code=500)
