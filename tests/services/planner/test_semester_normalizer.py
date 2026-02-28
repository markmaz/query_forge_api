from __future__ import annotations

from datetime import date

from app.services.planner.value_normalizers.semester import (
    current_semester_label,
    normalize_semester_values,
)


def test_current_semester_label_defaults_to_spring_in_february() -> None:
    assert current_semester_label(today=date(2026, 2, 27)) == "Spring"


def test_current_semester_label_defaults_to_fall_in_october() -> None:
    assert current_semester_label(today=date(2026, 10, 10)) == "Fall"


def test_current_semester_label_defaults_to_year_round_in_june() -> None:
    assert current_semester_label(today=date(2026, 6, 15)) == "Year Round"


def test_normalize_semester_values_current_phrase() -> None:
    out = normalize_semester_values("current semester", today=date(2026, 2, 27))
    assert out == ["Spring"]


def test_normalize_semester_values_typo_sprint_maps_to_spring() -> None:
    out = normalize_semester_values("sprint semester", today=date(2026, 10, 10))
    assert out == ["Spring"]
