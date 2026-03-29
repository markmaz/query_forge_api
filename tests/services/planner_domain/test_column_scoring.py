"""Unit tests for app.services.planner_domain.column_scoring."""
from __future__ import annotations

from app.services.planner_domain.column_scoring import (
    _column_heuristic_boost,
    _required_column_keys,
    _extract_group_entities_for_shortlist,
    _has_group_entity,
    _matches_group_entity_column,
    _is_canonical_name_column_name,
    _is_preferred_name_column_name,
    _has_canonical_name_columns,
    _is_student_identity_column_name,
    _is_adm_signal_column_name,
    _is_birth_date_column_name,
    _is_age_column_name,
    _is_calendar_day_column_name,
    _is_school_day_flag_column_name,
    _is_non_instructional_day_column_name,
    _is_city_column_name,
    _is_preferred_state_column_name,
    _is_technical_school_key_name,
    _is_staff_role_title_column_name,
    _is_staff_classification_column_name,
    _has_school_name_column,
    _has_staff_role_title_column,
    _prompt_prefers_human_school_name_filter,
    _prompt_prefers_staff_role_title_filter,
    _prompt_explicitly_requests_school_key,
    _prompt_explicitly_requests_staff_classification,
)


# ---------------------------------------------------------------------------
# _is_* column name predicates
# ---------------------------------------------------------------------------

def test_is_canonical_name_first_name() -> None:
    assert _is_canonical_name_column_name("first_name") is True


def test_is_canonical_name_false_for_preferred() -> None:
    assert _is_canonical_name_column_name("preferred_first_name") is False


def test_is_preferred_name_column_name_true() -> None:
    assert _is_preferred_name_column_name("preferred_first_name") is True


def test_is_preferred_name_column_name_false() -> None:
    assert _is_preferred_name_column_name("first_name") is False


def test_is_student_identity_column_name_first_name() -> None:
    assert _is_student_identity_column_name("first_name") is True


def test_is_student_identity_column_name_preferred_excluded() -> None:
    assert _is_student_identity_column_name("preferred_first_name") is False


def test_is_adm_signal_column_name_true() -> None:
    assert _is_adm_signal_column_name("normalized_adm") is True


def test_is_adm_signal_column_name_false() -> None:
    assert _is_adm_signal_column_name("school_name") is False


def test_is_birth_date_column_name_true() -> None:
    assert _is_birth_date_column_name("birth_date") is True
    assert _is_birth_date_column_name("date_of_birth") is True


def test_is_age_column_name_true() -> None:
    assert _is_age_column_name("age") is True
    assert _is_age_column_name("student_age") is True


def test_is_calendar_day_column_name_true() -> None:
    assert _is_calendar_day_column_name("calendar_date") is True


def test_is_school_day_flag_column_name_true() -> None:
    assert _is_school_day_flag_column_name("is_school_day") is True


def test_is_non_instructional_day_column_name_true() -> None:
    assert _is_non_instructional_day_column_name("non_instructional_day") is True


def test_is_city_column_name_true() -> None:
    assert _is_city_column_name("city") is True
    assert _is_city_column_name("city_name") is True


def test_is_preferred_state_column_name_true() -> None:
    assert _is_preferred_state_column_name("state_code") is True


def test_is_technical_school_key_name_true() -> None:
    assert _is_technical_school_key_name("k_school") is True


def test_is_staff_role_title_column_name_true() -> None:
    assert _is_staff_role_title_column_name("position_title") is True


def test_is_staff_classification_column_name_true() -> None:
    assert _is_staff_classification_column_name("staff_classification") is True


# ---------------------------------------------------------------------------
# _has_* row-level checks
# ---------------------------------------------------------------------------

def test_has_canonical_name_columns_true() -> None:
    rows = [{"column_name": "first_name"}, {"column_name": "grade"}]
    assert _has_canonical_name_columns(rows=rows) is True


def test_has_canonical_name_columns_false() -> None:
    rows = [{"column_name": "grade"}, {"column_name": "school_name"}]
    assert _has_canonical_name_columns(rows=rows) is False


def test_has_school_name_column_true() -> None:
    rows = [{"column_name": "school_name"}]
    assert _has_school_name_column(rows=rows) is True


def test_has_staff_role_title_column_true() -> None:
    rows = [{"column_name": "position_title"}]
    assert _has_staff_role_title_column(rows=rows) is True


