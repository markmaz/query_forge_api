from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Set

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.forge_match.field_extractor import SourceFieldRecord

JSON_DICT_PARSE_ERRORS = (TypeError, ValueError, json.JSONDecodeError)


class ForgeMatchSessionReader:
    def __init__(
        self,
        *,
        sql: ForgeQueryPort,
        allowed_result_statuses: Optional[Set[str]] = None,
    ) -> None:
        self._sql = sql
        self._allowed_result_statuses = set(allowed_result_statuses or set())

    def accepted_columns(self, *, workspace_id: str, session_id: str) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              fr.id AS mapping_id,
              fsr.sheet_name,
              fsr.`row_number`,
              fsr.source_field_name,
              COALESCE(fr.manually_selected_workspace_column_id, fr.best_match_workspace_column_id) AS selected_workspace_column_id,
              wc.workspace_table_id,
              wc.column_name,
              wt.table_name,
              wt.full_name
            FROM forge_match_result fr
            JOIN forge_match_source_record fsr ON fsr.id = fr.source_record_id
            JOIN forge_match_session fms ON fms.id = fr.session_id
            LEFT JOIN workspace_column wc
              ON wc.id = COALESCE(fr.manually_selected_workspace_column_id, fr.best_match_workspace_column_id)
            LEFT JOIN workspace_table wt ON wt.id = wc.workspace_table_id
            WHERE fr.session_id = :session_id
              AND fms.workspace_id = :workspace_id
              AND fr.status IN ('accepted', 'manually_mapped')
            ORDER BY fsr.sheet_name ASC, fsr.`row_number` ASC
            """,
            {"workspace_id": workspace_id, "session_id": session_id},
        )
        return [
            {
                "mapping_id": row.get("mapping_id"),
                "sheet_name": row.get("sheet_name"),
                "row_number": row.get("row_number"),
                "source_field_name": row.get("source_field_name"),
                "selected_workspace_column_id": row.get("selected_workspace_column_id"),
                "workspace_table_id": row.get("workspace_table_id"),
                "column_name": row.get("column_name"),
                "table_name": row.get("table_name"),
                "full_name": row.get("full_name"),
            }
            for row in rows
            if row.get("selected_workspace_column_id")
        ]

    def get_session_row(self, *, workspace_id: str, session_id: str) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM forge_match_session
            WHERE id = :session_id
              AND workspace_id = :workspace_id
            LIMIT 1
            """,
            {"workspace_id": workspace_id, "session_id": session_id},
        )
        if not rows:
            raise ForgeError("ForgeMatch session not found", status_code=404)
        return self._session_row_to_response(rows[0])

    def load_source_rows(self, *, session_id: str, limit: int = 2000, offset: int = 0) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              row_id,
              sheet_name,
              `row_number`,
              source_field_name,
              source_description,
              source_type,
              source_object_name,
              sample_value,
              category,
              normalized_search_text,
              raw_row_json,
              created_at
            FROM forge_match_source_record
            WHERE session_id = :session_id
            ORDER BY sheet_name ASC, `row_number` ASC
            LIMIT :limit OFFSET :offset
            """,
            {"session_id": session_id, "limit": int(limit), "offset": int(offset)},
        )
        return [json_safe_row(dict(row)) for row in rows]

    def load_mapping_rows(
        self,
        *,
        workspace_id: str,
        session_id: str,
        limit: int = 5000,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              fr.id AS mapping_id,
              fr.session_id,
              fr.source_record_id,
              fsr.row_id AS source_row_id,
              fsr.sheet_name,
              fsr.`row_number`,
              fsr.source_field_name,
              fsr.source_description,
              fsr.source_type,
              fsr.source_object_name,
              fsr.sample_value,
              fr.best_match_workspace_column_id,
              wc_best.column_name AS best_match_column_name,
              wt_best.table_name AS best_match_table_name,
              fr.alternate_workspace_column_ids,
              fr.retrieved_candidates_json,
              fr.llm_response_json,
              fr.match_decision,
              fr.reason_codes_json,
              fr.explanation,
              fr.ambiguity_note,
              fr.llm_confidence,
              fr.confidence_score,
              fr.confidence_band,
              fr.status,
              fr.review_notes,
              fr.manually_selected_workspace_column_id,
              wc_manual.column_name AS manual_column_name,
              wt_manual.table_name AS manual_table_name,
              fr.reviewer_user_id,
              fr.reviewed_at,
              fr.created_at,
              fr.updated_at
            FROM forge_match_result fr
            JOIN forge_match_source_record fsr ON fsr.id = fr.source_record_id
            JOIN forge_match_session fms ON fms.id = fr.session_id
            LEFT JOIN workspace_column wc_best ON wc_best.id = fr.best_match_workspace_column_id
            LEFT JOIN workspace_table wt_best ON wt_best.id = wc_best.workspace_table_id
            LEFT JOIN workspace_column wc_manual ON wc_manual.id = fr.manually_selected_workspace_column_id
            LEFT JOIN workspace_table wt_manual ON wt_manual.id = wc_manual.workspace_table_id
            WHERE fr.session_id = :session_id
              AND fms.workspace_id = :workspace_id
            ORDER BY fsr.sheet_name ASC, fsr.`row_number` ASC
            LIMIT :limit OFFSET :offset
            """,
            {
                "workspace_id": workspace_id,
                "session_id": session_id,
                "limit": int(limit),
                "offset": int(offset),
            },
        )
        return [self._mapping_row_to_response(json_safe_row(dict(row))) for row in rows]

    def build_summary(self, mappings: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        counts = {status: 0 for status in self._allowed_result_statuses}
        decision_counts = {"matched": 0, "ambiguous": 0, "no_confident_match": 0}
        by_band = {"high": 0, "medium": 0, "low": 0}

        for row in mappings:
            status = str(row.get("status") or "suggested")
            if status in counts:
                counts[status] += 1
            decision = str(row.get("match_decision") or "no_confident_match")
            if decision in decision_counts:
                decision_counts[decision] += 1
            band = str(row.get("confidence_band") or "low")
            if band in by_band:
                by_band[band] += 1

        return {
            "total": len(mappings),
            "status_counts": counts,
            "decision_counts": decision_counts,
            "confidence_bands": by_band,
        }

    @staticmethod
    def source_record_to_dict(record: SourceFieldRecord) -> Dict[str, Any]:
        return {
            "row_id": record.row_id,
            "sheet_name": record.sheet_name,
            "row_number": record.row_number,
            "source_field_name": record.source_field_name,
            "source_description": record.source_description,
            "source_type": record.source_type,
            "source_object_name": record.source_object_name,
            "sample_value": record.sample_value,
            "category": record.category,
        }

    @staticmethod
    def source_row_to_response(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": int(row.get("id") or 0),
            "row_id": row.get("row_id"),
            "sheet_name": row.get("sheet_name"),
            "row_number": row.get("row_number"),
            "source_field_name": row.get("source_field_name"),
            "source_description": row.get("source_description"),
            "source_type": row.get("source_type"),
            "source_object_name": row.get("source_object_name"),
            "sample_value": row.get("sample_value"),
            "category": row.get("category"),
            "created_at": row.get("created_at"),
        }

    def _mapping_row_to_response(self, row: Dict[str, Any]) -> Dict[str, Any]:
        best_match = None
        if row.get("best_match_workspace_column_id"):
            best_match = {
                "column_id": int(row["best_match_workspace_column_id"]),
                "column_name": row.get("best_match_column_name"),
                "display_name": _display_name(row.get("best_match_column_name")),
                "table_name": row.get("best_match_table_name"),
            }

        alt_ids = _parse_json_list(row.get("alternate_workspace_column_ids"))
        retrieved = _parse_json_list(row.get("retrieved_candidates_json"))
        llm_response = _parse_json_dict(row.get("llm_response_json")) or {}
        alternate_ids = {int(v) for v in alt_ids if _safe_int(v) is not None}
        alternates = [item for item in retrieved if int(item.get("column_id") or 0) in alternate_ids]

        out = {
            "mapping_id": row.get("mapping_id"),
            "source_record_id": row.get("source_record_id"),
            "source_row_id": row.get("source_row_id"),
            "sheet_name": row.get("sheet_name"),
            "row_number": row.get("row_number"),
            "source_field_name": row.get("source_field_name"),
            "source_description": row.get("source_description"),
            "source_type": row.get("source_type"),
            "source_object_name": row.get("source_object_name"),
            "sample_value": row.get("sample_value"),
            "best_match": best_match,
            "alternates": alternates[:2],
            "confidence_score": int(row.get("confidence_score") or 0),
            "confidence_band": str(row.get("confidence_band") or "low"),
            "match_decision": row.get("match_decision"),
            "explanation": row.get("explanation"),
            "reason_codes": _parse_json_list(row.get("reason_codes_json")),
            "status": row.get("status"),
            "review_notes": row.get("review_notes"),
            "manually_selected_workspace_column_id": row.get("manually_selected_workspace_column_id"),
            "manual_selection": None,
            "retrieved_candidates": retrieved,
            "llm_result": llm_response,
            "shared_pipeline": dict(llm_response.get("shared_pipeline") or {}),
            "reviewer_user_id": row.get("reviewer_user_id"),
            "reviewed_at": row.get("reviewed_at"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
        if row.get("manually_selected_workspace_column_id"):
            out["manual_selection"] = {
                "column_id": int(row["manually_selected_workspace_column_id"]),
                "column_name": row.get("manual_column_name"),
                "display_name": _display_name(row.get("manual_column_name")),
                "table_name": row.get("manual_table_name"),
            }
        return out

    @staticmethod
    def _session_row_to_response(row: Dict[str, Any]) -> Dict[str, Any]:
        safe = json_safe_row(dict(row))
        safe["summary_json"] = _parse_json_dict(safe.get("summary_json"))
        return safe


def json_safe_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, (datetime, date)):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _parse_json_dict(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            parsed = json.loads(text)
        except JSON_DICT_PARSE_ERRORS:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _parse_json_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return []
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _display_name(column_name: Any) -> str:
    text = str(column_name or "").strip()
    if text == "":
        return ""
    return " ".join(token.capitalize() for token in text.replace("-", "_").split("_") if token)


__all__ = ["ForgeMatchSessionReader", "json_safe_row"]
