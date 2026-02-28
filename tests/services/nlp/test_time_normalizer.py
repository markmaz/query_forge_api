from __future__ import annotations

from app.nlp.time_normalizer import normalize_time_terms


def test_normalize_time_terms_current_school_year() -> None:
    out = normalize_time_terms(["for the current school year"], vertical="education")
    assert out
    assert out[0].key == "CURRENT_SCHOOL_YEAR"


def test_normalize_time_terms_previous_school_year() -> None:
    out = normalize_time_terms(["last school year"], vertical="education")
    assert out
    assert out[0].key == "PREVIOUS_SCHOOL_YEAR"


def test_normalize_time_terms_rolling_years() -> None:
    out = normalize_time_terms(["past 3 years"], vertical="education")
    assert out
    assert out[0].key == "ROLLING_N_SCHOOL_YEARS"
    assert out[0].value == 3


def test_normalize_time_terms_school_year_span() -> None:
    out = normalize_time_terms(["2023-24"], vertical="education")
    assert out
    assert out[0].key == "SCHOOL_YEAR_EXACT"
    assert out[0].value == "2023-24"
