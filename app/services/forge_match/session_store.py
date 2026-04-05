from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional, Sequence

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.forge_match.field_extractor import SourceFieldRecord
from app.services.forge_match.session_reader import ForgeMatchSessionReader, json_safe_row


class ForgeMatchSessionStore:
    def __init__(
        self,
        *,
        sql: ForgeQueryPort,
        session_reader: ForgeMatchSessionReader,
    ) -> None:
        self._sql = sql
        self._session_reader = session_reader

    def list_sessions(
        self,
        *,
        workspace_id: str,
        page: int = 1,
        page_size: int = 25,
        status: Optional[str] = None,
        q: Optional[str] = None,
    ) -> Dict[str, Any]:
        page_val = max(1, int(page or 1))
        size_val = min(200, max(1, int(page_size or 25)))
        offset = (page_val - 1) * size_val

        where = ["s.workspace_id = :workspace_id"]
        params: Dict[str, Any] = {
            "workspace_id": workspace_id,
            "limit": size_val,
            "offset": offset,
        }

        if status is not None and str(status).strip() != "":
            status_norm = str(status).strip().lower()
            where.append("LOWER(s.status) = :status")
            params["status"] = status_norm

        if q is not None and str(q).strip() != "":
            token = f"%{str(q).strip().lower()}%"
            where.append(
                "(LOWER(COALESCE(s.uploaded_filename, '')) LIKE :q "
                "OR LOWER(COALESCE(s.created_by, '')) LIKE :q)"
            )
            params["q"] = token

        where_sql = " AND ".join(where)

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              s.id,
              s.workspace_id,
              s.uploaded_filename,
              s.file_type,
              s.created_by,
              s.status,
              s.sheet_count,
              s.source_record_count,
              s.analysis_started_at,
              s.analysis_completed_at,
              s.created_at,
              s.updated_at,
              (
                SELECT COUNT(*)
                FROM forge_match_result r
                WHERE r.session_id = s.id
              ) AS result_count,
              (
                SELECT COUNT(*)
                FROM forge_match_result r
                WHERE r.session_id = s.id
                  AND r.status = 'accepted'
              ) AS accepted_count,
              (
                SELECT COUNT(*)
                FROM forge_match_result r
                WHERE r.session_id = s.id
                  AND r.status = 'manually_mapped'
              ) AS manually_mapped_count
            FROM forge_match_session s
            WHERE {where_sql}
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

        total_rows = self._sql.execute_query_mappings(
            f"""
            SELECT COUNT(*) AS total
            FROM forge_match_session s
            WHERE {where_sql}
            """,
            {k: v for k, v in params.items() if k not in {"limit", "offset"}},
        )
        total = int((total_rows[0] or {}).get("total") or 0) if total_rows else 0

        return {
            "rows": [json_safe_row(dict(row)) for row in rows],
            "total": total,
            "page": page_val,
            "page_size": size_val,
        }

    def create_uploaded_session(
        self,
        *,
        session_id: str,
        workspace_id: str,
        created_by: str,
        upload_name: str,
        file_type: str,
        sheet_names: Sequence[str],
        records: Sequence[SourceFieldRecord],
        created_at: datetime,
    ) -> None:
        with self._sql.transaction() as tx:
            tx.execute_insert(
                """
                INSERT INTO forge_match_session (
                  id,
                  workspace_id,
                  uploaded_filename,
                  file_type,
                  created_by,
                  status,
                  sheet_count,
                  source_record_count,
                  summary_json,
                  created_at,
                  updated_at
                ) VALUES (
                  :id,
                  :workspace_id,
                  :uploaded_filename,
                  :file_type,
                  :created_by,
                  'uploaded',
                  :sheet_count,
                  :source_record_count,
                  :summary_json,
                  :created_at,
                  :updated_at
                )
                """,
                {
                    "id": session_id,
                    "workspace_id": workspace_id,
                    "uploaded_filename": upload_name,
                    "file_type": file_type,
                    "created_by": created_by,
                    "sheet_count": len(sheet_names),
                    "source_record_count": len(records),
                    "summary_json": _json_dumps(
                        {
                            "sheet_names": list(sheet_names),
                            "detected_count": len(records),
                        }
                    ),
                    "created_at": created_at,
                    "updated_at": created_at,
                },
            )

            for record in records:
                tx.execute_insert(
                    """
                    INSERT INTO forge_match_source_record (
                      session_id,
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
                      raw_row_json
                    ) VALUES (
                      :session_id,
                      :row_id,
                      :sheet_name,
                      :row_number,
                      :source_field_name,
                      :source_description,
                      :source_type,
                      :source_object_name,
                      :sample_value,
                      :category,
                      :normalized_search_text,
                      :raw_row_json
                    )
                    """,
                    {
                        "session_id": session_id,
                        "row_id": record.row_id,
                        "sheet_name": record.sheet_name,
                        "row_number": record.row_number,
                        "source_field_name": record.source_field_name,
                        "source_description": record.source_description,
                        "source_type": record.source_type,
                        "source_object_name": record.source_object_name,
                        "sample_value": record.sample_value,
                        "category": record.category,
                        "normalized_search_text": record.normalized_search_text,
                        "raw_row_json": _json_dumps(record.raw_row),
                    },
                )

    def delete_session(self, *, workspace_id: str, session_id: str) -> Dict[str, Any]:
        session = self._session_reader.get_session_row(workspace_id=workspace_id, session_id=session_id)

        status = str(session.get("status") or "").strip().lower()
        if status in {"queued", "analyzing"}:
            raise ForgeError("Cannot delete a ForgeMatch session while analysis is in progress", status_code=409)

        self._sql.execute_write(
            """
            DELETE FROM forge_match_session
            WHERE id = :session_id
              AND workspace_id = :workspace_id
            """,
            {"session_id": session_id, "workspace_id": workspace_id},
        )

        return {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "deleted": True,
            "message": "ForgeMatch session deleted",
        }

    def existing_results_by_source(self, *, session_id: str) -> Dict[int, str]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT source_record_id, id
            FROM forge_match_result
            WHERE session_id = :session_id
            """,
            {"session_id": session_id},
        )
        out: dict[int, str] = {}
        for row in rows:
            source_id = int(row.get("source_record_id") or 0)
            mapping_id = str(row.get("id") or "").strip()
            if source_id > 0 and mapping_id:
                out[source_id] = mapping_id
        return out

    def clear_session_results(self, *, session_id: str) -> None:
        self._sql.execute_write(
            """
            DELETE FROM forge_match_result
            WHERE session_id = :session_id
            """,
            {"session_id": session_id},
        )

    def persist_session_analysis_trace(
        self,
        *,
        session_id: str,
        current_summary: Any,
        trace_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        summary = current_summary if isinstance(current_summary, dict) else {}
        next_summary = dict(summary)
        next_summary["analysis_trace"] = dict(trace_snapshot)
        self._sql.execute_write(
            """
            UPDATE forge_match_session
            SET summary_json = :summary_json,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :session_id
            """,
            {
                "session_id": session_id,
                "summary_json": _json_dumps(next_summary),
            },
        )
        return next_summary


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, default=str)


__all__ = ["ForgeMatchSessionStore"]
