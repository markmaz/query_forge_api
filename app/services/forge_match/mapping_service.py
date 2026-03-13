from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.forge_match.candidate_retriever import ForgeMatchCandidateRetriever
from app.services.forge_match.confidence import ForgeMatchConfidenceScorer
from app.services.forge_match.export_service import ForgeMatchExportService
from app.services.forge_match.field_extractor import ForgeMatchFieldExtractor, SourceFieldRecord
from app.services.forge_match.file_parser import ForgeMatchFileParser
from app.services.forge_match.llm_ranker import ForgeMatchLLMRanker

logger = logging.getLogger(__name__)

_ALLOWED_RESULT_STATUSES = {"suggested", "accepted", "rejected", "needs_review", "manually_mapped"}
_TERMINAL_SESSION_STATUSES = {"uploaded", "analyzed", "failed", "canceled", "cancelled"}


class ForgeMatchMappingService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        parser: Optional[ForgeMatchFileParser] = None,
        extractor: Optional[ForgeMatchFieldExtractor] = None,
        retriever: Optional[ForgeMatchCandidateRetriever] = None,
        ranker: Optional[ForgeMatchLLMRanker] = None,
        confidence: Optional[ForgeMatchConfidenceScorer] = None,
        exporter: Optional[ForgeMatchExportService] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._parser = parser or ForgeMatchFileParser()
        self._extractor = extractor or ForgeMatchFieldExtractor()
        self._retriever = retriever or ForgeMatchCandidateRetriever(sql=self._sql)
        self._ranker = ranker or ForgeMatchLLMRanker()
        self._confidence = confidence or ForgeMatchConfidenceScorer()
        self._exporter = exporter or ForgeMatchExportService(sql=self._sql)
        self._extended_progress_columns_supported = True

    def list_sessions(
        self,
        *,
        workspace_id: str,
        page: int = 1,
        page_size: int = 25,
        status: Optional[str] = None,
        q: Optional[str] = None,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        page_val = max(1, int(page or 1))
        size_val = min(200, max(1, int(page_size or 25)))
        offset = (page_val - 1) * size_val

        where = ["s.workspace_id = :workspace_id"]
        params: Dict[str, Any] = {
            "workspace_id": ws,
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
            "rows": [self._json_safe_row(dict(row)) for row in rows],
            "total": total,
            "page": page_val,
            "page_size": size_val,
        }

    def upload_file(
        self,
        *,
        workspace_id: str,
        created_by: str,
        filename: str,
        file_bytes: bytes,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        user = _required_text(created_by, "created_by")
        upload_name = _required_text(filename, "filename")
        if not file_bytes:
            raise ForgeError("file is empty", status_code=400)

        parsed = self._parser.parse(file_bytes=file_bytes, filename=upload_name)
        records = self._extractor.extract(workbook=parsed)
        if not records:
            raise ForgeError("No source fields detected in uploaded file", status_code=400)

        session_id = str(uuid.uuid4())
        now = datetime.now()

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
                    "workspace_id": ws,
                    "uploaded_filename": upload_name,
                    "file_type": parsed.file_type,
                    "created_by": user,
                    "sheet_count": len(parsed.sheets),
                    "source_record_count": len(records),
                    "summary_json": _json_dumps(
                        {
                            "sheet_names": [sheet.sheet_name for sheet in parsed.sheets],
                            "detected_count": len(records),
                        }
                    ),
                    "created_at": now,
                    "updated_at": now,
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

        return {
            "session_id": session_id,
            "workspace_id": ws,
            "uploaded_filename": upload_name,
            "file_type": parsed.file_type,
            "status": "uploaded",
            "sheet_count": len(parsed.sheets),
            "source_record_count": len(records),
            "source_preview": [self._source_record_to_dict(row) for row in records[:25]],
        }

    def analyze_session(
        self,
        *,
        workspace_id: str,
        session_id: str,
        vertical_norm: Optional[str] = None,
        domain_id: Optional[int] = None,
        top_n: int = 8,
        force: bool = False,
    ) -> Dict[str, Any]:
        return self.run_analyze_job(
            workspace_id=workspace_id,
            session_id=session_id,
            vertical_norm=vertical_norm,
            domain_id=domain_id,
            top_n=top_n,
            force=force,
            job_id=None,
        )

    def start_analyze_session_job(
        self,
        *,
        workspace_id: str,
        session_id: str,
        top_n: int = 8,
        domain_id: Optional[int] = None,
        vertical_norm: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        del vertical_norm  # reserved for future filtering
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        session = self._get_session_row(workspace_id=ws, session_id=sid)

        status = str(session.get("status") or "").strip().lower()
        existing_job_id = _to_text_or_none(session.get("analysis_job_id"))
        if status in {"queued", "analyzing"} and existing_job_id:
            return {
                "job_id": existing_job_id,
                "session_id": sid,
                "workspace_id": ws,
                "status": status,
                "message": "Analyze run already in progress",
            }

        job_id = str(uuid.uuid4())
        source_total = int(session.get("source_record_count") or 0)
        self._update_session_progress(
            session_id=sid,
            status="queued",
            job_id=job_id,
            source_total=source_total,
            source_done=0,
            source_skipped=0,
            source_failed=0,
            current_phase="queued",
            current_source_row_id=None,
            analysis_error=None,
            cancel_requested=False,
            started_at=None,
            completed_at=None,
        )

        return {
            "job_id": job_id,
            "session_id": sid,
            "workspace_id": ws,
            "status": "queued",
            "source_total": source_total,
            "message": "ForgeMatch analysis queued",
            "top_n": max(3, int(top_n or 8)),
            "domain_id": int(domain_id) if domain_id is not None else None,
            "force": bool(force),
        }

    def run_analyze_job(
        self,
        *,
        workspace_id: str,
        session_id: str,
        vertical_norm: Optional[str] = None,
        domain_id: Optional[int] = None,
        top_n: int = 8,
        force: bool = False,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        del vertical_norm  # reserved for future filtering

        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        session = self._get_session_row(workspace_id=ws, session_id=sid)
        source_rows = self._load_source_rows(session_id=sid)
        if not source_rows:
            raise ForgeError("No source records found for session", status_code=400)

        if force:
            self._sql.execute_write(
                """
                DELETE FROM forge_match_result
                WHERE session_id = :session_id
                """,
                {"session_id": sid},
            )

        existing_by_source = self._existing_results_by_source(session_id=sid)
        source_total = len(source_rows)
        analyzed = 0
        skipped = 0
        failed = 0

        self._update_session_progress(
            session_id=sid,
            status="analyzing",
            job_id=job_id,
            source_total=source_total,
            source_done=0,
            source_skipped=0,
            source_failed=0,
            current_phase="analyzing",
            current_source_row_id=None,
            analysis_error=None,
            cancel_requested=False,
            started_at=datetime.utcnow(),
            completed_at=None,
        )

        try:
            for source in source_rows:
                src_id = int(source["id"])
                current_source_row_id = str(source.get("row_id") or "")

                if self._is_cancel_requested(session_id=sid):
                    self._update_session_progress(
                        session_id=sid,
                        status="canceled",
                        job_id=job_id,
                        source_total=source_total,
                        source_done=analyzed,
                        source_skipped=skipped,
                        source_failed=failed,
                        current_phase="canceled",
                        current_source_row_id=current_source_row_id or None,
                        analysis_error="Canceled by operator",
                        cancel_requested=True,
                        started_at=None,
                        completed_at=datetime.utcnow(),
                    )
                    return {
                        "job_id": job_id,
                        "session_id": sid,
                        "workspace_id": ws,
                        "status": "canceled",
                        "result_count": len(self._load_mapping_rows(workspace_id=ws, session_id=sid)),
                        "analyzed_count": analyzed,
                        "skipped_count": skipped,
                        "failed_count": failed,
                        "summary": self._build_summary(self._load_mapping_rows(workspace_id=ws, session_id=sid)),
                        "mappings": self._load_mapping_rows(workspace_id=ws, session_id=sid),
                        "session": session,
                    }

                if (not force) and src_id in existing_by_source:
                    skipped += 1
                    self._update_session_progress(
                        session_id=sid,
                        status="analyzing",
                        job_id=job_id,
                        source_total=source_total,
                        source_done=analyzed,
                        source_skipped=skipped,
                        source_failed=failed,
                        current_phase="skipping_existing",
                        current_source_row_id=current_source_row_id or None,
                    )
                    continue

                source_record = SourceFieldRecord(
                    row_id=str(source.get("row_id") or ""),
                    sheet_name=str(source.get("sheet_name") or ""),
                    row_number=int(source.get("row_number") or 0),
                    source_field_name=str(source.get("source_field_name") or ""),
                    source_description=_to_text_or_none(source.get("source_description")),
                    source_type=_to_text_or_none(source.get("source_type")),
                    source_object_name=_to_text_or_none(source.get("source_object_name")),
                    sample_value=_to_text_or_none(source.get("sample_value")),
                    category=_to_text_or_none(source.get("category")),
                    normalized_search_text=str(source.get("normalized_search_text") or ""),
                    raw_row=_parse_json_dict(source.get("raw_row_json")) or {},
                )

                try:
                    candidates = self._retriever.retrieve(
                        workspace_id=ws,
                        source_record=source_record,
                        top_n=max(3, int(top_n or 8)),
                        domain_id=int(domain_id) if domain_id is not None else None,
                    )
                    llm_rank = self._ranker.rank(source_record=source_record, candidates=candidates)
                    selected = self._find_candidate(candidates, llm_rank.get("selected_column_id"))
                    alternates = self._find_alternates(candidates, llm_rank.get("alternate_column_ids") or [])
                    confidence = self._confidence.score(
                        source_record=source_record,
                        selected_candidate=selected,
                        candidates=candidates,
                        llm_result=llm_rank,
                    )
                    self._upsert_mapping_result(
                        session_id=sid,
                        source_record_id=src_id,
                        selected=selected,
                        alternates=alternates,
                        candidates=candidates,
                        llm_rank=llm_rank,
                        confidence=confidence,
                    )
                    analyzed += 1
                    current_phase = "ranking"
                except Exception as row_exc:
                    failed += 1
                    logger.exception(
                        "ForgeMatch row analyze failed session_id=%s source_record_id=%s",
                        sid,
                        src_id,
                    )
                    self._upsert_mapping_result(
                        session_id=sid,
                        source_record_id=src_id,
                        selected=None,
                        alternates=[],
                        candidates=[],
                        llm_rank={
                            "match_decision": "no_confident_match",
                            "reason_codes": ["processing_error"],
                            "explanation": f"Processing error: {str(row_exc)[:300]}",
                            "ambiguity_note": None,
                            "llm_confidence": 0.0,
                        },
                        confidence={"confidence_score": 0, "confidence_band": "low"},
                    )
                    current_phase = "row_error"

                self._update_session_progress(
                    session_id=sid,
                    status="analyzing",
                    job_id=job_id,
                    source_total=source_total,
                    source_done=analyzed,
                    source_skipped=skipped,
                    source_failed=failed,
                    current_phase=current_phase,
                    current_source_row_id=current_source_row_id or None,
                )

            mappings = self._load_mapping_rows(workspace_id=ws, session_id=sid)
            summary = self._build_summary(mappings)
            warning_error = None
            if failed > 0:
                warning_error = f"Completed with row errors: failed_count={failed}"

            self._update_session_progress(
                session_id=sid,
                status="analyzed",
                job_id=job_id,
                source_total=source_total,
                source_done=analyzed,
                source_skipped=skipped,
                source_failed=failed,
                current_phase="analyzed",
                current_source_row_id=None,
                analysis_error=warning_error,
                completed_at=datetime.utcnow(),
            )

            return {
                "job_id": job_id,
                "session_id": sid,
                "workspace_id": ws,
                "status": "analyzed",
                "result_count": len(mappings),
                "analyzed_count": analyzed,
                "skipped_count": skipped,
                "failed_count": failed,
                "summary": summary,
                "mappings": mappings,
                "session": session,
            }
        except Exception as exc:
            logger.exception("ForgeMatch analyze session failed session_id=%s", sid)
            self._update_session_progress(
                session_id=sid,
                status="failed",
                job_id=job_id,
                source_total=source_total,
                source_done=analyzed,
                source_skipped=skipped,
                source_failed=failed + 1,
                current_phase="failed",
                current_source_row_id=None,
                analysis_error=str(exc)[:2000],
                completed_at=datetime.utcnow(),
            )
            raise

    def get_analysis_status(self, *, workspace_id: str, job_id: str) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        jid = _required_text(job_id, "job_id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM forge_match_session
            WHERE workspace_id = :workspace_id
              AND (analysis_job_id = :job_id OR id = :job_id)
            ORDER BY CASE WHEN analysis_job_id = :job_id THEN 0 ELSE 1 END
            LIMIT 1
            """,
            {"workspace_id": ws, "job_id": jid},
        )
        if not rows:
            raise ForgeError("ForgeMatch run not found", status_code=404)
        return self._serialize_analysis_status(self._json_safe_row(dict(rows[0])))

    def cancel_analysis_job(self, *, workspace_id: str, job_id: str) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        jid = _required_text(job_id, "job_id")
        status = self.get_analysis_status(workspace_id=ws, job_id=jid)
        current_status = str(status.get("status") or "").lower()
        if current_status in _TERMINAL_SESSION_STATUSES:
            return {
                "job_id": status.get("job_id"),
                "session_id": status.get("session_id"),
                "canceled": False,
                "status": current_status,
                "message": "Run already in terminal status",
            }

        sid = str(status.get("session_id") or "")
        self._update_session_progress(
            session_id=sid,
            status="canceled",
            job_id=str(status.get("job_id") or jid),
            source_total=int(status.get("source_total") or 0),
            source_done=int(status.get("source_done") or 0),
            source_skipped=int(status.get("source_skipped") or 0),
            source_failed=int(status.get("source_failed") or 0),
            current_phase="canceled",
            current_source_row_id=status.get("current_source_row_id"),
            analysis_error="Canceled by operator",
            cancel_requested=True,
            completed_at=datetime.utcnow(),
        )
        refreshed = self.get_analysis_status(workspace_id=ws, job_id=jid)
        return {
            "job_id": refreshed.get("job_id"),
            "session_id": refreshed.get("session_id"),
            "canceled": True,
            "status": str(refreshed.get("status") or "").lower(),
            "message": "Cancellation requested",
        }

    def list_analysis_history(self, *, workspace_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        ws = _required_text(workspace_id, "workspace_id")
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM forge_match_session
            WHERE workspace_id = :workspace_id
              AND analysis_started_at IS NOT NULL
            ORDER BY analysis_started_at DESC
            LIMIT :limit
            """,
            {"workspace_id": ws, "limit": max(1, min(200, int(limit or 20)))},
        )
        return [self._serialize_analysis_status(self._json_safe_row(dict(row))) for row in rows]

    def mark_enqueue_failed(
        self,
        *,
        session_id: str,
        job_id: str,
        source_total: int,
        error_message: str,
    ) -> None:
        self._update_session_progress(
            session_id=_required_text(session_id, "session_id"),
            status="failed",
            job_id=_required_text(job_id, "job_id"),
            source_total=int(source_total or 0),
            source_done=0,
            source_skipped=0,
            source_failed=1,
            current_phase="failed",
            current_source_row_id=None,
            analysis_error=str(error_message or "Failed to enqueue ForgeMatch analysis task")[:2000],
            completed_at=None,
        )

    def get_session(
        self,
        *,
        workspace_id: str,
        session_id: str,
        source_limit: int = 200,
        source_offset: int = 0,
        mapping_limit: int = 500,
        mapping_offset: int = 0,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")

        session = self._get_session_row(workspace_id=ws, session_id=sid)
        source_records = self._load_source_rows(
            session_id=sid,
            limit=max(1, min(1000, int(source_limit))),
            offset=max(0, int(source_offset)),
        )
        mappings = self._load_mapping_rows(
            workspace_id=ws,
            session_id=sid,
            limit=max(1, min(2000, int(mapping_limit))),
            offset=max(0, int(mapping_offset)),
        )
        summary = self._build_summary(mappings)

        return {
            "session": session,
            "source_records": [self._source_row_to_response(row) for row in source_records],
            "mappings": mappings,
            "summary": summary,
        }

    def patch_mappings(
        self,
        *,
        workspace_id: str,
        session_id: str,
        reviewer_user_id: str,
        updates: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        reviewer = _required_text(reviewer_user_id, "reviewer_user_id")
        self._get_session_row(workspace_id=ws, session_id=sid)

        changed: list[dict[str, Any]] = []

        for update in updates:
            mapping_id = _required_text(update.get("mapping_id"), "mapping_id")
            row = self._get_mapping_row_by_id(workspace_id=ws, session_id=sid, mapping_id=mapping_id)
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
                if status not in _ALLOWED_RESULT_STATUSES:
                    raise ForgeError(f"Invalid status: {status}", status_code=400)

            manual_col_id = None
            if manual_col is not None:
                try:
                    manual_col_id = int(manual_col)
                except Exception as exc:
                    raise ForgeError("manually_selected_workspace_column_id must be integer", status_code=400) from exc
                if manual_col_id <= 0:
                    raise ForgeError("manually_selected_workspace_column_id must be > 0", status_code=400)
                self._assert_workspace_column(workspace_id=ws, workspace_column_id=manual_col_id)
                if status is None:
                    status = "manually_mapped"
            elif action and action.lower() == "remap":
                raise ForgeError("remap action requires manually_selected_workspace_column_id", status_code=400)

            if status is None and notes is None and manual_col is None:
                continue

            params: Dict[str, Any] = {
                "id": mapping_id,
                "session_id": sid,
                "reviewer_user_id": reviewer,
            }
            set_parts = ["reviewer_user_id = :reviewer_user_id", "reviewed_at = CURRENT_TIMESTAMP", "updated_at = CURRENT_TIMESTAMP"]

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
            "session_id": sid,
            "workspace_id": ws,
            "updated": len(changed),
            "rows": changed,
        }

    def export_session(
        self,
        *,
        workspace_id: str,
        session_id: str,
        export_format: str,
    ) -> tuple[bytes, str, str]:
        return self._exporter.export_session(
            workspace_id=workspace_id,
            session_id=session_id,
            export_format=export_format,
        )

    def create_view_draft(self, *, workspace_id: str, session_id: str, name: Optional[str] = None) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        accepted = self._accepted_columns(workspace_id=ws, session_id=sid)
        artifact_id = f"fmdv_{uuid.uuid4().hex[:16]}"
        return {
            "artifact_id": artifact_id,
            "workspace_id": ws,
            "session_id": sid,
            "name": (name or f"ForgeMatch View Draft {sid[:8]}").strip(),
            "accepted_column_count": len(accepted),
            "columns": accepted,
            "status": "draft_created",
            "note": "V1 draft artifact only; no SQL view was created.",
        }

    def create_domain_draft(self, *, workspace_id: str, session_id: str, name: Optional[str] = None) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        accepted = self._accepted_columns(workspace_id=ws, session_id=sid)
        artifact_id = f"fmdd_{uuid.uuid4().hex[:16]}"
        return {
            "artifact_id": artifact_id,
            "workspace_id": ws,
            "session_id": sid,
            "name": (name or f"ForgeMatch Domain Draft {sid[:8]}").strip(),
            "accepted_column_count": len(accepted),
            "columns": accepted,
            "status": "draft_created",
            "note": "V1 draft artifact only; no production domain was created.",
        }

    def _upsert_mapping_result(
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

    def _is_cancel_requested(self, *, session_id: str) -> bool:
        try:
            rows = self._sql.execute_query_mappings(
                """
                SELECT cancel_requested
                FROM forge_match_session
                WHERE id = :session_id
                LIMIT 1
                """,
                {"session_id": session_id},
            )
        except Exception:
            return False
        if not rows:
            return False
        return bool(int(rows[0].get("cancel_requested") or 0))

    def _update_session_progress(
        self,
        *,
        session_id: str,
        status: str,
        job_id: Optional[str],
        source_total: int,
        source_done: int,
        source_skipped: int,
        source_failed: int,
        current_phase: Optional[str],
        current_source_row_id: Optional[str],
        analysis_error: Optional[str] = None,
        cancel_requested: Optional[bool] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> None:
        params = {
            "session_id": session_id,
            "status": status,
            "analysis_job_id": job_id,
            "source_total": int(source_total or 0),
            "source_done": int(source_done or 0),
            "source_skipped": int(source_skipped or 0),
            "source_failed": int(source_failed or 0),
            "current_phase": _to_text_or_none(current_phase),
            "current_source_row_id": _to_text_or_none(current_source_row_id),
            "analysis_error": _to_text_or_none(analysis_error),
            "cancel_requested": None if cancel_requested is None else (1 if cancel_requested else 0),
            "started_at": started_at,
            "completed_at": completed_at,
            "last_heartbeat_at": datetime.utcnow(),
        }

        advanced_sql = """
            UPDATE forge_match_session
            SET status = :status,
                analysis_job_id = COALESCE(:analysis_job_id, analysis_job_id),
                analyzed_count = :source_done,
                skipped_count = :source_skipped,
                failed_count = :source_failed,
                current_phase = :current_phase,
                current_source_row_id = :current_source_row_id,
                analysis_error = COALESCE(:analysis_error, analysis_error),
                cancel_requested = COALESCE(:cancel_requested, cancel_requested),
                analysis_started_at = COALESCE(:started_at, analysis_started_at),
                analysis_completed_at = :completed_at,
                last_heartbeat_at = :last_heartbeat_at,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :session_id
        """

        fallback_sql = """
            UPDATE forge_match_session
            SET status = :status,
                analysis_started_at = COALESCE(:started_at, analysis_started_at),
                analysis_completed_at = :completed_at,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :session_id
        """

        if self._extended_progress_columns_supported:
            try:
                self._sql.execute_write(advanced_sql, params)
                return
            except Exception:
                self._extended_progress_columns_supported = False
                logger.warning(
                    "forge_match_session extended progress columns missing; using fallback updates"
                )

        self._sql.execute_write(fallback_sql, params)

    @staticmethod
    def _serialize_analysis_status(row: Dict[str, Any]) -> Dict[str, Any]:
        source_total = int(row.get("source_record_count") or 0)
        source_done = int(row.get("analyzed_count") or 0)
        source_skipped = int(row.get("skipped_count") or 0)
        source_failed = int(row.get("failed_count") or 0)
        processed = source_done + source_skipped + source_failed
        progress_pct = 0.0
        if source_total > 0:
            progress_pct = max(0.0, min(100.0, round((processed / source_total) * 100.0, 2)))

        return {
            "id": row.get("analysis_job_id") or row.get("id"),
            "job_id": row.get("analysis_job_id") or row.get("id"),
            "session_id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "uploaded_filename": row.get("uploaded_filename"),
            "status": str(row.get("status") or "").lower(),
            "current_phase": _to_text_or_none(row.get("current_phase")),
            "current_source_row_id": _to_text_or_none(row.get("current_source_row_id")),
            "source_total": source_total,
            "source_done": source_done,
            "source_skipped": source_skipped,
            "source_failed": source_failed,
            "progress_pct": progress_pct,
            "analysis_error": _to_text_or_none(row.get("analysis_error")),
            "cancel_requested": bool(int(row.get("cancel_requested") or 0)),
            "started_at": row.get("analysis_started_at"),
            "completed_at": row.get("analysis_completed_at"),
            "last_heartbeat_at": row.get("last_heartbeat_at"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def _accepted_columns(self, *, workspace_id: str, session_id: str) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              fr.id AS mapping_id,
              fsr.source_field_name,
              COALESCE(fr.manually_selected_workspace_column_id, fr.best_match_workspace_column_id) AS selected_workspace_column_id,
              wc.column_name,
              wt.table_name
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
                "source_field_name": row.get("source_field_name"),
                "selected_workspace_column_id": row.get("selected_workspace_column_id"),
                "column_name": row.get("column_name"),
                "table_name": row.get("table_name"),
            }
            for row in rows
            if row.get("selected_workspace_column_id")
        ]

    def _get_session_row(self, *, workspace_id: str, session_id: str) -> Dict[str, Any]:
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

    def _existing_results_by_source(self, *, session_id: str) -> Dict[int, str]:
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

    def _load_source_rows(self, *, session_id: str, limit: int = 2000, offset: int = 0) -> List[Dict[str, Any]]:
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
        return [self._json_safe_row(dict(row)) for row in rows]

    def _load_mapping_rows(
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

        return [self._mapping_row_to_response(self._json_safe_row(dict(row))) for row in rows]

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
        alternates = [item for item in retrieved if int(item.get("column_id") or 0) in {int(v) for v in alt_ids if _safe_int(v) is not None}]

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
    def _source_record_to_dict(record: SourceFieldRecord) -> Dict[str, Any]:
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
    def _source_row_to_response(row: Dict[str, Any]) -> Dict[str, Any]:
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

    def _session_row_to_response(self, row: Dict[str, Any]) -> Dict[str, Any]:
        safe = self._json_safe_row(dict(row))
        safe["summary_json"] = _parse_json_dict(safe.get("summary_json"))
        return safe

    @staticmethod
    def _build_summary(mappings: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        counts = {status: 0 for status in _ALLOWED_RESULT_STATUSES}
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

    def _get_mapping_row_by_id(self, *, workspace_id: str, session_id: str, mapping_id: str) -> Optional[Dict[str, Any]]:
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

    def _assert_workspace_column(self, *, workspace_id: str, workspace_column_id: int) -> None:
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

    @staticmethod
    def _find_candidate(candidates: Sequence[Dict[str, Any]], candidate_id: Any) -> Optional[Dict[str, Any]]:
        cid = _safe_int(candidate_id)
        if cid is None:
            return None
        for row in candidates:
            if _safe_int(row.get("column_id")) == cid:
                return row
        return None

    @staticmethod
    def _find_alternates(candidates: Sequence[Dict[str, Any]], candidate_ids: Sequence[Any]) -> List[Dict[str, Any]]:
        allowed = {_safe_int(value) for value in candidate_ids}
        allowed = {value for value in allowed if value is not None}
        out: list[Dict[str, Any]] = []
        for row in candidates:
            cid = _safe_int(row.get("column_id"))
            if cid is not None and cid in allowed:
                out.append(row)
            if len(out) >= 2:
                break
        return out

    @staticmethod
    def _json_safe_row(row: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, (datetime, date)):
                out[key] = value.isoformat()
            else:
                out[key] = value
        return out


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


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        parsed = int(value)
    except Exception:
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
        except Exception:
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
        except Exception:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _display_name(column_name: Any) -> str:
    text = str(column_name or "").strip()
    if text == "":
        return ""
    return " ".join(token.capitalize() for token in text.replace("-", "_").split("_") if token)


__all__ = ["ForgeMatchMappingService"]
