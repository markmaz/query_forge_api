from __future__ import annotations

import json

from app.services.forge_match.candidate_retriever import ForgeMatchCandidateRetriever
from app.services.forge_match.confidence import ForgeMatchConfidenceScorer
from app.services.forge_match.field_extractor import SourceFieldRecord
from app.services.forge_match.file_parser import ParsedSheet, ParsedWorkbook
from app.services.forge_match.mapping_service import ForgeMatchMappingService
from tests._support.fakes import FakeForgeQueryPort


class _Parser:
    def parse(self, *, file_bytes: bytes, filename: str) -> ParsedWorkbook:
        del file_bytes, filename
        return ParsedWorkbook(
            file_type="csv",
            sheets=[ParsedSheet(sheet_name="Sheet1", header_row_index=0, headers=[], rows=[])],
        )


class _Extractor:
    def extract(self, *, workbook: ParsedWorkbook):
        del workbook
        return [
            SourceFieldRecord(
                row_id="Sheet1:2",
                sheet_name="Sheet1",
                row_number=2,
                source_field_name="BirthDate",
                source_description="Student date of birth",
                source_type="date",
                source_object_name="StudentDemographics",
                sample_value="2010-02-14",
                category=None,
                normalized_search_text="BirthDate. Student date of birth",
                raw_row={"field": "BirthDate"},
            )
        ]


class _Retriever:
    def __init__(self) -> None:
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(dict(kwargs))
        return [
            {
                "column_id": 4812,
                "workspace_table_id": 100,
                "column_name": "student_birth_date",
                "display_name": "Student Birth Date",
                "table_name": "dim_student",
                "domain_id": 17,
                "domain_name": "Student Profile",
                "description": "Date of birth of the student",
                "data_type": "date",
                "semantic_type": "dimension",
                "entity": "student",
                "vector_score": 0.91,
                "lexical_score": 0.84,
                "combined_retrieval_score": 0.88,
            }
        ]


class _PipelineRetriever(ForgeMatchCandidateRetriever):
    def __init__(self, *, lexical_rows, vector_scores, **kwargs) -> None:
        super().__init__(**kwargs)
        self._lexical_rows = list(lexical_rows)
        self._vector_scores = dict(vector_scores)

    def _load_lexical_candidates(self, **kwargs):
        del kwargs
        return list(self._lexical_rows)

    def _load_vector_scores(self, **kwargs):
        del kwargs
        return dict(self._vector_scores)


class _Ranker:
    def rank(self, **kwargs):
        del kwargs
        return {
            "selected_column_id": 4812,
            "alternate_column_ids": [],
            "match_decision": "matched",
            "reason_codes": ["name_similarity", "type_compatible"],
            "explanation": "Strong name and type alignment.",
            "ambiguity_note": None,
            "llm_confidence": 0.91,
        }


class _Confidence:
    def score(self, **kwargs):
        del kwargs
        return {"confidence_score": 92, "confidence_band": "high"}


class _FirstCandidateRanker:
    def rank(self, **kwargs):
        candidates = list(kwargs["candidates"])
        selected = candidates[0] if candidates else None
        alternates = [int(row.get("column_id") or 0) for row in candidates[1:3] if int(row.get("column_id") or 0) > 0]
        return {
            "selected_column_id": int(selected.get("column_id") or 0) if selected else None,
            "alternate_column_ids": alternates,
            "match_decision": "matched" if selected else "no_confident_match",
            "reason_codes": ["name_similarity", "definition_alignment"] if selected else ["insufficient_signal"],
            "explanation": "Selected the top reranked candidate.",
            "ambiguity_note": None,
            "llm_confidence": 0.88 if selected else 0.0,
        }


def test_upload_file_creates_session_and_source_rows() -> None:
    sql = FakeForgeQueryPort()
    svc = ForgeMatchMappingService(
        sql=sql,
        parser=_Parser(),
        extractor=_Extractor(),
    )

    out = svc.upload_file(
        workspace_id="ws-1",
        created_by="user-1",
        filename="mapping.csv",
        file_bytes=b"field,desc\nvalue,test",
    )

    assert out["status"] == "uploaded"
    assert out["source_record_count"] == 1
    assert len(sql.insert_calls) == 2


