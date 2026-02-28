from __future__ import annotations

from app.scripts.backfill_semantic_types import infer_semantic_type


def test_infer_semantic_type_exact_mappings() -> None:
    assert infer_semantic_type("city") == "geography.city"
    assert infer_semantic_type("school_city") == "geography.city"
    assert infer_semantic_type("name_of_county") == "geography.county"
    assert infer_semantic_type("state") == "geography.state"
    assert infer_semantic_type("zip") == "geography.zip"
    assert infer_semantic_type("school_year") == "time.school_year"
    assert infer_semantic_type("calendar_year") == "time.calendar_year"
    assert infer_semantic_type("student_unique_id") == "identifier.student_id"
    assert infer_semantic_type("first_name") == "attribute.student.first_name"
    assert infer_semantic_type("last_name") == "attribute.student.last_name"
    assert infer_semantic_type("race_ethnicity") == "attribute.student.race"
    assert infer_semantic_type("days_enrolled") == "metric.days_enrolled"
    assert infer_semantic_type("days_attended") == "metric.days_attended"


def test_infer_semantic_type_pattern_mappings() -> None:
    assert infer_semantic_type("enrollment_date") == "time.date"
    assert infer_semantic_type("student_id") == "identifier.surrogate_key"
    assert infer_semantic_type("is_active") == "flag.active"
    assert infer_semantic_type("is_english_learner") == "flag.english_learner"
    assert infer_semantic_type("unknown_column") is None

