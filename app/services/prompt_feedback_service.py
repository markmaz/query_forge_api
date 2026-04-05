from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

_VOTE_ALIASES = {
    "up": "up",
    "thumbs_up": "up",
    "down": "down",
    "thumbs_down": "down",
}


@dataclass(frozen=True)
class PromptFeedbackWriteResult:
    id: int
    vote: str
    created_at: datetime
    updated_at: datetime
    created: bool


@dataclass(frozen=True)
class PromptFeedbackDeleteResult:
    id: int
    deleted: bool


class PromptFeedbackService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, max_payload_bytes: int = 2_000_000) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._max_payload_bytes = int(max_payload_bytes)

    def save_feedback(
        self,
        *,
        workspace_id: str,
        user_id: str,
        vote: str,
        response_json: Dict[str, Any],
        trace_id: Optional[str] = None,
        normalized_prompt: Optional[str] = None,
        prompt_text: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PromptFeedbackWriteResult:
        ws = _required_text(workspace_id, "workspace_id")
        uid = _required_text(user_id, "user_id")
        if len(ws) > 64:
            raise ForgeError("workspace_id must be 64 characters or fewer", status_code=400)
        if len(uid) > 255:
            raise ForgeError("user_id must be 255 characters or fewer", status_code=400)

        vote_norm = _normalize_vote(vote)
        trace = _optional_text(trace_id)
        if trace is not None and len(trace) > 64:
            raise ForgeError("trace_id must be 64 characters or fewer", status_code=400)

        normalized_prompt_text = _optional_text(normalized_prompt)
        prompt_text_value = _optional_text(prompt_text)

        if not isinstance(response_json, dict):
            raise ForgeError("response_json must be an object", status_code=400)
        response_payload = _serialize_json(
            response_json,
            field_name="response_json",
            max_payload_bytes=self._max_payload_bytes,
        )

        meta_payload: Optional[str] = None
        if meta is not None:
            if not isinstance(meta, dict):
                raise ForgeError("meta must be an object", status_code=400)
            meta_payload = _serialize_json(
                meta,
                field_name="meta",
                max_payload_bytes=self._max_payload_bytes,
            )

        params = {
            "workspace_id": ws,
            "user_id": uid,
            "trace_id": trace,
            "vote": vote_norm,
            "normalized_prompt": normalized_prompt_text,
            "prompt_text": prompt_text_value,
            "response_json": response_payload,
            "meta_json": meta_payload,
        }

        with self._sql.transaction() as tx:
            created = True
            existing_id: Optional[int] = None

            if trace is not None:
                existing_rows = tx.execute_query_mappings(
                    """
                    SELECT id
                    FROM prompt_feedback
                    WHERE workspace_id = :workspace_id
                      AND user_id = :user_id
                      AND trace_id = :trace_id
                    LIMIT 1
                    """,
                    {"workspace_id": ws, "user_id": uid, "trace_id": trace},
                )
                if existing_rows:
                    created = False
                    existing_id = int(existing_rows[0]["id"])

                write_result = tx.execute_insert(
                    """
                    INSERT INTO prompt_feedback (
                      workspace_id,
                      user_id,
                      trace_id,
                      vote,
                      normalized_prompt,
                      prompt_text,
                      response_json,
                      meta_json
                    ) VALUES (
                      :workspace_id,
                      :user_id,
                      :trace_id,
                      :vote,
                      :normalized_prompt,
                      :prompt_text,
                      :response_json,
                      :meta_json
                    )
                    ON DUPLICATE KEY UPDATE
                      id = LAST_INSERT_ID(id),
                      vote = VALUES(vote),
                      normalized_prompt = VALUES(normalized_prompt),
                      prompt_text = VALUES(prompt_text),
                      response_json = VALUES(response_json),
                      meta_json = VALUES(meta_json),
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    params,
                )
            else:
                write_result = tx.execute_insert(
                    """
                    INSERT INTO prompt_feedback (
                      workspace_id,
                      user_id,
                      trace_id,
                      vote,
                      normalized_prompt,
                      prompt_text,
                      response_json,
                      meta_json
                    ) VALUES (
                      :workspace_id,
                      :user_id,
                      :trace_id,
                      :vote,
                      :normalized_prompt,
                      :prompt_text,
                      :response_json,
                      :meta_json
                    )
                    """,
                    params,
                )

            feedback_id = int(write_result.lastrowid or 0)
            if feedback_id <= 0 and existing_id is not None:
                feedback_id = existing_id
            if feedback_id <= 0:
                raise ForgeError("failed to persist prompt feedback", status_code=500)

            rows = tx.execute_query_mappings(
                """
                SELECT id, vote, created_at, updated_at
                FROM prompt_feedback
                WHERE id = :id
                LIMIT 1
                """,
                {"id": feedback_id},
            )

        if not rows:
            raise ForgeError("failed to load prompt feedback row", status_code=500)
        row = rows[0]
        return PromptFeedbackWriteResult(
            id=int(row["id"]),
            vote=str(row["vote"]),
            created_at=_coerce_datetime(row.get("created_at"), field_name="created_at"),
            updated_at=_coerce_datetime(row.get("updated_at"), field_name="updated_at"),
            created=created,
        )

    def get_vote_aggregation(self, *, workspace_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        del user_id
        ws = _required_text(workspace_id, "workspace_id")
        return {"workspace_id": ws, "rows": []}

    def list_feedback(
        self,
        *,
        workspace_id: str,
        limit: int = 100,
        offset: int = 0,
        vote: Optional[str] = None,
        user_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        include_payload: bool = False,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        page_limit = max(1, min(int(limit or 100), 500))
        page_offset = max(0, int(offset or 0))

        where_parts = ["workspace_id = :workspace_id"]
        params: Dict[str, Any] = {"workspace_id": ws, "limit": page_limit, "offset": page_offset}

        vote_text = _optional_text(vote)
        if vote_text:
            params["vote"] = _normalize_vote(vote_text)
            where_parts.append("vote = :vote")

        user_text = _optional_text(user_id)
        if user_text:
            params["user_id"] = user_text
            where_parts.append("user_id = :user_id")

        trace_text = _optional_text(trace_id)
        if trace_text:
            params["trace_id"] = trace_text
            where_parts.append("trace_id = :trace_id")

        where_clause = " AND ".join(where_parts)
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT id, workspace_id, user_id, trace_id, vote, normalized_prompt, prompt_text,
                   response_json, meta_json, created_at, updated_at
            FROM prompt_feedback
            WHERE {where_clause}
            ORDER BY created_at DESC, id DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        count_rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM prompt_feedback
            WHERE {where_clause}
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        total = int((count_rows[0] or {}).get("total") or 0) if count_rows else 0

        out_rows = []
        for row in rows:
            item = dict(row)
            item["created_at"] = _coerce_datetime(item.get("created_at"), field_name="created_at").isoformat()
            item["updated_at"] = _coerce_datetime(item.get("updated_at"), field_name="updated_at").isoformat()
            if include_payload:
                item["response_json"] = _coerce_json(item.get("response_json"))
                item["meta_json"] = _coerce_json(item.get("meta_json"))
            else:
                item.pop("response_json", None)
                item.pop("meta_json", None)
            out_rows.append(item)

        return {
            "rows": out_rows,
            "count": len(out_rows),
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
        }

    def delete_feedback(self, *, workspace_id: str, feedback_id: int) -> PromptFeedbackDeleteResult:
        ws = _required_text(workspace_id, "workspace_id")
        try:
            fid = int(feedback_id)
        except Exception as exc:
            raise ForgeError("feedback_id must be an integer", status_code=400) from exc
        if fid <= 0:
            raise ForgeError("feedback_id must be greater than 0", status_code=400)

        with self._sql.transaction() as tx:
            deleted = int(
                tx.execute_write(
                    """
                    DELETE FROM prompt_feedback
                    WHERE id = :id
                      AND workspace_id = :workspace_id
                    LIMIT 1
                    """,
                    {"id": fid, "workspace_id": ws},
                )
                or 0
            )
        if deleted <= 0:
            raise ForgeError("Prompt feedback record not found", status_code=404)

        return PromptFeedbackDeleteResult(id=fid, deleted=True)


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ForgeError(f"{field_name} is required", status_code=400)
    return text


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_vote(vote: Any) -> str:
    key = str(vote or "").strip().lower()
    if key not in _VOTE_ALIASES:
        raise ForgeError("vote must be one of: up, down, thumbs_up, thumbs_down", status_code=400)
    return _VOTE_ALIASES[key]


def _serialize_json(value: Dict[str, Any], *, field_name: str, max_payload_bytes: int) -> str:
    try:
        payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ForgeError(f"{field_name} must be JSON serializable", status_code=400) from exc
    payload_size = len(payload.encode("utf-8"))
    if payload_size > int(max_payload_bytes):
        raise ForgeError(
            f"{field_name} exceeds max size of {int(max_payload_bytes)} bytes",
            status_code=413,
        )
    return payload


def _coerce_datetime(value: Any, *, field_name: str) -> datetime:
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
    raise ForgeError(f"invalid {field_name} value returned from database", status_code=500)


def _coerce_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except (TypeError, ValueError, json.JSONDecodeError):
            return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            return json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"_raw": text}
    return value