def test_list_sessions_returns_paginated_rows() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": "sess-1",
                "workspace_id": "ws-1",
                "uploaded_filename": "mapping.csv",
                "file_type": "csv",
                "created_by": "user-1",
                "status": "analyzed",
                "sheet_count": 1,
                "source_record_count": 12,
                "result_count": 12,
                "accepted_count": 5,
                "manually_mapped_count": 1,
                "analysis_started_at": "2026-03-12T19:00:00",
                "analysis_completed_at": "2026-03-12T19:01:00",
                "created_at": "2026-03-12T18:59:00",
                "updated_at": "2026-03-12T19:01:00",
            }
        ],
        [{"total": 1}],
    ]
    svc = ForgeMatchMappingService(sql=sql)
    out = svc.list_sessions(workspace_id="ws-1", page=1, page_size=25, status="analyzed")
    assert out["total"] == 1
    assert out["rows"][0]["id"] == "sess-1"


def test_analyze_session_persists_mappings_and_summary() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": "sess-1",
                "workspace_id": "ws-1",
                "uploaded_filename": "mapping.csv",
                "file_type": "csv",
                "created_by": "user-1",
                "status": "uploaded",
                "sheet_count": 1,
                "source_record_count": 1,
                "summary_json": None,
                "created_at": "2026-03-12T00:00:00",
                "updated_at": "2026-03-12T00:00:00",
            }
        ],
        [
            {
                "id": 10,
                "row_id": "Sheet1:2",
                "sheet_name": "Sheet1",
                "row_number": 2,
                "source_field_name": "BirthDate",
                "source_description": "Student date of birth",
                "source_type": "date",
                "source_object_name": "StudentDemographics",
                "sample_value": "2010-02-14",
                "category": None,
                "normalized_search_text": "BirthDate. Student date of birth",
                "raw_row_json": '{"field":"BirthDate"}',
            }
        ],
        [],
        [{"cancel_requested": 0}],
        [
            {
                "mapping_id": "map-1",
                "session_id": "sess-1",
                "source_record_id": 10,
                "source_row_id": "Sheet1:2",
                "sheet_name": "Sheet1",
                "row_number": 2,
                "source_field_name": "BirthDate",
                "source_description": "Student date of birth",
                "source_type": "date",
                "source_object_name": "StudentDemographics",
                "sample_value": "2010-02-14",
                "best_match_workspace_column_id": 4812,
                "best_match_column_name": "student_birth_date",
                "best_match_table_name": "dim_student",
                "alternate_workspace_column_ids": "[]",
                "retrieved_candidates_json": (
                    '[{"column_id":4812,"column_name":"student_birth_date",'
                    '"display_name":"Student Birth Date","table_name":"dim_student"}]'
                ),
                "match_decision": "matched",
                "reason_codes_json": '["name_similarity"]',
                "explanation": "Strong name and type alignment.",
                "ambiguity_note": None,
                "llm_confidence": 0.91,
                "confidence_score": 92,
                "confidence_band": "high",
                "status": "suggested",
                "review_notes": None,
                "manually_selected_workspace_column_id": None,
                "manual_column_name": None,
                "manual_table_name": None,
                "reviewer_user_id": None,
                "reviewed_at": None,
                "created_at": "2026-03-12T00:00:00",
                "updated_at": "2026-03-12T00:00:00",
            }
        ],
    ]

    svc = ForgeMatchMappingService(
        sql=sql,
        retriever=_Retriever(),
        ranker=_Ranker(),
        confidence=_Confidence(),
    )

    out = svc.analyze_session(workspace_id="ws-1", session_id="sess-1", top_n=8)

    assert out["status"] == "analyzed"
    assert out["summary"]["total"] == 1
    assert out["summary"]["confidence_bands"]["high"] == 1
    assert out["session"]["summary_json"]["analysis_trace"]["pipeline_name"] == "forge_match_session_pipeline"
    assert len(sql.insert_calls) == 1


