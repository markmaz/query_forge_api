from __future__ import annotations

from app.services.semantic.deterministic_matcher import DeterministicMatcher


def test_deterministic_matcher_k_prefix() -> None:
    out = DeterministicMatcher().match("show records for k_school and school_year")
    matched = out["matched"]
    concept_keys = {row["concept_key"] for row in matched}
    assert "SCHOOL_ID" in concept_keys
    assert "SCHOOL_YEAR" in concept_keys


def test_deterministic_matcher_extracts_name_phrases() -> None:
    out = DeterministicMatcher().match('Find students named "Holden Caulfield" and staff called O\'Neil')
    extracted = out.get("extracted_values")
    assert isinstance(extracted, list)
    assert {"kind": "name", "value": "Holden Caulfield", "source": "pattern:named"} in extracted
    assert {"kind": "name", "value": "O'Neil", "source": "pattern:called"} in extracted


def test_deterministic_matcher_extracts_school_phrase() -> None:
    out = DeterministicMatcher().match(
        "Give me all students at the Clarksville Elementary School"
    )
    extracted = out.get("extracted_values")
    assert isinstance(extracted, list)
    assert {
        "kind": "school_name",
        "value": "Clarksville Elementary School",
        "source": "pattern:at_school",
    } in extracted


def test_deterministic_matcher_extracts_quoted_school_phrase() -> None:
    out = DeterministicMatcher().match('Give me all students at "Clarksville Elementary School"')
    extracted = out.get("extracted_values")
    assert isinstance(extracted, list)
    assert {
        "kind": "school_name",
        "value": "Clarksville Elementary School",
        "source": "pattern:at_school",
    } in extracted
