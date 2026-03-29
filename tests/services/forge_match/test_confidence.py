from __future__ import annotations

from app.services.forge_match.confidence import ForgeMatchConfidenceScorer
from app.services.forge_match.field_extractor import SourceFieldRecord


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


def test_confidence_rewards_definition_alignment() -> None:
    scorer = ForgeMatchConfidenceScorer()
    selected = {
        "column_id": 4812,
        "column_name": "student_dob",
        "table_name": "dim_student",
        "domain_name": "Student Profile",
        "description": "Date of birth for the student",
        "data_type": "date",
        "lexical_score": 0.52,
        "vector_score": 0.62,
        "combined_retrieval_score": 0.6,
        "final_score": 0.68,
    }

    out = scorer.score(
        source_record=_source(),
        selected_candidate=selected,
        candidates=[selected],
        llm_result={
            "match_decision": "matched",
            "llm_confidence": 0.74,
            "reason_codes": ["definition_alignment"],
        },
    )

    assert out["confidence_score"] >= 65
    assert out["confidence_band"] in {"medium", "high"}


def test_confidence_penalizes_definition_conflict() -> None:
    scorer = ForgeMatchConfidenceScorer()
    selected = {
        "column_id": 4812,
        "column_name": "birth_date",
        "table_name": "dim_student",
        "domain_name": "Student Profile",
        "description": "Date the student enrolled in the district",
        "data_type": "date",
        "lexical_score": 0.88,
        "vector_score": 0.71,
        "combined_retrieval_score": 0.79,
        "final_score": 0.83,
    }

    out = scorer.score(
        source_record=_source(),
        selected_candidate=selected,
        candidates=[selected],
        llm_result={
            "match_decision": "ambiguous",
            "llm_confidence": 0.42,
            "reason_codes": ["definition_conflict", "ambiguous_candidates"],
        },
    )

    assert out["confidence_score"] < 55
    assert out["confidence_band"] in {"low", "medium"}
