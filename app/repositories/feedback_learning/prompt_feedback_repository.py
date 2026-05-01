from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort

from app.repositories.feedback_learning._shared import parse_json_object


class PromptFeedbackRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_feedback(self, *, prompt_feedback_id: int) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              workspace_id,
              user_id,
              trace_id,
              vote,
              normalized_prompt,
              prompt_text,
              response_json,
              meta_json,
              created_at,
              updated_at
            FROM prompt_feedback
            WHERE id = :id
            LIMIT 1
            """,
            {"id": int(prompt_feedback_id)},
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["response_json"] = parse_json_object(row.get("response_json"))
        row["meta_json"] = parse_json_object(row.get("meta_json"))
        return row

    def feedback_exists(self, *, prompt_feedback_id: int) -> bool:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM prompt_feedback
            WHERE id = :id
            LIMIT 1
            """,
            {"id": int(prompt_feedback_id)},
        )
        return bool(rows)

    def list_negative_feedback_without_analysis(
        self,
        *,
        limit: Optional[int] = None,
        workspace_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        where_parts = [
            "pf.vote = 'down'",
            "pfa.id IS NULL",
        ]
        params: Dict[str, Any] = {}
        if workspace_id is not None and str(workspace_id).strip():
            params["workspace_id"] = str(workspace_id).strip()
            where_parts.append("pf.workspace_id = :workspace_id")
        if date_from is not None and str(date_from).strip():
            params["date_from"] = str(date_from).strip()
            where_parts.append("pf.created_at >= :date_from")
        if date_to is not None and str(date_to).strip():
            params["date_to"] = str(date_to).strip()
            where_parts.append("pf.created_at <= :date_to")
        limit_value = max(1, int(limit or 500))
        params["limit"] = limit_value

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              pf.id,
              pf.workspace_id,
              pf.user_id,
              pf.trace_id,
              pf.vote,
              pf.normalized_prompt,
              pf.prompt_text,
              pf.response_json,
              pf.meta_json,
              pf.created_at,
              pf.updated_at
            FROM prompt_feedback pf
            LEFT JOIN prompt_failure_analysis pfa
              ON pfa.prompt_feedback_id = pf.id
            WHERE {' AND '.join(where_parts)}
            ORDER BY pf.created_at ASC, pf.id ASC
            LIMIT :limit
            """,
            params,
        )
        out: List[Dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            row["response_json"] = parse_json_object(row.get("response_json"))
            row["meta_json"] = parse_json_object(row.get("meta_json"))
            out.append(row)
        return out


__all__ = ["PromptFeedbackRepository"]
