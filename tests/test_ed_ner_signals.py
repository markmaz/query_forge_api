from __future__ import annotations

from app.services.nlp.ed_ner import extract_signals


def _filters(result):
    return {(item["column"], item["op"], item["value"]) for item in result["filters"]}


def test_birth_country_filter() -> None:
    result = extract_signals("students born in mexico")
    assert ("birth_country", "=", "Mexico") in _filters(result)


def test_name_filters() -> None:
    result = extract_signals("student firstname is john and last name is doe")
    filters = _filters(result)
    assert ("first_name", "=", "John") in filters
    assert ("last_name", "=", "Doe") in filters


def test_count_enrollment_race_and_time() -> None:
    result = extract_signals("how many black students are enrolled this year")
    filters = _filters(result)
    assert result["metric"] == "COUNT"
    assert ("race_ethnicity", "=", "Black - African American") in filters
    assert ("is_active_enrollment", "=", True) in filters
    assert ("school_year", "=", "CURRENT") in filters
