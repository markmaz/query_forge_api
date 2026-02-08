from __future__ import annotations

from app.services.nlp.edfi_ner import (
    LABEL_GRADE_LEVEL,
    LABEL_GROUP_BY,
    LABEL_SCHOOL_YEAR,
    extract_entities,
)


def _by_label(result, label: str):
    return [e for e in result["entities"] if e["label"] == label]


def test_grade_level_normalization() -> None:
    result = extract_entities("Show 9th grade attendance for K and grade 11")
    norms = {e["norm"] for e in _by_label(result, LABEL_GRADE_LEVEL)}
    assert {"9", "K", "11"}.issubset(norms)


def test_school_year_normalization() -> None:
    result = extract_entities("SY 2024 and 2024-25 school year")
    norms = {e["norm"] for e in _by_label(result, LABEL_SCHOOL_YEAR)}
    assert "2024" in norms


def test_acronym_detection() -> None:
    result = extract_entities("IEP OSS ADA GPA")
    texts = {e["text"].upper() for e in result["entities"]}
    assert {"IEP", "OSS", "ADA", "GPA"}.issubset(texts)


def test_group_by_extraction() -> None:
    result = extract_entities("Attendance by school and by grade")
    norms = {e["norm"] for e in _by_label(result, LABEL_GROUP_BY)}
    assert {"school", "grade"}.issubset(norms)
