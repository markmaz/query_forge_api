from __future__ import annotations

from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort

from app.repositories.feedback_learning._shared import parse_json_object, serialize_json_object


class PromptFailureAnalysisRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_by_id(self, *, analysis_id: int) -> Optional[Dict[str, Any]]:
        return self._fetch_one(where_sql="id = :analysis_id", params={"analysis_id": int(analysis_id)})

    def get_by_feedback_id(self, *, prompt_feedback_id: int) -> Optional[Dict[str, Any]]:
        return self._fetch_one(
            where_sql="prompt_feedback_id = :prompt_feedback_id",
            params={"prompt_feedback_id": int(prompt_feedback_id)},
        )

    def create_pending(
        self,
        *,
        prompt_feedback_id: int,
        evaluator_model: Optional[str] = None,
        evaluator_version: Optional[str] = None,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO prompt_failure_analysis (
              prompt_feedback_id,
              evaluator_model,
              evaluator_version,
              status
            ) VALUES (
              :prompt_feedback_id,
              :evaluator_model,
              :evaluator_version,
              'pending'
            )
            """,
            {
                "prompt_feedback_id": int(prompt_feedback_id),
                "evaluator_model": evaluator_model,
                "evaluator_version": evaluator_version,
            },
        )
        return int(result.lastrowid or 0)

    def mark_completed(
        self,
        *,
        analysis_id: int,
        failure_verdict: Optional[str],
        confidence: Optional[float],
        analysis_json: Optional[Dict[str, Any]],
        raw_llm_output: Optional[str],
    ) -> int:
        return int(
            self._sql.execute_write(
                """
                UPDATE prompt_failure_analysis
                SET status = 'completed',
                    failure_verdict = :failure_verdict,
                    confidence = :confidence,
                    analysis_json = :analysis_json,
                    raw_llm_output = :raw_llm_output,
                    error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """,
                {
                    "id": int(analysis_id),
                    "failure_verdict": failure_verdict,
                    "confidence": confidence,
                    "analysis_json": serialize_json_object(analysis_json),
                    "raw_llm_output": raw_llm_output,
                },
            )
            or 0
        )

    def mark_failed(
        self,
        *,
        analysis_id: int,
        error_message: str,
        raw_llm_output: Optional[str] = None,
    ) -> int:
        return int(
            self._sql.execute_write(
                """
                UPDATE prompt_failure_analysis
                SET status = 'failed',
                    error_message = :error_message,
                    raw_llm_output = COALESCE(:raw_llm_output, raw_llm_output),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """,
                {
                    "id": int(analysis_id),
                    "error_message": str(error_message or "").strip(),
                    "raw_llm_output": raw_llm_output,
                },
            )
            or 0
        )

    def _fetch_one(self, *, where_sql: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              id,
              prompt_feedback_id,
              evaluator_model,
              evaluator_version,
              status,
              failure_verdict,
              confidence,
              analysis_json,
              raw_llm_output,
              error_message,
              created_at,
              updated_at
            FROM prompt_failure_analysis
            WHERE {where_sql}
            LIMIT 1
            """,
            params,
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["analysis_json"] = parse_json_object(row.get("analysis_json"))
        return row


__all__ = ["PromptFailureAnalysisRepository"]
