from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain_resolver import DomainResolver
from app.services.forge_match.artifact_service import ForgeMatchArtifactService
from app.services.forge_match.candidate_retriever import ForgeMatchCandidateRetriever
from app.services.forge_match.confidence import ForgeMatchConfidenceScorer
from app.services.forge_match.export_service import ForgeMatchExportService
from app.services.forge_match.field_extractor import ForgeMatchFieldExtractor
from app.services.forge_match.file_parser import ForgeMatchFileParser
from app.services.forge_match.llm_ranker import ForgeMatchLLMRanker
from app.services.forge_match.mapping_store import ForgeMatchMappingStore
from app.services.forge_match.row_pipeline_runner import ForgeMatchRowPipelineRunner
from app.services.forge_match.session_job_coordinator import ForgeMatchSessionJobCoordinator
from app.services.forge_match.session_reader import ForgeMatchSessionReader
from app.services.forge_match.session_store import ForgeMatchSessionStore
from app.services.forge_match.view_draft_sql import ForgeMatchViewDraftBuilder
from app.services.shared_ai.executor import PipelineExecutor
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder

_ALLOWED_RESULT_STATUSES = {"suggested", "accepted", "rejected", "needs_review", "manually_mapped"}


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
        self._pipeline_executor = PipelineExecutor()
        self._session_reader = ForgeMatchSessionReader(
            sql=self._sql,
            allowed_result_statuses=_ALLOWED_RESULT_STATUSES,
        )
        self._session_store = ForgeMatchSessionStore(
            sql=self._sql,
            session_reader=self._session_reader,
        )
        self._mapping_store = ForgeMatchMappingStore(
            sql=self._sql,
            session_reader=self._session_reader,
            allowed_result_statuses=_ALLOWED_RESULT_STATUSES,
        )
        self._row_pipeline_runner = ForgeMatchRowPipelineRunner(
            pipeline_executor=self._pipeline_executor,
            retriever=self._retriever,
            ranker=self._ranker,
            confidence=self._confidence,
            persist_result=self._upsert_mapping_result,
        )
        self._view_draft_builder = ForgeMatchViewDraftBuilder(
            sql=self._sql,
            resolver_factory=lambda workspace_id: DomainResolver(workspace_id=workspace_id, sql=self._sql),
        )
        self._artifact_service = ForgeMatchArtifactService(
            session_reader=self._session_reader,
            view_draft_builder=self._view_draft_builder,
            exporter=self._exporter,
            workspace_context_builder_factory=lambda: WorkspaceSqlContextBuilder(),
        )
        self._session_jobs = ForgeMatchSessionJobCoordinator(
            sql=self._sql,
            session_reader=self._session_reader,
            pipeline_executor=self._pipeline_executor,
            run_row_pipeline=self._row_pipeline_runner.run,
            existing_results_by_source=self._session_store.existing_results_by_source,
            clear_results=self._session_store.clear_session_results,
            persist_failure_result=self._upsert_mapping_result,
            persist_session_analysis_trace=self._session_store.persist_session_analysis_trace,
        )

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
        return self._session_store.list_sessions(
            workspace_id=ws,
            page=page,
            page_size=page_size,
            status=status,
            q=q,
        )

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
        self._session_store.create_uploaded_session(
            session_id=session_id,
            workspace_id=ws,
            created_by=user,
            upload_name=upload_name,
            file_type=parsed.file_type,
            sheet_names=[sheet.sheet_name for sheet in parsed.sheets],
            records=records,
            created_at=now,
        )

        return {
            "session_id": session_id,
            "workspace_id": ws,
            "uploaded_filename": upload_name,
            "file_type": parsed.file_type,
            "status": "uploaded",
            "sheet_count": len(parsed.sheets),
            "source_record_count": len(records),
            "source_preview": [self._session_reader.source_record_to_dict(row) for row in records[:25]],
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
        llm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        return self._session_jobs.analyze_session(
            workspace_id=ws,
            session_id=sid,
            vertical_norm=vertical_norm,
            domain_id=domain_id,
            top_n=top_n,
            force=force,
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
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        return self._session_jobs.start_analyze_session_job(
            workspace_id=ws,
            session_id=sid,
            top_n=top_n,
            domain_id=domain_id,
            vertical_norm=vertical_norm,
            force=force,
            llm_id=llm_id,
        )

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
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        return self._session_jobs.run_analyze_job(
            workspace_id=ws,
            session_id=sid,
            vertical_norm=vertical_norm,
            domain_id=domain_id,
            top_n=top_n,
            force=force,
            job_id=job_id,
            llm_id=llm_id,
        )

    def get_analysis_status(self, *, workspace_id: str, job_id: str) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        jid = _required_text(job_id, "job_id")
        return self._session_jobs.get_analysis_status(workspace_id=ws, job_id=jid)

    def cancel_analysis_job(self, *, workspace_id: str, job_id: str) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        jid = _required_text(job_id, "job_id")
        return self._session_jobs.cancel_analysis_job(workspace_id=ws, job_id=jid)

    def list_analysis_history(self, *, workspace_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        ws = _required_text(workspace_id, "workspace_id")
        return self._session_jobs.list_analysis_history(workspace_id=ws, limit=limit)

    def mark_enqueue_failed(
        self,
        *,
        session_id: str,
        job_id: str,
        source_total: int,
        error_message: str,
    ) -> None:
        self._session_jobs.mark_enqueue_failed(
            session_id=_required_text(session_id, "session_id"),
            job_id=_required_text(job_id, "job_id"),
            source_total=source_total,
            error_message=error_message,
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

        session = self._session_reader.get_session_row(workspace_id=ws, session_id=sid)
        source_records = self._session_reader.load_source_rows(
            session_id=sid,
            limit=max(1, min(1000, int(source_limit))),
            offset=max(0, int(source_offset)),
        )
        mappings = self._session_reader.load_mapping_rows(
            workspace_id=ws,
            session_id=sid,
            limit=max(1, min(2000, int(mapping_limit))),
            offset=max(0, int(mapping_offset)),
        )
        summary = self._session_reader.build_summary(mappings)

        return {
            "session": session,
            "source_records": [self._session_reader.source_row_to_response(row) for row in source_records],
            "mappings": mappings,
            "summary": summary,
        }

    def delete_session(self, *, workspace_id: str, session_id: str) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        return self._session_store.delete_session(workspace_id=ws, session_id=sid)

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
        return self._mapping_store.patch_mappings(
            workspace_id=ws,
            session_id=sid,
            reviewer_user_id=reviewer,
            updates=updates,
        )

    def export_session(
        self,
        *,
        workspace_id: str,
        session_id: str,
        export_format: str,
    ) -> tuple[bytes, str, str]:
        return self._artifact_service.export_session(
            workspace_id=workspace_id,
            session_id=session_id,
            export_format=export_format,
        )

    def create_view_draft(self, *, workspace_id: str, session_id: str, name: Optional[str] = None) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        return self._artifact_service.create_view_draft(
            workspace_id=ws,
            session_id=sid,
            name=name,
        )

    def execute_view_draft_sql(
        self,
        *,
        workspace_id: str,
        session_id: str,
        sql: str,
        catalog_name: Optional[str] = None,
        schema_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        return self._artifact_service.execute_view_draft_sql(
            workspace_id=ws,
            session_id=sid,
            sql=sql,
            catalog_name=catalog_name,
            schema_name=schema_name,
        )

    def create_domain_draft(self, *, workspace_id: str, session_id: str, name: Optional[str] = None) -> Dict[str, Any]:
        ws = _required_text(workspace_id, "workspace_id")
        sid = _required_text(session_id, "session_id")
        return self._artifact_service.create_domain_draft(
            workspace_id=ws,
            session_id=sid,
            name=name,
        )

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
        self._mapping_store.upsert_mapping_result(
            session_id=session_id,
            source_record_id=source_record_id,
            selected=selected,
            alternates=alternates,
            candidates=candidates,
            llm_rank=llm_rank,
            confidence=confidence,
        )

def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if text == "":
        raise ForgeError(f"{field} is required", status_code=400)
    return text


__all__ = ["ForgeMatchMappingService"]
