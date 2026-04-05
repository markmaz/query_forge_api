from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.forge_match.pipeline_adapters import (
    ForgeMatchSessionExecutionAdapter,
    ForgeMatchSessionFinalizationAdapter,
    ForgeMatchSessionPreparationAdapter,
)
from app.services.forge_match.pipeline_definition import build_forge_match_session_pipeline_definition
from app.services.forge_match.session_pipeline_artifacts import ForgeMatchSessionResultArtifact
from app.services.forge_match.session_reader import ForgeMatchSessionReader, json_safe_row
from app.services.shared_ai.artifacts import MatchOutcomeArtifact, PersistenceArtifact
from app.services.shared_ai.context import PipelineContext
from app.services.shared_ai.executor import PipelineExecutor
from app.services.shared_ai.tracing import serialize_pipeline_context

logger = logging.getLogger(__name__)

_TERMINAL_SESSION_STATUSES = {"uploaded", "analyzed", "failed", "canceled", "cancelled"}


class ForgeMatchSessionJobCoordinator:
    def __init__(
        self,
        *,
        sql: ForgeQueryPort,
        session_reader: ForgeMatchSessionReader,
        pipeline_executor: PipelineExecutor,
        run_row_pipeline: Callable[..., tuple[MatchOutcomeArtifact, dict[str, Any], PersistenceArtifact]],
        existing_results_by_source: Callable[..., Dict[int, str]],
        clear_results: Callable[..., None],
        persist_failure_result: Callable[..., None],
        persist_session_analysis_trace: Callable[..., Dict[str, Any]],
    ) -> None:
        self._sql = sql
        self._session_reader = session_reader
        self._pipeline_executor = pipeline_executor
        self._run_row_pipeline = run_row_pipeline
        self._existing_results_by_source = existing_results_by_source
        self._clear_results = clear_results
        self._persist_failure_result = persist_failure_result
        self._persist_session_analysis_trace = persist_session_analysis_trace
        self._extended_progress_columns_supported = True

    def analyze_session(
        self,
        *,
        workspace_id: str,
        session_id: str,
        vertical_norm: Optional[str] = None,
        domain_id: Optional[int] = None,
        top_n: int = 8,
        force: bool = False,
        llm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self.run_analyze_job(
            workspace_id=workspace_id,
            session_id=session_id,
            vertical_norm=vertical_norm,
            domain_id=domain_id,
            top_n=top_n,
            force=force,
            job_id=None,
            llm_id=llm_id,
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
        llm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        session = self._session_reader.get_session_row(workspace_id=workspace_id, session_id=session_id)

        status = str(session.get("status") or "").strip().lower()
        existing_job_id = _to_text_or_none(session.get("analysis_job_id"))
        if status in {"queued", "analyzing"} and existing_job_id:
            return {
                "job_id": existing_job_id,
                "session_id": session_id,
                "workspace_id": workspace_id,
                "status": status,
                "message": "Analyze run already in progress",
            }

        job_id = str(uuid.uuid4())
        source_total = int(session.get("source_record_count") or 0)
        self.update_session_progress(
            session_id=session_id,
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
            "session_id": session_id,
            "workspace_id": workspace_id,
            "status": "queued",
            "source_total": source_total,
            "message": "ForgeMatch analysis queued",
            "top_n": max(3, int(top_n or 8)),
            "domain_id": int(domain_id) if domain_id is not None else None,
            "vertical_norm": _to_text_or_none(vertical_norm),
            "force": bool(force),
            "llm_id": int(llm_id) if llm_id is not None else None,
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
        llm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        context = PipelineContext(
            pipeline_name="forge_match_session_pipeline",
            trace_id=f"forge_match_session:{uuid.uuid4().hex}",
            workspace_id=workspace_id,
            user_id=None,
            vertical_norm=str(vertical_norm or "generic"),
            request={
                "session_id": session_id,
                "job_id": _to_text_or_none(job_id),
                "top_n": max(3, int(top_n or 8)),
                "vertical_norm": _to_text_or_none(vertical_norm),
                "domain_id": int(domain_id) if domain_id is not None else None,
                "preferred_domain_id": int(domain_id) if domain_id is not None else None,
                "force": bool(force),
                "llm_id": int(llm_id) if llm_id is not None else None,
            },
        )

        try:
            result = self._run_session_pipeline(context)
            return dict(result.payload)
        except Exception as exc:
            logger.exception("ForgeMatch analyze session failed session_id=%s", session_id)
            progress = context.metadata.get("session_progress") or {}
            analyzed = int(progress.get("analyzed_count") or 0)
            skipped = int(progress.get("skipped_count") or 0)
            failed = int(progress.get("failed_count") or 0)
            source_total = int(progress.get("source_total") or 0)
            self.update_session_progress(
                session_id=session_id,
                status="failed",
                job_id=job_id,
                source_total=source_total,
                source_done=analyzed,
                source_skipped=skipped,
                source_failed=failed + 1,
                current_phase="failed",
                current_source_row_id=None,
                analysis_error=str(exc)[:2000],
                completed_at=datetime.now(timezone.utc),
            )
            raise

    def get_analysis_status(self, *, workspace_id: str, job_id: str) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM forge_match_session
            WHERE workspace_id = :workspace_id
              AND (analysis_job_id = :job_id OR id = :job_id)
            ORDER BY CASE WHEN analysis_job_id = :job_id THEN 0 ELSE 1 END
            LIMIT 1
            """,
            {"workspace_id": workspace_id, "job_id": job_id},
        )
        if not rows:
            raise ForgeError("ForgeMatch run not found", status_code=404)
        return self.serialize_analysis_status(json_safe_row(dict(rows[0])))

    def cancel_analysis_job(self, *, workspace_id: str, job_id: str) -> Dict[str, Any]:
        status = self.get_analysis_status(workspace_id=workspace_id, job_id=job_id)
        current_status = str(status.get("status") or "").lower()
        if current_status in _TERMINAL_SESSION_STATUSES:
            return {
                "job_id": status.get("job_id"),
                "session_id": status.get("session_id"),
                "canceled": False,
                "status": current_status,
                "message": "Run already in terminal status",
            }

        session_id = str(status.get("session_id") or "")
        self.update_session_progress(
            session_id=session_id,
            status="canceled",
            job_id=str(status.get("job_id") or job_id),
            source_total=int(status.get("source_total") or 0),
            source_done=int(status.get("source_done") or 0),
            source_skipped=int(status.get("source_skipped") or 0),
            source_failed=int(status.get("source_failed") or 0),
            current_phase="canceled",
            current_source_row_id=status.get("current_source_row_id"),
            analysis_error="Canceled by operator",
            cancel_requested=True,
            completed_at=datetime.now(timezone.utc),
        )
        refreshed = self.get_analysis_status(workspace_id=workspace_id, job_id=job_id)
        return {
            "job_id": refreshed.get("job_id"),
            "session_id": refreshed.get("session_id"),
            "canceled": True,
            "status": str(refreshed.get("status") or "").lower(),
            "message": "Cancellation requested",
        }

    def list_analysis_history(self, *, workspace_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM forge_match_session
            WHERE workspace_id = :workspace_id
              AND analysis_started_at IS NOT NULL
            ORDER BY analysis_started_at DESC
            LIMIT :limit
            """,
            {"workspace_id": workspace_id, "limit": max(1, min(200, int(limit or 20)))},
        )
        return [self.serialize_analysis_status(json_safe_row(dict(row))) for row in rows]

    def mark_enqueue_failed(
        self,
        *,
        session_id: str,
        job_id: str,
        source_total: int,
        error_message: str,
    ) -> None:
        self.update_session_progress(
            session_id=session_id,
            status="failed",
            job_id=job_id,
            source_total=int(source_total or 0),
            source_done=0,
            source_skipped=0,
            source_failed=1,
            current_phase="failed",
            current_source_row_id=None,
            analysis_error=str(error_message or "Failed to enqueue ForgeMatch analysis task")[:2000],
            completed_at=None,
        )

    def is_cancel_requested(self, *, session_id: str) -> bool:
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

    def update_session_progress(
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
            "last_heartbeat_at": datetime.now(timezone.utc),
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
    def serialize_analysis_status(row: Dict[str, Any]) -> Dict[str, Any]:
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

    def _run_session_pipeline(self, context: PipelineContext) -> ForgeMatchSessionResultArtifact:
        definition = build_forge_match_session_pipeline_definition(
            preparation_adapter=ForgeMatchSessionPreparationAdapter(
                load_session=self._session_reader.get_session_row,
                load_source_rows=self._session_reader.load_source_rows,
                existing_results_by_source=self._existing_results_by_source,
                clear_results=self._clear_results,
                update_progress=self.update_session_progress,
            ),
            execution_adapter=ForgeMatchSessionExecutionAdapter(
                is_cancel_requested=self.is_cancel_requested,
                update_progress=self.update_session_progress,
                run_row_pipeline=self._run_row_pipeline,
                persist_failure_result=self._persist_failure_result,
            ),
            finalization_adapter=ForgeMatchSessionFinalizationAdapter(
                load_mapping_rows=self._session_reader.load_mapping_rows,
                build_summary=self._session_reader.build_summary,
                update_progress=self.update_session_progress,
            ),
        )
        context = self._pipeline_executor.execute(definition, context)
        trace_snapshot = serialize_pipeline_context(context)
        work = context.get_artifact("session_work", node_name="forge_match_session_pipeline")
        result = context.get_artifact("session_result", node_name="forge_match_session_pipeline")
        if not isinstance(result, ForgeMatchSessionResultArtifact):
            raise TypeError("forge_match_session_pipeline expected ForgeMatchSessionResultArtifact.")
        if hasattr(work, "session") and isinstance(getattr(work, "session"), dict):
            summary_json = self._persist_session_analysis_trace(
                session_id=str(context.request.get("session_id") or ""),
                current_summary=getattr(work, "session").get("summary_json"),
                trace_snapshot=trace_snapshot,
            )
            payload_session = result.payload.get("session")
            if isinstance(payload_session, dict):
                payload_session["summary_json"] = summary_json
        return result


def _to_text_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["ForgeMatchSessionJobCoordinator"]
