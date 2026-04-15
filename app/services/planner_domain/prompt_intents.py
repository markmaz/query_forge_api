"""Prompt-intent heuristics for the planner domain service.

Pure text-analysis functions that inspect a user prompt (or slot payload) to
determine intent signals used during domain selection and column scoring.  No
I/O, no external dependencies.
"""
from __future__ import annotations
from typing import Any, List, Mapping, Optional, Sequence

from app.services.domain.planner_prompt_intent_policy_service import PlannerPromptIntentPolicyService

_PROMPT_INTENT_POLICIES = PlannerPromptIntentPolicyService(enable_db_lookup=False)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dedupe_text_items(values: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for value in values:
        token = " ".join(str(value).strip().split())
        if token == "":
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _extract_named_month_number(text: str) -> Optional[int]:
    return _PROMPT_INTENT_POLICIES.extract_named_month_number(text)


# ---------------------------------------------------------------------------
# List vs aggregate intent
# ---------------------------------------------------------------------------


def _looks_like_list_students_prompt(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.looks_like_list_students(prompt)


def _looks_like_list_schools_prompt(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.looks_like_list_schools(prompt)


# ---------------------------------------------------------------------------
# Entity mention checks
# ---------------------------------------------------------------------------


def _prompt_mentions_students(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.prompt_mentions_students(prompt)


def _slot_mentions_students(slot_hints: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(slot_hints, Mapping):
        return False
    entity = str(slot_hints.get("entity") or "").strip().lower()
    return entity in {"student", "students", "kid", "kids"}


def _prompt_mentions_school_or_district(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.prompt_mentions_school_or_district(prompt)


# ---------------------------------------------------------------------------
# Subgroup / demographic signals
# ---------------------------------------------------------------------------


def _prompt_has_subgroup(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.prompt_has_subgroup(prompt)


def _prompt_has_nativity(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.prompt_has_nativity(prompt)


# ---------------------------------------------------------------------------
# Calendar / date signals
# ---------------------------------------------------------------------------


def _prompt_has_calendar_days_off(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.prompt_has_calendar_days_off(prompt)


def _prompt_has_age_extreme(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.prompt_has_age_extreme(prompt)


def _prompt_has_birth_month_constraint(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.prompt_has_birth_month_constraint(prompt)


# ---------------------------------------------------------------------------
# Name-preference signals
# ---------------------------------------------------------------------------


def _prompt_has_name_constraint(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.prompt_has_name_constraint(prompt)


def _prompt_explicitly_requests_preferred_name(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.prompt_explicitly_requests_preferred_name(prompt)


def _prompt_prefers_canonical_name_columns(prompt: str) -> bool:
    text = str(prompt or "")
    if text.strip() == "":
        return False
    if _prompt_explicitly_requests_preferred_name(text):
        return False
    return (
        _prompt_has_name_constraint(text)
        or _prompt_implies_staff_work_context(text)
        or _prompt_implies_student_school_context(text)
        or _looks_like_list_students_prompt(text)
    )


# ---------------------------------------------------------------------------
# ADM intent
# ---------------------------------------------------------------------------


def _prompt_has_adm_intent(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.prompt_has_adm_intent(prompt)


# ---------------------------------------------------------------------------
# Staff vs student context
# ---------------------------------------------------------------------------


def _prompt_implies_staff_work_context(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.prompt_implies_staff_work_context(prompt)


def _prompt_implies_student_school_context(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.prompt_implies_student_school_context(prompt)


# ---------------------------------------------------------------------------
# Geographic signals
# ---------------------------------------------------------------------------


def _prompt_has_city_state_pattern(prompt: str) -> bool:
    return _PROMPT_INTENT_POLICIES.prompt_has_city_state_pattern(prompt)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _extract_subgroup_terms(prompt: str) -> List[str]:
    return _PROMPT_INTENT_POLICIES.extract_subgroup_terms(prompt)


def _extract_time_phrases(prompt: str) -> List[str]:
    return _PROMPT_INTENT_POLICIES.extract_time_phrases(prompt)
