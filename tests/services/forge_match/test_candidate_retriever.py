from __future__ import annotations

from app.services.forge_match.candidate_retriever import ForgeMatchCandidateRetriever
from app.services.forge_match.field_extractor import SourceFieldRecord


class _Retriever(ForgeMatchCandidateRetriever):
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


class _PolicyService:
    def get_applicable_policies(self, *, workspace_id: str, vertical_norm: str, base_domain_id: int):
        assert workspace_id == "ws-1"
        assert vertical_norm == "education"
        assert base_domain_id in {15, 21}
        return [
            {
                "policy_key": "prefer_birth_date",
                "stop_on_match": False,
                "policy_json": {
                    "version": 1,
                    "when_signals_all": [],
                    "when_signals_any": [],
                    "exclude_signals_any": [],
                    "prefer_capabilities": ["BIRTH_DATE"],
                    "penalize_missing": ["BIRTH_DATE"],
                    "require_for_bonus": [],
                    "boost": 0.3,
                    "penalty": 0.3,
                    "max_effect": 0.3,
                },
            }
        ]


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
    retriever._policy_adapter._policies = _PolicyService()
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
        vertical_norm="education",
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
