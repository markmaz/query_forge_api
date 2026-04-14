from __future__ import annotations

import pytest

from app.services.forge_match.candidate_retriever import ForgeMatchCandidateRetriever, _vector_query_text
from app.services.forge_match.field_extractor import SourceFieldRecord


class _Retriever(ForgeMatchCandidateRetriever):
    def __init__(self, *, lexical_rows, vector_scores, hydrated_rows=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._lexical_rows = list(lexical_rows)
        self._vector_scores = dict(vector_scores)
        self._hydrated_rows = list(hydrated_rows or [])

    def _load_lexical_candidates(self, **kwargs):
        del kwargs
        return list(self._lexical_rows)

    def _load_vector_scores(self, **kwargs):
        del kwargs
        return dict(self._vector_scores)

    def _load_candidates_by_ids(self, **kwargs):
        del kwargs
        return list(self._hydrated_rows)


def test_retrieve_applies_shared_pipeline_rerank() -> None:
    retriever = _Retriever(
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
    source = SourceFieldRecord(
        row_id="Sheet1:2",
        sheet_name="Sheet1",
        row_number=2,
        source_field_name="OldestStudent",
        source_description="Find the oldest student by date of birth",
        source_type="date",
        source_object_name="StudentDemographics",
        sample_value=None,
        category=None,
        normalized_search_text="Find the oldest student by date of birth",
        raw_row={},
    )

    rows = retriever.retrieve(
        workspace_id="ws-1",
        source_record=source,
        top_n=5,
    )

    assert rows[0]["column_id"] == 202
    assert rows[0]["capabilities"] == ["BIRTH_DATE"]
    assert rows[0]["final_score"] > rows[1]["final_score"]
    assert retriever.last_pipeline_context is not None
    assert [entry["node"] for entry in retriever.last_pipeline_context.trace_nodes] == [
        "normalize_text",
        "retrieve_candidates",
        "extract_signals",
        "resolve_capabilities",
        "apply_policy_rerank",
    ]


def test_retrieve_preferred_domain_is_soft_bias_not_hard_filter() -> None:
    retriever = _Retriever(
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
        vector_scores={101: 0.72, 202: 0.18},
        vector_search=object(),
        policy_adapter=None,
    )
    source = SourceFieldRecord(
        row_id="Sheet1:2",
        sheet_name="Sheet1",
        row_number=2,
        source_field_name="BirthDate",
        source_description="Student date of birth",
        source_type="date",
        source_object_name="StudentProgram",
        sample_value=None,
        category=None,
        normalized_search_text="BirthDate. Student date of birth",
        raw_row={},
    )

    rows = retriever.retrieve(
        workspace_id="ws-1",
        source_record=source,
        top_n=5,
        domain_id=15,
    )

    assert rows[0]["column_id"] == 202
    assert rows[0]["domain_id"] == 21
    assert rows[0]["preferred_domain_match"] is False
    retrieval_debug = retriever.last_pipeline_context.get_artifact(
        "candidate_set",
        node_name="forge_match_candidate_pipeline",
    ).retrieval_debug
    assert retrieval_debug["preferred_domain_id"] == 15
    assert retrieval_debug["search_scope"] == "workspace_global"


def test_retrieve_preferred_domain_does_not_change_scores() -> None:
    retriever = _Retriever(
        lexical_rows=[
            {
                "workspace_column_id": 301,
                "workspace_table_id": 550,
                "column_name": "birth_date",
                "description": "Birth date on program snapshot",
                "data_type": "date",
                "semantic_type": "dimension",
                "entity": "student",
                "table_name": "fact_student_program",
                "domain_id": 15,
                "domain_name": "Student Programs And Services",
            },
            {
                "workspace_column_id": 302,
                "workspace_table_id": 551,
                "column_name": "birth_date",
                "description": "Birth date on demographic profile",
                "data_type": "date",
                "semantic_type": "dimension",
                "entity": "student",
                "table_name": "dim_student",
                "domain_id": 21,
                "domain_name": "Student Demographics And Enrollment",
            },
        ],
        vector_scores={301: 0.51, 302: 0.51},
        vector_search=object(),
        policy_adapter=None,
    )
    source = SourceFieldRecord(
        row_id="Sheet1:2",
        sheet_name="Sheet1",
        row_number=2,
        source_field_name="BirthDate",
        source_description="Birth date",
        source_type="date",
        source_object_name="StudentProfile",
        sample_value=None,
        category=None,
        normalized_search_text="BirthDate. Birth date",
        raw_row={},
    )

    rows = retriever.retrieve(
        workspace_id="ws-1",
        source_record=source,
        top_n=5,
        domain_id=15,
    )
    rows_without_domain = retriever.retrieve(
        workspace_id="ws-1",
        source_record=source,
        top_n=5,
    )

    assert rows[0]["column_id"] == rows_without_domain[0]["column_id"]
    assert rows[0]["preferred_domain_match"] is False
    assert rows[0]["domain_preference_adjustment"] == 0.0


def test_retrieve_hydrates_vector_only_candidates_even_when_lexical_rows_exist() -> None:
    retriever = _Retriever(
        lexical_rows=[
            {
                "workspace_column_id": 401,
                "workspace_table_id": 700,
                "column_name": "full_name",
                "description": "Student full name",
                "data_type": "string",
                "semantic_type": "dimension",
                "entity": "student",
                "table_name": "dim_student_profile",
                "domain_id": 22,
                "domain_name": "Student Profile",
            },
        ],
        vector_scores={402: 0.95},
        hydrated_rows=[
            {
                "workspace_column_id": 402,
                "workspace_table_id": 701,
                "column_name": "first_name",
                "description": "Student given name",
                "data_type": "string",
                "semantic_type": "dimension",
                "entity": "student",
                "table_name": "dim_student",
                "domain_id": 21,
                "domain_name": "Student Demographics And Enrollment",
            },
        ],
        vector_search=object(),
        policy_adapter=None,
    )
    source = SourceFieldRecord(
        row_id="Sheet1:3",
        sheet_name="Sheet1",
        row_number=3,
        source_field_name="FirstName",
        source_description="Student first name",
        source_type="string",
        source_object_name="StudentDemographics",
        sample_value=None,
        category=None,
        normalized_search_text="FirstName. Student first name",
        raw_row={},
    )

    rows = retriever.retrieve(
        workspace_id="ws-1",
        source_record=source,
        top_n=5,
    )

    assert rows[0]["column_id"] == 402
    assert {row["column_id"] for row in rows} == {401, 402}


def test_vector_query_text_expands_birth_date_aliases() -> None:
    source = SourceFieldRecord(
        row_id="Sheet1:4",
        sheet_name="Sheet1",
        row_number=4,
        source_field_name="BirthDate",
        source_description="Student birthday value",
        source_type="date",
        source_object_name="StudentDemographics",
        sample_value=None,
        category=None,
        normalized_search_text="BirthDate. Student birthday value",
        raw_row={},
    )

    query_text = _vector_query_text(source)

    assert "Aliases: birth date, date of birth, birthdate, dob" in query_text
    assert "Object: StudentDemographics" in query_text


def test_load_vector_scores_falls_back_on_expected_runtime_errors() -> None:
    class _Vector:
        def search(self, **kwargs):
            del kwargs
            raise RuntimeError("vector unavailable")

    retriever = ForgeMatchCandidateRetriever(vector_search=_Vector())
    source = SourceFieldRecord(
        row_id="Sheet1:4",
        sheet_name="Sheet1",
        row_number=4,
        source_field_name="BirthDate",
        source_description="Student birthday value",
        source_type="date",
        source_object_name="StudentDemographics",
        sample_value=None,
        category=None,
        normalized_search_text="BirthDate. Student birthday value",
        raw_row={},
    )

    assert retriever._load_vector_scores(workspace_id="ws-1", source_record=source, domain_id=None, limit=10) == {}


def test_load_vector_scores_surfaces_unexpected_errors() -> None:
    class _Vector:
        def search(self, **kwargs):
            del kwargs
            raise AssertionError("unexpected vector bug")

    retriever = ForgeMatchCandidateRetriever(vector_search=_Vector())
    source = SourceFieldRecord(
        row_id="Sheet1:4",
        sheet_name="Sheet1",
        row_number=4,
        source_field_name="BirthDate",
        source_description="Student birthday value",
        source_type="date",
        source_object_name="StudentDemographics",
        sample_value=None,
        category=None,
        normalized_search_text="BirthDate. Student birthday value",
        raw_row={},
    )

    with pytest.raises(AssertionError, match="unexpected vector bug"):
        retriever._load_vector_scores(workspace_id="ws-1", source_record=source, domain_id=None, limit=10)