def test_analyze_session_passes_vertical_norm_to_retriever() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": "sess-1",
                "workspace_id": "ws-1",
                "uploaded_filename": "mapping.csv",
                "file_type": "csv",
                "created_by": "user-1",
                "status": "uploaded",
                "sheet_count": 1,
                "source_record_count": 1,
                "summary_json": None,
                "created_at": "2026-03-12T00:00:00",
                "updated_at": "2026-03-12T00:00:00",
            }
        ],
        [
            {
                "id": 10,
                "row_id": "Sheet1:2",
                "sheet_name": "Sheet1",
                "row_number": 2,
                "source_field_name": "BirthDate",
                "source_description": "Student date of birth",
                "source_type": "date",
                "source_object_name": "StudentDemographics",
                "sample_value": "2010-02-14",
                "category": None,
                "normalized_search_text": "BirthDate. Student date of birth",
                "raw_row_json": '{"field":"BirthDate"}',
            }
        ],
        [],
        [{"cancel_requested": 0}],
        [
            {
                "mapping_id": "map-1",
                "session_id": "sess-1",
                "source_record_id": 10,
                "source_row_id": "Sheet1:2",
                "sheet_name": "Sheet1",
                "row_number": 2,
                "source_field_name": "BirthDate",
                "source_description": "Student date of birth",
                "source_type": "date",
                "source_object_name": "StudentDemographics",
                "sample_value": "2010-02-14",
                "best_match_workspace_column_id": 4812,
                "best_match_column_name": "student_birth_date",
                "best_match_table_name": "dim_student",
                "alternate_workspace_column_ids": "[]",
                "retrieved_candidates_json": "[]",
                "match_decision": "matched",
                "reason_codes_json": '["name_similarity"]',
                "explanation": "Strong name and type alignment.",
                "ambiguity_note": None,
                "llm_confidence": 0.91,
                "confidence_score": 92,
                "confidence_band": "high",
                "status": "suggested",
                "review_notes": None,
                "manually_selected_workspace_column_id": None,
                "manual_column_name": None,
                "manual_table_name": None,
                "reviewer_user_id": None,
                "reviewed_at": None,
                "created_at": "2026-03-12T00:00:00",
                "updated_at": "2026-03-12T00:00:00",
            }
        ],
    ]
    retriever = _Retriever()
    svc = ForgeMatchMappingService(
        sql=sql,
        retriever=retriever,
        ranker=_Ranker(),
        confidence=_Confidence(),
    )

    out = svc.analyze_session(
        workspace_id="ws-1",
        session_id="sess-1",
        vertical_norm="education",
        top_n=8,
    )

    assert out["status"] == "analyzed"
    assert retriever.calls[0]["vertical_norm"] == "education"


def test_analyze_session_workflow_prefers_birth_date_candidate_from_shared_pipeline() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": "sess-1",
                "workspace_id": "ws-1",
                "uploaded_filename": "mapping.csv",
                "file_type": "csv",
                "created_by": "user-1",
                "status": "uploaded",
                "sheet_count": 1,
                "source_record_count": 1,
                "summary_json": None,
                "created_at": "2026-03-12T00:00:00",
                "updated_at": "2026-03-12T00:00:00",
            }
        ],
        [
            {
                "id": 10,
                "row_id": "Sheet1:2",
                "sheet_name": "Sheet1",
                "row_number": 2,
                "source_field_name": "OldestStudent",
                "source_description": "Find the oldest student by date of birth",
                "source_type": "date",
                "source_object_name": "StudentDemographics",
                "sample_value": None,
                "category": None,
                "normalized_search_text": "Find the oldest student by date of birth",
                "raw_row_json": '{"field":"OldestStudent"}',
            }
        ],
        [],
        [{"cancel_requested": 0}],
        [
            {
                "mapping_id": "map-1",
                "session_id": "sess-1",
                "source_record_id": 10,
                "source_row_id": "Sheet1:2",
                "sheet_name": "Sheet1",
                "row_number": 2,
                "source_field_name": "OldestStudent",
                "source_description": "Find the oldest student by date of birth",
                "source_type": "date",
                "source_object_name": "StudentDemographics",
                "sample_value": None,
                "best_match_workspace_column_id": 202,
                "best_match_column_name": "birth_date",
                "best_match_table_name": "dim_student",
                "alternate_workspace_column_ids": "[101]",
                "retrieved_candidates_json": "[]",
                "match_decision": "matched",
                "reason_codes_json": '["name_similarity","domain_alignment"]',
                "explanation": "Selected the top reranked candidate.",
                "ambiguity_note": None,
                "llm_confidence": 0.88,
                "confidence_score": 86,
                "confidence_band": "high",
                "status": "suggested",
                "review_notes": None,
                "manually_selected_workspace_column_id": None,
                "manual_column_name": None,
                "manual_table_name": None,
                "reviewer_user_id": None,
                "reviewed_at": None,
                "created_at": "2026-03-12T00:00:00",
                "updated_at": "2026-03-12T00:00:00",
            }
        ],
    ]

    retriever = _PipelineRetriever(
        lexical_rows=[
            {
                "workspace_column_id": 101,
                "workspace_table_id": 500,
                "column_name": "program_name",
                "description": "Student program label",
                "data_type": "string",
                "semantic_type": "dimension",
                "entity": "student",
                "table_name": "fact_student_program",
                "domain_id": 15,
                "domain_name": "Student Programs And Services",
            },
            {
                "workspace_column_id": 202,
                "workspace_table_id": 501,
                "column_name": "birth_date",
                "description": "Date of birth",
                "data_type": "date",
                "semantic_type": "dimension",
                "entity": "student",
                "table_name": "dim_student",
                "domain_id": 21,
                "domain_name": "Student Demographics And Enrollment",
            },
        ],
        vector_scores={101: 0.7, 202: 0.2},
        vector_search=object(),
        policy_adapter=None,
    )
    svc = ForgeMatchMappingService(
        sql=sql,
        retriever=retriever,
        ranker=_FirstCandidateRanker(),
        confidence=ForgeMatchConfidenceScorer(),
    )

    out = svc.analyze_session(
        workspace_id="ws-1",
        session_id="sess-1",
        vertical_norm="education",
        domain_id=15,
        top_n=8,
    )

    assert out["status"] == "analyzed"
    assert out["summary"]["total"] == 1
    payload = json.loads(str(sql.insert_calls[0].params["retrieved_candidates_json"]))
    assert payload[0]["column_id"] == 202
    assert payload[0]["capabilities"] == ["BIRTH_DATE"]
    assert payload[0]["preferred_domain_match"] is False
    assert payload[0]["policy_adjustment"] > 0
    assert payload[0]["final_score"] > payload[1]["final_score"]
    llm_payload = json.loads(str(sql.insert_calls[0].params["llm_response_json"]))
    assert llm_payload["selected_column_id"] == 202
    assert llm_payload["shared_pipeline"]["pipeline_name"] == "forge_match_row_pipeline"
    assert llm_payload["shared_pipeline"]["trace_nodes"][-1]["node"] == "score_confidence"


