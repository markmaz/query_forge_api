from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

_ALLOWED_ROLES = {"user", "assistant", "system"}
_MAX_CONTENT_LEN = 8000
_MAX_TITLE_LEN = 255
_MAX_SUMMARY_LEN = 5000


class ForgeInsightsConversationStore:
    """Persistent conversation storage for ForgeInsights (MySQL source of truth)."""

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_messages(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
    ) -> Optional[List[Dict[str, str]]]:
        convo = self.get_conversation(
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if convo is None:
            return None
        return list(convo.get("messages") or [])

    def save_messages(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
        messages: Sequence[Mapping[str, Any]],
        qf_ttl_seconds: int,
    ) -> None:
        del qf_ttl_seconds
        existing = self.get_conversation(
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
        ) or {"title": None, "summary": ""}
        self.save_conversation(
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            conversation={
                "conversation_id": conversation_id,
                "messages": list(messages or []),
                "title": existing.get("title"),
                "summary": existing.get("summary"),
            },
            qf_ttl_seconds=0,
        )

    def get_conversation(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
    ) -> Optional[Dict[str, Any]]:
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        cid = _required_text(conversation_id, "conversation_id", max_len=128)
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              workspace_id,
              user_id,
              conversation_id,
              title,
              summary,
              message_count,
              created_at,
              updated_at,
              last_message_at
            FROM forge_insights_conversation
            WHERE workspace_id = :workspace_id
              AND user_id = :user_id
              AND conversation_id = :conversation_id
            LIMIT 1
            """,
            {"workspace_id": ws, "user_id": uid, "conversation_id": cid},
        )
        if not rows:
            return None
        row = rows[0]
        conversation_pk = int(row["id"])
        message_rows = self._sql.execute_query_mappings(
            """
            SELECT role, content
            FROM forge_insights_message
            WHERE conversation_pk = :conversation_pk
            ORDER BY seq_no ASC, id ASC
            """,
            {"conversation_pk": conversation_pk},
        )
        messages = _normalize_messages(message_rows)
        return {
            "conversation_id": str(row.get("conversation_id") or cid),
            "messages": messages,
            "summary": str(row.get("summary") or ""),
            "title": _optional_text(row.get("title"), max_len=_MAX_TITLE_LEN),
            "created_at": _dt_str(row.get("created_at")),
            "updated_at": _dt_str(row.get("updated_at")),
            "message_count": int(row.get("message_count") or len(messages)),
            "last_user_message": _last_user_message(messages),
            "last_message_at": _dt_str(row.get("last_message_at")),
        }

    def save_conversation(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
        conversation: Mapping[str, Any],
        qf_ttl_seconds: int,
    ) -> None:
        del qf_ttl_seconds
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        cid = _required_text(conversation_id, "conversation_id", max_len=128)

        messages = _normalize_messages(list(conversation.get("messages") or []))
        title = _optional_text(conversation.get("title"), max_len=_MAX_TITLE_LEN)
        summary = str(conversation.get("summary") or "")
        if len(summary) > _MAX_SUMMARY_LEN:
            summary = summary[:_MAX_SUMMARY_LEN]
        message_count = len(messages)

        with self._sql.transaction() as tx:
            inserted = tx.execute_insert(
                """
                INSERT INTO forge_insights_conversation (
                  workspace_id,
                  user_id,
                  conversation_id,
                  title,
                  summary,
                  message_count,
                  last_message_at
                ) VALUES (
                  :workspace_id,
                  :user_id,
                  :conversation_id,
                  :title,
                  :summary,
                  :message_count,
                  CURRENT_TIMESTAMP
                )
                ON DUPLICATE KEY UPDATE
                  id = LAST_INSERT_ID(id),
                  title = COALESCE(:title, title),
                  summary = :summary,
                  message_count = :message_count,
                  last_message_at = CURRENT_TIMESTAMP,
                  updated_at = CURRENT_TIMESTAMP
                """,
                {
                    "workspace_id": ws,
                    "user_id": uid,
                    "conversation_id": cid,
                    "title": title,
                    "summary": summary,
                    "message_count": message_count,
                },
            )
            conversation_pk = int(inserted.lastrowid or 0)
            if conversation_pk <= 0:
                id_rows = tx.execute_query_mappings(
                    """
                    SELECT id
                    FROM forge_insights_conversation
                    WHERE workspace_id = :workspace_id
                      AND user_id = :user_id
                      AND conversation_id = :conversation_id
                    LIMIT 1
                    """,
                    {"workspace_id": ws, "user_id": uid, "conversation_id": cid},
                )
                if not id_rows:
                    raise ForgeError("failed to resolve conversation row", status_code=500)
                conversation_pk = int(id_rows[0]["id"])

            tx.execute_write(
                "DELETE FROM forge_insights_message WHERE conversation_pk = :conversation_pk",
                {"conversation_pk": conversation_pk},
            )
            for idx, row in enumerate(messages, start=1):
                tx.execute_write(
                    """
                    INSERT INTO forge_insights_message (
                      conversation_pk,
                      seq_no,
                      role,
                      content
                    ) VALUES (
                      :conversation_pk,
                      :seq_no,
                      :role,
                      :content
                    )
                    """,
                    {
                        "conversation_pk": conversation_pk,
                        "seq_no": idx,
                        "role": row["role"],
                        "content": row["content"],
                    },
                )

    def list_conversations(
        self,
        *,
        workspace_id: str,
        user_id: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        safe_limit = max(1, min(int(limit), 200))
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              conversation_id,
              title,
              summary,
              message_count,
              created_at,
              updated_at,
              last_message_at
            FROM forge_insights_conversation
            WHERE workspace_id = :workspace_id
              AND user_id = :user_id
            ORDER BY COALESCE(last_message_at, updated_at) DESC, id DESC
            LIMIT :limit_value
            """,
            {"workspace_id": ws, "user_id": uid, "limit_value": safe_limit},
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            conversation_pk = int(row["id"])
            last_user = self._sql.execute_query_mappings(
                """
                SELECT content
                FROM forge_insights_message
                WHERE conversation_pk = :conversation_pk
                  AND role = 'user'
                ORDER BY seq_no DESC, id DESC
                LIMIT 1
                """,
                {"conversation_pk": conversation_pk},
            )
            out.append(
                {
                    "conversation_id": str(row.get("conversation_id") or ""),
                    "title": _optional_text(row.get("title"), max_len=_MAX_TITLE_LEN),
                    "last_user_message": _optional_text(
                        (last_user[0].get("content") if last_user else None),
                        max_len=240,
                    ),
                    "created_at": _dt_str(row.get("created_at")),
                    "updated_at": _dt_str(row.get("updated_at")),
                    "message_count": int(row.get("message_count") or 0),
                    "has_summary": bool(str(row.get("summary") or "").strip()),
                }
            )
        return out

    def delete_conversation(
        self,
        *,
        workspace_id: str,
        user_id: str,
        conversation_id: str,
    ) -> bool:
        ws = _required_text(workspace_id, "workspace_id", max_len=64)
        uid = _required_text(user_id, "user_id", max_len=255)
        cid = _required_text(conversation_id, "conversation_id", max_len=128)
        with self._sql.transaction() as tx:
            rows = tx.execute_query_mappings(
                """
                SELECT id
                FROM forge_insights_conversation
                WHERE workspace_id = :workspace_id
                  AND user_id = :user_id
                  AND conversation_id = :conversation_id
                LIMIT 1
                """,
                {"workspace_id": ws, "user_id": uid, "conversation_id": cid},
            )
            if not rows:
                return False
            deleted = tx.execute_write(
                "DELETE FROM forge_insights_conversation WHERE id = :id",
                {"id": int(rows[0]["id"])},
            )
            return bool(deleted)


def _required_text(value: Any, field_name: str, *, max_len: int) -> str:
    text = str(value or "").strip()
    if text == "":
        raise ForgeError(f"{field_name} is required", status_code=400)
    if len(text) > max_len:
        raise ForgeError(f"{field_name} must be {max_len} characters or fewer", status_code=400)
    return text


def _optional_text(value: Any, *, max_len: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    if len(text) > max_len:
        return text[:max_len]
    return text


def _normalize_messages(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in rows or []:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "")
        if role not in _ALLOWED_ROLES:
            continue
        if content.strip() == "":
            continue
        if len(content) > _MAX_CONTENT_LEN:
            content = content[:_MAX_CONTENT_LEN]
        out.append({"role": role, "content": content})
    return out


def _last_user_message(messages: Sequence[Mapping[str, Any]]) -> Optional[str]:
    for row in reversed(list(messages)):
        if str(row.get("role") or "").strip().lower() != "user":
            continue
        text = str(row.get("content") or "").strip()
        if text == "":
            continue
        if len(text) > 240:
            return f"{text[:240]}..."
        return text
    return None


def _dt_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    return text or None
