"""Prompt-intent heuristics for the planner domain service.

Pure text-analysis functions that inspect a user prompt (or slot payload) to
determine intent signals used during domain selection and column scoring.  No
I/O, no external dependencies.
"""
from __future__ import annotations

import re
from typing import Any, List, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Compiled regex constants
# ---------------------------------------------------------------------------

_LIST_STUDENTS_RE = re.compile(
    r"\b(show|list|give|display|return|find)\b.*\b(student|students)\b", re.IGNORECASE
)
_AGGREGATE_STUDENTS_RE = re.compile(
    r"\b(how many|count|number of|total|sum|average|avg|ratio|rate|percentage|percent)\b.*\b(student|students)\b",
    re.IGNORECASE,
)
_LIST_SCHOOLS_RE = re.compile(
    r"\b(show|list|give|display|return|find)\b.*\b(school|schools)\b", re.IGNORECASE
)
_AGGREGATE_SCHOOLS_RE = re.compile(
    r"\b(how many|count|number of|total|sum|average|avg|ratio|rate|percentage|percent)\b.*\b(school|schools)\b",
    re.IGNORECASE,
)
_SUBGROUP_HINT_RE = re.compile(
    r"\b(black|african american|african-american|hispanic|latino|el|ell|esl|lep|mll)\b",
    re.IGNORECASE,
)
_DISTRICT_LEA_TERM_RE = re.compile(
    r"\b(district|school district|lea|local education agency)\b", re.IGNORECASE
)
_CITY_STATE_ABBR_RE = re.compile(r",\s*([a-z]{2})\b", re.IGNORECASE)
_STAFF_WORK_HINT_RE = re.compile(
    r"\b(work(s|ed|ing)?|workplace|employed|employment|teach(es|ing)?|teacher|staff|job|principal|assistant\s+principal|counselor|counsellor)\b",
    re.IGNORECASE,
)
_STAFF_ROLE_TITLE_HINT_RE = re.compile(
    r"\b(principal|assistant\s+principal|teacher|counselor|counsellor|coach|librarian|superintendent|nurse|psychologist|social\s+worker|position\s+title|job\s+title|role)\b",
    re.IGNORECASE,
)
_STUDENT_ATTEND_HINT_RE = re.compile(
    r"\b(goes to|attend(s|ed|ing)?|enroll(ed|ment|ing)?|student)\b",
    re.IGNORECASE,
)
_ADM_HINT_RE = re.compile(
    r"\b(adm|average\s+daily\s+membership|base\s+adm|daily\s+membership|normalized\s+adm)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# US state abbreviations (used by _prompt_has_city_state_pattern)
# ---------------------------------------------------------------------------

_US_STATE_ABBR = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
}

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
    prompt_text = str(text or "").strip().lower()
    if prompt_text == "":
        return None
    month_map = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    match = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
        prompt_text,
    )
    if match is None:
        return None
    return month_map.get(str(match.group(1) or "").lower())


# ---------------------------------------------------------------------------
# List vs aggregate intent
# ---------------------------------------------------------------------------


