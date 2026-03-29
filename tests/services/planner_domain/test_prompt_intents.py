"""Unit tests for app.services.planner_domain.prompt_intents."""
from __future__ import annotations

from app.services.planner_domain.prompt_intents import (
    _extract_subgroup_terms,
    _extract_time_phrases,
    _looks_like_list_schools_prompt,
    _looks_like_list_students_prompt,
    _prompt_has_adm_intent,
    _prompt_has_age_extreme,
    _prompt_has_birth_month_constraint,
    _prompt_has_calendar_days_off,
    _prompt_has_city_state_pattern,
    _prompt_has_name_constraint,
    _prompt_has_nativity,
    _prompt_has_subgroup,
    _prompt_implies_staff_work_context,
    _prompt_implies_student_school_context,
    _prompt_mentions_school_or_district,
    _prompt_mentions_students,
    _prompt_explicitly_requests_preferred_name,
    _prompt_prefers_canonical_name_columns,
    _slot_mentions_students,
)


# --- _looks_like_list_students_prompt ---

def test_list_students_matches_show_students() -> None:
    assert _looks_like_list_students_prompt("show me all students") is True


def test_list_students_false_for_aggregate() -> None:
    assert _looks_like_list_students_prompt("how many students passed?") is False


def test_list_students_true_for_bare_students_word() -> None:
    assert _looks_like_list_students_prompt("students with absences") is True


# --- _looks_like_list_schools_prompt ---

def test_list_schools_matches_list_schools() -> None:
    assert _looks_like_list_schools_prompt("list all schools in the district") is True


def test_list_schools_false_for_count_schools() -> None:
    assert _looks_like_list_schools_prompt("count the schools") is False


# --- _prompt_mentions_students ---

def test_prompt_mentions_students_true() -> None:
    assert _prompt_mentions_students("show me all kids") is True


def test_prompt_mentions_students_false() -> None:
    assert _prompt_mentions_students("show me all staff") is False


# --- _slot_mentions_students ---

def test_slot_mentions_students_true() -> None:
    assert _slot_mentions_students({"entity": "students"}) is True


def test_slot_mentions_students_false_for_non_mapping() -> None:
    assert _slot_mentions_students(None) is False


# --- _prompt_mentions_school_or_district ---

def test_prompt_mentions_school_true() -> None:
    assert _prompt_mentions_school_or_district("list schools in district") is True


def test_prompt_mentions_district_via_lea() -> None:
    assert _prompt_mentions_school_or_district("LEA 101 students") is True


# --- _prompt_has_subgroup ---

def test_prompt_has_subgroup_hispanic() -> None:
    assert _prompt_has_subgroup("hispanic students in grade 5") is True


def test_prompt_has_subgroup_false() -> None:
    assert _prompt_has_subgroup("show me all students") is False


# --- _prompt_has_nativity ---

def test_prompt_has_nativity_born() -> None:
    assert _prompt_has_nativity("students born outside the us") is True


def test_prompt_has_nativity_false() -> None:
    assert _prompt_has_nativity("show me third grade students") is False


# --- _prompt_has_calendar_days_off ---

def test_prompt_has_calendar_days_off_true() -> None:
    assert _prompt_has_calendar_days_off("show me all days off this year") is True


def test_prompt_has_calendar_days_off_false() -> None:
    assert _prompt_has_calendar_days_off("show me absent students") is False


# --- _prompt_has_age_extreme ---

def test_prompt_has_age_extreme_oldest() -> None:
    assert _prompt_has_age_extreme("show me the oldest students") is True


def test_prompt_has_age_extreme_false() -> None:
    assert _prompt_has_age_extreme("show me students by age") is False


# --- _prompt_has_birth_month_constraint ---

def test_prompt_has_birth_month_constraint_true() -> None:
    assert _prompt_has_birth_month_constraint("students with birthday in March") is True


def test_prompt_has_birth_month_constraint_false_no_month() -> None:
    assert _prompt_has_birth_month_constraint("students with birthdays") is False


# --- _prompt_has_name_constraint ---

def test_prompt_has_name_constraint_first_name() -> None:
    assert _prompt_has_name_constraint("show first name of students") is True


def test_prompt_has_name_constraint_false() -> None:
    assert _prompt_has_name_constraint("show me all students") is False


# --- _prompt_explicitly_requests_preferred_name ---

def test_prompt_explicitly_requests_preferred_name_true() -> None:
    assert _prompt_explicitly_requests_preferred_name("show preferred name for students") is True


def test_prompt_explicitly_requests_preferred_name_false() -> None:
    assert _prompt_explicitly_requests_preferred_name("show first name of students") is False


# --- _prompt_prefers_canonical_name_columns ---

def test_prompt_prefers_canonical_name_columns_true() -> None:
    assert _prompt_prefers_canonical_name_columns("show last name of students at barksdale") is True


def test_prompt_prefers_canonical_name_false_for_preferred_name() -> None:
    assert _prompt_prefers_canonical_name_columns("show preferred name for staff") is False


# --- _prompt_has_adm_intent ---

def test_prompt_has_adm_intent_true() -> None:
    assert _prompt_has_adm_intent("what is the average daily membership?") is True


def test_prompt_has_adm_intent_false() -> None:
    assert _prompt_has_adm_intent("show me all students") is False


# --- _prompt_implies_staff_work_context ---

def test_prompt_implies_staff_work_context_teacher() -> None:
    assert _prompt_implies_staff_work_context("teachers working at Lincoln") is True


def test_prompt_implies_staff_work_context_false() -> None:
    assert _prompt_implies_staff_work_context("students at Lincoln") is False


# --- _prompt_implies_student_school_context ---

def test_prompt_implies_student_school_context_enrolled() -> None:
    assert _prompt_implies_student_school_context("students enrolled at barksdale") is True


# --- _prompt_has_city_state_pattern ---

def test_prompt_has_city_state_pattern_true() -> None:
    assert _prompt_has_city_state_pattern("students in Austin, TX") is True


def test_prompt_has_city_state_pattern_false() -> None:
    assert _prompt_has_city_state_pattern("students in third grade") is False


# --- _extract_subgroup_terms ---

def test_extract_subgroup_terms_returns_matched_terms() -> None:
    terms = _extract_subgroup_terms("hispanic and ELL students")
    assert "hispanic" in [t.lower() for t in terms]


def test_extract_subgroup_terms_empty_when_no_match() -> None:
    assert _extract_subgroup_terms("all students") == []


# --- _extract_time_phrases ---

def test_extract_time_phrases_this_year() -> None:
    assert "this year" in _extract_time_phrases("students this year")


def test_extract_time_phrases_last_year() -> None:
    assert "last year" in _extract_time_phrases("students last year")


def test_extract_time_phrases_empty() -> None:
    assert _extract_time_phrases("show me all students") == []
