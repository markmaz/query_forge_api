from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor

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


class PromptFeedbackService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None, max_payload_bytes: int = 2_000_000) -> None:
        self._sql = sql or MySQLSQLExecutor()
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
            raise ServiceError("workspace_id must be 64 characters or fewer", status_code=400)
        if len(uid) > 255:
            raise ServiceError("user_id must be 255 characters or fewer", status_code=400)

        vote_norm = _normalize_vote(vote)
        trace = _optional_text(trace_id)
        if trace is not None and len(trace) > 64:
            raise ServiceError("trace_id must be 64 characters or fewer", status_code=400)

        normalized_prompt_text = _optional_text(normalized_prompt)
        prompt_text_value = _optional_text(prompt_text)

        if not isinstance(response_json, dict):
            raise ServiceError("response_json must be an object", status_code=400)
        response_payload = _serialize_json(
            response_json,
            field_name="response_json",
            max_payload_bytes=self._max_payload_bytes,
        )

        meta_payload: Optional[str] = None
        if meta is not None:
            if not isinstance(meta, dict):
                raise ServiceError("meta must be an object", status_code=400)
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
                raise ServiceError("failed to persist prompt feedback", status_code=500)

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
            raise ServiceError("failed to load prompt feedback row", status_code=500)
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


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ServiceError(f"{field_name} is required", status_code=400)
    return text


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_vote(vote: Any) -> str:
    key = str(vote or "").strip().lower()
    if key not in _VOTE_ALIASES:
        raise ServiceError("vote must be one of: up, down, thumbs_up, thumbs_down", status_code=400)
    return _VOTE_ALIASES[key]


def _serialize_json(value: Dict[str, Any], *, field_name: str, max_payload_bytes: int) -> str:
    try:
        payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ServiceError(f"{field_name} must be JSON serializable", status_code=400) from exc
    payload_size = len(payload.encode("utf-8"))
    if payload_size > int(max_payload_bytes):
        raise ServiceError(
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
    raise ServiceError(f"invalid {field_name} value returned from database", status_code=500)