# ---------------------------------------------------------------------------
# Group entity extraction
# ---------------------------------------------------------------------------

def test_extract_group_entities_by_account() -> None:
    entities = _extract_group_entities_for_shortlist("show revenue by account")
    assert "account" in entities


def test_extract_group_entities_empty_without_by() -> None:
    entities = _extract_group_entities_for_shortlist("show all accounts")
    assert entities == set()


def test_has_group_entity_true() -> None:
    assert _has_group_entity({"account", "region"}, "account") is True


def test_has_group_entity_false() -> None:
    assert _has_group_entity({"region"}, "account") is False


def test_matches_group_entity_column_account_name() -> None:
    assert _matches_group_entity_column(col_name="account_name", entities={"account"}) is True


def test_matches_group_entity_column_false() -> None:
    assert _matches_group_entity_column(col_name="account_id", entities={"account"}) is False


# ---------------------------------------------------------------------------
# Prompt preference checks
# ---------------------------------------------------------------------------

def test_prompt_prefers_human_school_name_filter_true() -> None:
    assert _prompt_prefers_human_school_name_filter("staff at Lincoln school") is True


def test_prompt_prefers_human_school_name_filter_false() -> None:
    assert _prompt_prefers_human_school_name_filter("show all students") is False


def test_prompt_prefers_staff_role_title_filter_true() -> None:
    assert _prompt_prefers_staff_role_title_filter("principal at Lincoln") is True


def test_prompt_prefers_staff_role_title_filter_false_when_classification() -> None:
    assert _prompt_prefers_staff_role_title_filter("staff classification at Lincoln") is False


def test_prompt_explicitly_requests_school_key_true() -> None:
    assert _prompt_explicitly_requests_school_key("show nces school code") is True


def test_prompt_explicitly_requests_school_key_false() -> None:
    assert _prompt_explicitly_requests_school_key("show school name") is False


def test_prompt_explicitly_requests_staff_classification_true() -> None:
    assert _prompt_explicitly_requests_staff_classification("show staff classification") is True


# ---------------------------------------------------------------------------
# _column_heuristic_boost
# ---------------------------------------------------------------------------

def test_column_heuristic_boost_birth_date_for_age_extreme() -> None:
    row = {"column_name": "birth_date", "column_key": "wt1.birth_date"}
    score = _column_heuristic_boost(prompt="show the oldest students", row=row)
    assert score > 0.5


def test_column_heuristic_boost_zero_for_irrelevant() -> None:
    row = {"column_name": "school_year", "column_key": "wt1.school_year"}
    score = _column_heuristic_boost(prompt="show all students", row=row)
    assert score == 0.0


def test_column_heuristic_boost_subgroup_race_column() -> None:
    row = {"column_name": "race_ethnicity", "column_key": "wt1.race_ethnicity"}
    score = _column_heuristic_boost(prompt="hispanic students", row=row)
    assert score > 0.0


def test_column_heuristic_boost_canonical_name_for_student_list() -> None:
    row = {"column_name": "first_name", "column_key": "wt1.first_name"}
    score = _column_heuristic_boost(
        prompt="show first name of students at barksdale", row=row
    )
    assert score > 0.0


# ---------------------------------------------------------------------------
# _required_column_keys
# ---------------------------------------------------------------------------

def test_required_column_keys_canonical_name_for_student_listing() -> None:
    rows = [
        {"column_name": "first_name", "column_key": "wt1.first_name"},
        {"column_name": "preferred_first_name", "column_key": "wt1.preferred_first_name"},
        {"column_name": "grade", "column_key": "wt1.grade"},
    ]
    keys = _required_column_keys(prompt="show first name of students at Lincoln", rows=rows)
    assert "wt1.first_name" in keys
    assert "wt1.preferred_first_name" not in keys


def test_required_column_keys_adm_signal_columns() -> None:
    rows = [
        {"column_name": "normalized_adm", "column_key": "wt1.normalized_adm"},
        {"column_name": "school_name", "column_key": "wt1.school_name"},
    ]
    keys = _required_column_keys(
        prompt="what is the average daily membership by school", rows=rows
    )
    assert "wt1.normalized_adm" in keys


def test_required_column_keys_empty_for_plain_prompt() -> None:
    rows = [
        {"column_name": "grade", "column_key": "wt1.grade"},
    ]
    keys = _required_column_keys(prompt="show all students", rows=rows)
    assert keys == []