def test_analyze_session_workflow_prefers_school_day_flag_candidate_from_shared_pipeline() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": "sess-1",
                "workspace_id": "ws-1",
                "uploaded_filename": "mapping.csv",
                "file_type": "csv",
                "created_by": "user-1",
                "status": "uploaded",
                "sheet_count": 1,
                "source_record_count": 1,
                "summary_json": None,
                "created_at": "2026-03-12T00:00:00",
                "updated_at": "2026-03-12T00:00:00",
            }
        ],
        [
            {
                "id": 10,
                "row_id": "Sheet1:2",
                "sheet_name": "Sheet1",
                "row_number": 2,
                "source_field_name": "OffDay",
                "source_description": "School off day or no school indicator",
                "source_type": "boolean",
                "source_object_name": "AcademicCalendar",
                "sample_value": "true",
                "category": None,
                "normalized_search_text": "school off day no school indicator",
                "raw_row_json": '{"field":"OffDay"}',
            }
        ],
        [],
        [{"cancel_requested": 0}],
        [
            {
                "mapping_id": "map-1",
                "session_id": "sess-1",
                "source_record_id": 10,
                "source_row_id": "Sheet1:2",
                "sheet_name": "Sheet1",
                "row_number": 2,
                "source_field_name": "OffDay",
                "source_description": "School off day or no school indicator",
                "source_type": "boolean",
                "source_object_name": "AcademicCalendar",
                "sample_value": "true",
                "best_match_workspace_column_id": 302,
                "best_match_column_name": "is_school_day",
                "best_match_table_name": "dim_calendar",
                "alternate_workspace_column_ids": "[301]",
                "retrieved_candidates_json": "[]",
                "match_decision": "matched",
                "reason_codes_json": '["name_similarity","domain_alignment"]',
                "explanation": "Selected the top reranked candidate.",
                "ambiguity_note": None,
                "llm_confidence": 0.88,
                "confidence_score": 83,
                "confidence_band": "high",
                "status": "suggested",
                "review_notes": None,
                "manually_selected_workspace_column_id": None,
                "manual_column_name": None,
                "manual_table_name": None,
                "reviewer_user_id": None,
                "reviewed_at": None,
                "created_at": "2026-03-12T00:00:00",
                "updated_at": "2026-03-12T00:00:00",
            }
        ],
    ]

    retriever = _PipelineRetriever(
        lexical_rows=[
            {
                "workspace_column_id": 301,
                "workspace_table_id": 590,
                "column_name": "program_name",
                "description": "Program label",
                "data_type": "string",
                "semantic_type": "dimension",
                "entity": "student",
                "table_name": "fact_student_program",
                "domain_id": 15,
                "domain_name": "Student Programs And Services",
            },
            {
                "workspace_column_id": 302,
                "workspace_table_id": 536,
                "column_name": "is_school_day",
                "description": "Flag for whether school is in session",
                "data_type": "boolean",
                "semantic_type": "dimension",
                "entity": "calendar",
                "table_name": "dim_calendar",
                "domain_id": 6,
                "domain_name": "Academic Calendar And Scheduling",
            },
        ],
        vector_scores={301: 0.72, 302: 0.18},
        vector_search=object(),
        policy_adapter=None,
    )
    svc = ForgeMatchMappingService(
        sql=sql,
        retriever=retriever,
        ranker=_FirstCandidateRanker(),
        confidence=ForgeMatchConfidenceScorer(),
    )

    out = svc.analyze_session(
        workspace_id="ws-1",
        session_id="sess-1",
        vertical_norm="education",
        top_n=8,
    )

    assert out["status"] == "analyzed"
    payload = json.loads(str(sql.insert_calls[0].params["retrieved_candidates_json"]))
    assert payload[0]["column_id"] == 302
    assert payload[0]["capabilities"] == ["SCHOOL_DAY_FLAG"]
    assert payload[0]["policy_adjustment"] > 0
    assert payload[0]["final_score"] > payload[1]["final_score"]
    llm_payload = json.loads(str(sql.insert_calls[0].params["llm_response_json"]))
    assert llm_payload["selected_column_id"] == 302
    assert llm_payload["shared_pipeline"]["trace_nodes"][-1]["node"] == "score_confidence"


