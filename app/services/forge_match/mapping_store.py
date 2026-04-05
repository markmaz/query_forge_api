from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional, Sequence, Set

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.forge_match.session_reader import ForgeMatchSessionReader


class ForgeMatchMappingStore:
    def __init__(
        self,
        *,
        sql: ForgeQueryPort,
        session_reader: ForgeMatchSessionReader,
        allowed_result_statuses: Optional[Set[str]] = None,
    ) -> None:
        self._sql = sql
        self._session_reader = session_reader
        self._allowed_result_statuses = set(allowed_result_statuses or set())

    def patch_mappings(
        self,
        *,
        workspace_id: str,
        session_id: str,
        reviewer_user_id: str,
        updates: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        self._session_reader.get_session_row(workspace_id=workspace_id, session_id=session_id)

        changed: list[dict[str, Any]] = []
        for update in updates:
            mapping_id = _required_text(update.get("mapping_id"), "mapping_id")
            row = self.get_mapping_row_by_id(
                workspace_id=workspace_id,
                session_id=session_id,
                mapping_id=mapping_id,
            )
            if not row:
                raise ForgeError(f"mapping_id not found: {mapping_id}", status_code=404)

            action = _to_text_or_none(update.get("action"))
            status = update.get("status")
            manual_col = update.get("manually_selected_workspace_column_id")
            notes = update.get("review_notes")

            if action:
                action_norm = action.lower()
                if action_norm == "accept":
                    status = "accepted"
                elif action_norm == "reject":
                    status = "rejected"
                elif action_norm == "needs_review":
                    status = "needs_review"
                elif action_norm == "remap":
                    status = "manually_mapped"
                elif action_norm == "edit_notes":
                    pass
                else:
                    raise ForgeError(f"Invalid action: {action}", status_code=400)

            if status is not None:
                status = str(status).strip().lower()
                if status not in self._allowed_result_statuses:
                    raise ForgeError(f"Invalid status: {status}", status_code=400)

            manual_col_id = None
            if manual_col is not None:
                try:
                    manual_col_id = int(manual_col)
                except Exception as exc:
                    raise ForgeError("manually_selected_workspace_column_id must be integer", status_code=400) from exc
                if manual_col_id <= 0:
                    raise ForgeError("manually_selected_workspace_column_id must be > 0", status_code=400)
                self.assert_workspace_column(workspace_id=workspace_id, workspace_column_id=manual_col_id)
                if status is None:
                    status = "manually_mapped"
            elif action and action.lower() == "remap":
                raise ForgeError("remap action requires manually_selected_workspace_column_id", status_code=400)

            if status is None and notes is None and manual_col is None:
                continue

            params: Dict[str, Any] = {
                "id": mapping_id,
                "session_id": session_id,
                "reviewer_user_id": reviewer_user_id,
            }
            set_parts = [
                "reviewer_user_id = :reviewer_user_id",
                "reviewed_at = CURRENT_TIMESTAMP",
                "updated_at = CURRENT_TIMESTAMP",
            ]

            if status is not None:
                set_parts.append("status = :status")
                params["status"] = status
            if manual_col is not None:
                set_parts.append("manually_selected_workspace_column_id = :manually_selected_workspace_column_id")
                params["manually_selected_workspace_column_id"] = manual_col_id
            if notes is not None:
                set_parts.append("review_notes = :review_notes")
                params["review_notes"] = str(notes)

            self._sql.execute_write(
                f"""
                UPDATE forge_match_result
                SET {', '.join(set_parts)}
                WHERE id = :id
                  AND session_id = :session_id
                """,
                params,
            )
            changed.append({"mapping_id": mapping_id, "status": status, "manual_column_id": manual_col_id})

        return {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "updated": len(changed),
            "rows": changed,
        }

    def upsert_mapping_result(
        self,
        *,
        session_id: str,
        source_record_id: int,
        selected: Optional[Dict[str, Any]],
        alternates: Sequence[Dict[str, Any]],
        candidates: Sequence[Dict[str, Any]],
        llm_rank: Dict[str, Any],
        confidence: Dict[str, Any],
    ) -> None:
        mapping_id = str(uuid.uuid4())
        self._sql.execute_insert(
            """
            INSERT INTO forge_match_result (
              id,
              session_id,
              source_record_id,
              best_match_workspace_column_id,
              alternate_workspace_column_ids,
              retrieved_candidates_json,
              llm_response_json,
              match_decision,
              reason_codes_json,
              explanation,
              ambiguity_note,
              llm_confidence,
              confidence_score,
              confidence_band,
              status
            ) VALUES (
              :id,
              :session_id,
              :source_record_id,
              :best_match_workspace_column_id,
              :alternate_workspace_column_ids,
              :retrieved_candidates_json,
              :llm_response_json,
              :match_decision,
              :reason_codes_json,
              :explanation,
              :ambiguity_note,
              :llm_confidence,
              :confidence_score,
              :confidence_band,
              :status
            )
            ON DUPLICATE KEY UPDATE
              best_match_workspace_column_id = VALUES(best_match_workspace_column_id),
              alternate_workspace_column_ids = VALUES(alternate_workspace_column_ids),
              retrieved_candidates_json = VALUES(retrieved_candidates_json),
              llm_response_json = VALUES(llm_response_json),
              match_decision = VALUES(match_decision),
              reason_codes_json = VALUES(reason_codes_json),
              explanation = VALUES(explanation),
              ambiguity_note = VALUES(ambiguity_note),
              llm_confidence = VALUES(llm_confidence),
              confidence_score = VALUES(confidence_score),
              confidence_band = VALUES(confidence_band),
              status = VALUES(status),
              updated_at = CURRENT_TIMESTAMP
            """,
            {
                "id": mapping_id,
                "session_id": session_id,
                "source_record_id": int(source_record_id),
                "best_match_workspace_column_id": selected.get("column_id") if selected else None,
                "alternate_workspace_column_ids": _json_dumps([row.get("column_id") for row in alternates]),
                "retrieved_candidates_json": _json_dumps(list(candidates)),
                "llm_response_json": _json_dumps(llm_rank),
                "match_decision": str(llm_rank.get("match_decision") or "no_confident_match"),
                "reason_codes_json": _json_dumps(llm_rank.get("reason_codes") or []),
                "explanation": str(llm_rank.get("explanation") or "").strip(),
                "ambiguity_note": _to_text_or_none(llm_rank.get("ambiguity_note")),
                "llm_confidence": float(llm_rank.get("llm_confidence") or 0.0),
                "confidence_score": int(confidence.get("confidence_score") or 0),
                "confidence_band": str(confidence.get("confidence_band") or "low"),
                "status": "suggested",
            },
        )

    def get_mapping_row_by_id(
        self,
        *,
        workspace_id: str,
        session_id: str,
        mapping_id: str,
    ) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT fr.id, fr.session_id
            FROM forge_match_result fr
            JOIN forge_match_session fms ON fms.id = fr.session_id
            WHERE fr.id = :id
              AND fr.session_id = :session_id
              AND fms.workspace_id = :workspace_id
            LIMIT 1
            """,
            {"id": mapping_id, "session_id": session_id, "workspace_id": workspace_id},
        )
        return dict(rows[0]) if rows else None

    def assert_workspace_column(self, *, workspace_id: str, workspace_column_id: int) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT wc.id
            FROM workspace_column wc
            JOIN workspace_table wt ON wt.id = wc.workspace_table_id
            WHERE wc.id = :id
              AND wt.workspace_id = :workspace_id
            LIMIT 1
            """,
            {"id": int(workspace_column_id), "workspace_id": workspace_id},
        )
        if not rows:
            raise ForgeError("manually_selected_workspace_column_id not found in workspace", status_code=404)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, default=str)


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if text == "":
        raise ForgeError(f"{field} is required", status_code=400)
    return text


def _to_text_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["ForgeMatchMappingStore"]