def _looks_like_list_students_prompt(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if text == "":
        return False
    if _AGGREGATE_STUDENTS_RE.search(text) is not None:
        return False
    if _LIST_STUDENTS_RE.search(text) is not None:
        return True
    return re.search(r"\b(student|students)\b", text, flags=re.IGNORECASE) is not None


def _looks_like_list_schools_prompt(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if text == "":
        return False
    if _AGGREGATE_SCHOOLS_RE.search(text) is not None:
        return False
    if _LIST_SCHOOLS_RE.search(text) is not None:
        return True
    return re.search(r"\b(school|schools)\b", text, flags=re.IGNORECASE) is not None


# ---------------------------------------------------------------------------
# Entity mention checks
# ---------------------------------------------------------------------------


def _prompt_mentions_students(prompt: str) -> bool:
    return (
        re.search(r"\b(student|students|kid|kids)\b", str(prompt or ""), flags=re.IGNORECASE)
        is not None
    )


def _slot_mentions_students(slot_hints: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(slot_hints, Mapping):
        return False
    entity = str(slot_hints.get("entity") or "").strip().lower()
    return entity in {"student", "students", "kid", "kids"}


def _prompt_mentions_school_or_district(prompt: str) -> bool:
    text = str(prompt or "")
    if re.search(r"\b(school|schools)\b", text, flags=re.IGNORECASE) is not None:
        return True
    return _DISTRICT_LEA_TERM_RE.search(text) is not None


# ---------------------------------------------------------------------------
# Subgroup / demographic signals
# ---------------------------------------------------------------------------


def _prompt_has_subgroup(prompt: str) -> bool:
    return _SUBGROUP_HINT_RE.search(str(prompt or "")) is not None


def _prompt_has_nativity(prompt: str) -> bool:
    text = str(prompt or "").lower()
    nativity_terms = (
        "born",
        "birth",
        "birth country",
        "not born",
        "entered the us",
        "date entered us",
    )
    return any(term in text for term in nativity_terms)


# ---------------------------------------------------------------------------
# Calendar / date signals
# ---------------------------------------------------------------------------


def _prompt_has_calendar_days_off(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    phrases = (
        " days off ",
        " day off ",
        " off day ",
        " off days ",
        " no school ",
        " school closed ",
        " non instructional ",
        " non-instructional ",
    )
    return any(phrase in text for phrase in phrases)


def _prompt_has_age_extreme(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    return any(token in text for token in (" oldest ", " youngest ", " eldest "))


def _prompt_has_birth_month_constraint(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    has_birth_context = any(
        token in text
        for token in (
            " birthday ",
            " birthdays ",
            " birth month ",
            " birthdate ",
            " date of birth ",
            " born in ",
            " births in ",
        )
    )
    if not has_birth_context:
        return False
    return _extract_named_month_number(text) is not None


# ---------------------------------------------------------------------------
# Name-preference signals
# ---------------------------------------------------------------------------


def _prompt_has_name_constraint(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return (
        ("first name" in text)
        or ("last name" in text)
        or ("named " in text)
        or ("name of " in text)
    )


def _prompt_explicitly_requests_preferred_name(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    explicit_phrases = (
        " preferred name ",
        " preferred first name ",
        " preferred last name ",
        " preferred names ",
    )
    return any(phrase in text for phrase in explicit_phrases)


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
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    return _ADM_HINT_RE.search(text) is not None


# ---------------------------------------------------------------------------
# Staff vs student context
# ---------------------------------------------------------------------------


def _prompt_implies_staff_work_context(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    if _STUDENT_ATTEND_HINT_RE.search(text) is not None and _STAFF_WORK_HINT_RE.search(text) is None:
        return False
    return _STAFF_WORK_HINT_RE.search(text) is not None


def _prompt_implies_student_school_context(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    if _STAFF_WORK_HINT_RE.search(text) is not None and _STUDENT_ATTEND_HINT_RE.search(text) is None:
        return False
    return _STUDENT_ATTEND_HINT_RE.search(text) is not None


# ---------------------------------------------------------------------------
# Geographic signals
# ---------------------------------------------------------------------------


def _prompt_has_city_state_pattern(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    match = _CITY_STATE_ABBR_RE.search(text)
    if match is None:
        return False
    token = str(match.group(1) or "").strip().lower()
    return token in _US_STATE_ABBR


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _extract_subgroup_terms(prompt: str) -> List[str]:
    text = str(prompt or "")
    matches = [match.group(0) for match in _SUBGROUP_HINT_RE.finditer(text)]
    return _dedupe_text_items(matches)


def _extract_time_phrases(prompt: str) -> List[str]:
    text = str(prompt or "").lower()
    phrases: List[str] = []
    if "this year" in text:
        phrases.append("this year")
    if "last year" in text:
        phrases.append("last year")
    if "current school year" in text:
        phrases.append("current school year")
    if "school year" in text and not phrases:
        phrases.append("school year")
    return _dedupe_text_items(phrases)
