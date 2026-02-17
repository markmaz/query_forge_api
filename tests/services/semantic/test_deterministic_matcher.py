from __future__ import annotations

from app.services.semantic.deterministic_matcher import DeterministicMatcher


def test_deterministic_matcher_k_prefix() -> None:
    out = DeterministicMatcher().match("show records for k_school and school_year")
    matched = out["matched"]
    concept_keys = {row["concept_key"] for row in matched}
    assert "SCHOOL_ID" in concept_keys
    assert "SCHOOL_YEAR" in concept_keys
