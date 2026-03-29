from __future__ import annotations

from app.services.forge_match.field_extractor import SourceFieldRecord
from app.services.forge_match.llm_ranker import ForgeMatchLLMRanker


class _LLM:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def chat_json_with_trace(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"parsed": self._payload, "content": ""}


class _BrokenLLM:
    def chat_json_with_trace(self, **kwargs):
        del kwargs
        return {"parsed": None, "content": "not-json"}


def _source() -> SourceFieldRecord:
    return SourceFieldRecord(
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
        raw_row={},
    )


def test_ranker_rejects_out_of_set_ids() -> None:
    llm = _LLM(
        {
            "selected_column_id": 99999,
            "alternate_column_ids": [88888],
            "match_decision": "matched",
            "reason_codes": ["name_similarity"],
            "explanation": "bad",
            "ambiguity_note": None,
            "llm_confidence": 0.9,
        }
    )
    ranker = ForgeMatchLLMRanker(llm=llm)
    candidates = [
        {
            "column_id": 4812,
            "column_name": "student_birth_date",
            "display_name": "Student Birth Date",
            "table_name": "dim_student",
            "combined_retrieval_score": 0.88,
        }
    ]

    out = ranker.rank(workspace_id="ws-test", source_record=_source(), candidates=candidates)
    assert out["match_decision"] == "no_confident_match"
    assert out["selected_column_id"] is None


def test_ranker_prompt_includes_definition_guidance() -> None:
    llm = _LLM(
        {
            "selected_column_id": 4812,
            "alternate_column_ids": [],
            "match_decision": "matched",
            "reason_codes": ["definition_alignment"],
            "explanation": "Definitions aligned.",
            "ambiguity_note": None,
            "llm_confidence": 0.8,
        }
    )
    ranker = ForgeMatchLLMRanker(llm=llm)
    candidates = [
        {
            "column_id": 4812,
            "column_name": "student_dob",
            "display_name": "Student DOB",
            "table_name": "dim_student",
            "description": "Date of birth for the student",
            "combined_retrieval_score": 0.72,
        }
    ]

    ranker.rank(workspace_id="ws-test", source_record=_source(), candidates=candidates)

    prompt = llm.calls[0]["user_prompt"]
    assert "definition_guidance" in prompt
    assert "definition_overlap_score" in prompt


def test_ranker_fallback_refuses_confident_match_when_definitions_conflict() -> None:
    ranker = ForgeMatchLLMRanker(llm=_BrokenLLM())
    candidates = [
        {
            "column_id": 4812,
            "column_name": "birth_date",
            "display_name": "Birth Date",
            "table_name": "dim_student",
            "description": "Date the student enrolled in the district",
            "final_score": 0.93,
            "combined_retrieval_score": 0.9,
            "lexical_score": 0.88,
            "vector_score": 0.85,
        }
    ]

    out = ranker.rank(workspace_id="ws-test", source_record=_source(), candidates=candidates)

    assert out["match_decision"] == "ambiguous"
    assert out["selected_column_id"] is None
    assert "definition_conflict" in out["reason_codes"]