def test_patch_mappings_accepts_remap_action() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": "sess-1",
                "workspace_id": "ws-1",
                "uploaded_filename": "mapping.csv",
                "file_type": "csv",
                "created_by": "user-1",
                "status": "analyzed",
                "sheet_count": 1,
                "source_record_count": 1,
                "summary_json": None,
                "created_at": "2026-03-12T00:00:00",
                "updated_at": "2026-03-12T00:00:00",
            }
        ],
        [{"id": "map-1", "session_id": "sess-1"}],
        [{"id": 888}],
    ]
    sql.write_responses = [1]

    svc = ForgeMatchMappingService(sql=sql)
    out = svc.patch_mappings(
        workspace_id="ws-1",
        session_id="sess-1",
        reviewer_user_id="admin-1",
        updates=[
            {
                "mapping_id": "map-1",
                "action": "remap",
                "manually_selected_workspace_column_id": 888,
                "review_notes": "Corrected to canonical column",
            }
        ],
    )

    assert out["updated"] == 1
    assert out["rows"][0]["status"] == "manually_mapped"
    assert sql.write_calls


def test_start_analyze_session_job_sets_queued_status() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": "sess-1",
                "workspace_id": "ws-1",
                "uploaded_filename": "mapping.csv",
                "file_type": "csv",
                "created_by": "user-1",
                "status": "uploaded",
                "source_record_count": 12,
                "summary_json": None,
                "created_at": "2026-03-12T00:00:00",
                "updated_at": "2026-03-12T00:00:00",
            }
        ]
    ]
    svc = ForgeMatchMappingService(sql=sql)
    out = svc.start_analyze_session_job(workspace_id="ws-1", session_id="sess-1", top_n=8)
    assert out["status"] == "queued"
    assert out["source_total"] == 12
    assert sql.write_calls


def test_get_analysis_status_serializes_progress() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": "sess-1",
                "analysis_job_id": "job-1",
                "workspace_id": "ws-1",
                "uploaded_filename": "mapping.csv",
                "status": "analyzing",
                "source_record_count": 10,
                "analyzed_count": 4,
                "skipped_count": 1,
                "failed_count": 0,
                "cancel_requested": 0,
                "analysis_started_at": "2026-03-12T00:00:00",
                "analysis_completed_at": None,
            }
        ]
    ]
    svc = ForgeMatchMappingService(sql=sql)
    out = svc.get_analysis_status(workspace_id="ws-1", job_id="job-1")
    assert out["job_id"] == "job-1"
    assert out["source_total"] == 10
    assert out["source_done"] == 4
    assert out["progress_pct"] == 50.0


