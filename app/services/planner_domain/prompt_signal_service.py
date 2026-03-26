from __future__ import annotations

import re
from typing import List, Set

from app.models.domain.planner_rerank_policy import PLANNER_RERANK_SIGNAL_KEYS

_LIST_STUDENTS_RE = re.compile(r"\b(show|list|give|display|return|find)\b.*\b(student|students|kid|kids)\b", re.IGNORECASE)
_AGG_STUDENTS_RE = re.compile(
    r"\b(how many|count|number of|total|sum|average|avg|ratio|rate|percentage|percent)\b.*\b(student|students|kid|kids)\b",
    re.IGNORECASE,
)
_LIST_STAFF_RE = re.compile(r"\b(show|list|give|display|return|find)\b.*\b(staff|teachers?|employees?)\b", re.IGNORECASE)
_AGG_STAFF_RE = re.compile(
    r"\b(how many|count|number of|total|sum|average|avg|ratio|rate|percentage|percent)\b.*\b(staff|teachers?|employees?)\b",
    re.IGNORECASE,
)
_SCHOOL_AGG_RE = re.compile(
    r"\b(how many|count|number of|total|sum|average|avg|ratio|rate|percentage|percent)\b.*\b(school|schools)\b",
    re.IGNORECASE,
)
_DISTRICT_RE = re.compile(r"\b(district|school district|lea|local education agency)\b", re.IGNORECASE)
_TIME_RE = re.compile(r"\b(this year|last year|current school year|school year|today|yesterday|last month|this month)\b", re.IGNORECASE)
_MONTH_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.IGNORECASE,
)
_BIRTH_MONTH_RE = re.compile(
    r"\b(birthday|birthdays|birth month|birth months|birthdate|birthdates|birth date|birth dates|date of birth|dates of birth|born in|born during|births in)\b",
    re.IGNORECASE,
)
_ENROLLED_RE = re.compile(r"\b(currently enrolled|enrolled|active enrollment|is enrolled|enrollment)\b", re.IGNORECASE)
_ACTIVE_RE = re.compile(r"\b(active|currently active)\b", re.IGNORECASE)
_SUBGROUP_RE = re.compile(r"\b(black|african american|african-american|hispanic|latino|el|ell|esl|lep|mll)\b", re.IGNORECASE)
_PROGRAM_RE = re.compile(r"\b(program|service|services|participation|membership)\b", re.IGNORECASE)
_CALENDAR_DAYS_OFF_RE = re.compile(
    r"\b(days off|day off|off day|off days|no school|school closed|non instructional|non-instructional)\b",
    re.IGNORECASE,
)
_AGE_EXTREME_RE = re.compile(r"\b(oldest|youngest|eldest)\b", re.IGNORECASE)
_STAFF_ROLE_RE = re.compile(
    r"\b(principal|assistant\s+principal|teacher|counselor|counsellor|coach|librarian|superintendent|nurse|psychologist|social\s+worker|position\s+title|job\s+title|role)\b",
    re.IGNORECASE,
)
_SCHOOL_LITERAL_SUFFIXES = {"elementary", "middle", "high", "academy", "campus", "school"}
_SCHOOL_LITERAL_STOPWORDS = {"the", "a", "an", "all", "show", "list", "give", "display", "return", "find", "me", "has", "have"}


class PromptSignalService:
    def extract_signals(self, *, prompt: str) -> List[str]:
        text = str(prompt or "").strip()
        lower = text.lower()
        if text == "":
            return []

        signals: Set[str] = set()

        if _LIST_STUDENTS_RE.search(text):
            signals.update({"student_listing", "listing_intent", "needs_student_identity"})
        if _AGG_STUDENTS_RE.search(text):
            signals.update({"student_aggregate", "aggregate_intent"})
        if _LIST_STAFF_RE.search(text):
            signals.update({"staff_listing", "listing_intent"})
        if _AGG_STAFF_RE.search(text):
            signals.update({"staff_aggregate", "aggregate_intent"})
        if _SCHOOL_AGG_RE.search(text):
            signals.update({"school_aggregate", "aggregate_intent"})
        if " by " in lower and "aggregate_intent" in signals:
            signals.add("grouped_aggregate")

        if _DISTRICT_RE.search(text):
            signals.add("district_literal_present")
        if _TIME_RE.search(text) or _MONTH_RE.search(text):
            signals.add("time_constraint_present")
        if _AGE_EXTREME_RE.search(text):
            signals.add("age_extreme_prompt")
        if _BIRTH_MONTH_RE.search(text) and _MONTH_RE.search(text):
            signals.add("birth_month_prompt")
        if _CALENDAR_DAYS_OFF_RE.search(text):
            signals.add("calendar_days_off_prompt")
        if _ENROLLED_RE.search(text):
            signals.update({"status_enrolled", "needs_enrollment_status"})
        if _ACTIVE_RE.search(text):
            signals.add("status_active")
        if _SUBGROUP_RE.search(text):
            signals.add("subgroup_prompt")
        if _PROGRAM_RE.search(text):
            signals.update({"program_prompt", "needs_program_membership"})
        if _STAFF_ROLE_RE.search(text):
            signals.add("staff_role_prompt")
        if _has_school_literal(text):
            signals.update({"school_literal_present", "needs_school_filter"})

        if "student_listing" in signals:
            signals.add("needs_student_identity")
        if "student_aggregate" in signals and "enrolled" in lower:
            signals.update({"needs_enrollment_status", "needs_student_identity"})
        if "attendance" in lower or "attend" in lower:
            signals.add("needs_attendance_metric")
        if "grade" in lower or "gpa" in lower or "course grade" in lower:
            signals.add("needs_grade_metric")
        if "student" in lower and "school_literal_present" in signals:
            signals.add("student_listing")
            signals.add("listing_intent")
            signals.add("needs_student_identity")
        return sorted(signal for signal in signals if signal in PLANNER_RERANK_SIGNAL_KEYS)


__all__ = ["PromptSignalService"]


def _has_school_literal(text: str) -> bool:
    tokens = [token for token in re.findall(r"[A-Za-z0-9'&.-]+", str(text or "").lower()) if token]
    for idx, token in enumerate(tokens):
        if token not in _SCHOOL_LITERAL_SUFFIXES or idx == 0:
            continue
        start = max(0, idx - 4)
        preceding = [item for item in tokens[start:idx] if item not in _SCHOOL_LITERAL_STOPWORDS]
        if preceding:
            return True
    return False
