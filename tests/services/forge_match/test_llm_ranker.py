from __future__ import annotations

from app.services.forge_match.field_extractor import SourceFieldRecord
from app.services.forge_match.llm_ranker import ForgeMatchLLMRanker


class _LLM:
    def __init__(self, payload):
        self._payload = payload

    def chat_json_with_trace(self, **kwargs):
        del kwargs
        return {"parsed": self._payload, "content": ""}


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

    out = ranker.rank(source_record=_source(), candidates=candidates)
    assert out["match_decision"] == "no_confident_match"
    assert out["selected_column_id"] is None