def test_cancel_analysis_job_marks_row_canceled() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": "sess-1",
                "analysis_job_id": "job-1",
                "workspace_id": "ws-1",
                "uploaded_filename": "mapping.csv",
                "status": "analyzing",
                "source_record_count": 10,
                "analyzed_count": 2,
                "skipped_count": 0,
                "failed_count": 0,
                "cancel_requested": 0,
            }
        ],
        [
            {
                "id": "sess-1",
                "analysis_job_id": "job-1",
                "workspace_id": "ws-1",
                "uploaded_filename": "mapping.csv",
                "status": "canceled",
                "source_record_count": 10,
                "analyzed_count": 2,
                "skipped_count": 0,
                "failed_count": 0,
                "cancel_requested": 1,
            }
        ],
    ]
    svc = ForgeMatchMappingService(sql=sql)
    out = svc.cancel_analysis_job(workspace_id="ws-1", job_id="job-1")
    assert out["canceled"] is True
    assert out["status"] == "canceled"
    assert sql.write_calls


def test_get_session_surfaces_shared_pipeline_debug_for_mapping_rows() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": "sess-1",
                "workspace_id": "ws-1",
                "uploaded_filename": "mapping.csv",
                "file_type": "csv",
                "created_by": "user-1",
                "status": "analyzed",
                "sheet_count": 1,
                "source_record_count": 1,
                "summary_json": None,
                "created_at": "2026-03-12T00:00:00",
                "updated_at": "2026-03-12T00:00:00",
            }
        ],
        [
            {
                "id": 10,
                "row_id": "Sheet1:2",
                "sheet_name": "Sheet1",
                "row_number": 2,
                "source_field_name": "BirthDate",
                "source_description": "Student date of birth",
                "source_type": "date",
                "source_object_name": "StudentDemographics",
                "sample_value": "2010-02-14",
                "category": None,
                "normalized_search_text": "BirthDate. Student date of birth",
                "raw_row_json": '{"field":"BirthDate"}',
                "created_at": "2026-03-12T00:00:00",
            }
        ],
        [
            {
                "mapping_id": "map-1",
                "session_id": "sess-1",
                "source_record_id": 10,
                "source_row_id": "Sheet1:2",
                "sheet_name": "Sheet1",
                "row_number": 2,
                "source_field_name": "BirthDate",
                "source_description": "Student date of birth",
                "source_type": "date",
                "source_object_name": "StudentDemographics",
                "sample_value": "2010-02-14",
                "best_match_workspace_column_id": 4812,
                "best_match_column_name": "student_birth_date",
                "best_match_table_name": "dim_student",
                "alternate_workspace_column_ids": "[]",
                "retrieved_candidates_json": '[{"column_id":4812,"column_name":"student_birth_date"}]',
                "llm_response_json": (
                    '{"selected_column_id":4812,'
                    '"shared_pipeline":{"pipeline_name":"forge_match_row_pipeline",'
                    '"trace_nodes":[{"node":"dispatch_candidate_pipeline"},{"node":"rank_candidates"}]}}'
                ),
                "match_decision": "matched",
                "reason_codes_json": '["name_similarity"]',
                "explanation": "Strong name and type alignment.",
                "ambiguity_note": None,
                "llm_confidence": 0.91,
                "confidence_score": 92,
                "confidence_band": "high",
                "status": "suggested",
                "review_notes": None,
                "manually_selected_workspace_column_id": None,
                "manual_column_name": None,
                "manual_table_name": None,
                "reviewer_user_id": None,
                "reviewed_at": None,
                "created_at": "2026-03-12T00:00:00",
                "updated_at": "2026-03-12T00:00:00",
            }
        ],
    ]

    svc = ForgeMatchMappingService(sql=sql)
    out = svc.get_session(workspace_id="ws-1", session_id="sess-1")

    assert out["mappings"][0]["llm_result"]["selected_column_id"] == 4812
    assert out["mappings"][0]["shared_pipeline"]["pipeline_name"] == "forge_match_row_pipeline"
    assert out["mappings"][0]["shared_pipeline"]["trace_nodes"][1]["node"] == "rank_candidates"
