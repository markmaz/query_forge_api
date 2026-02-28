from __future__ import annotations

from datetime import date

from app.services.planner.value_normalizers.school_year import (
    current_school_year,
    normalize_school_year_values,
)


def test_current_school_year_before_august() -> None:
    assert current_school_year(today=date(2026, 2, 27)) == 2026


def test_current_school_year_august_rollover() -> None:
    assert current_school_year(today=date(2026, 8, 1)) == 2027


def test_normalize_school_year_current_phrase() -> None:
    out = normalize_school_year_values("current school year", today=date(2026, 2, 27))
    assert out == [2026]


def test_normalize_school_year_span_uses_second_year() -> None:
    out = normalize_school_year_values("2025-2026 school year", today=date(2026, 2, 27))
    assert out == [2026]


def test_current_school_year_respects_custom_start_end_months() -> None:
    assert current_school_year(today=date(2026, 6, 30), school_year_start_month=7, school_year_end_month=6) == 2026
    assert current_school_year(today=date(2026, 7, 1), school_year_start_month=7, school_year_end_month=6) == 2027
