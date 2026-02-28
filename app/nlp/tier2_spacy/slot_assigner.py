from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from app.nlp.tier2_spacy.schema import (
    Tier2AssessmentSlot,
    Tier2AttendanceSlot,
    Tier2CalendarSlot,
    Tier2CourseSlot,
    Tier2DisciplineSlot,
    Tier2GradesSlot,
    Tier2NameSlot,
    Tier2Slots,
    Tier2ValueSlot,
)

_NAME_PATTERN = re.compile(r"\b(?:named|name\s+is|called)\b\s*(?:[\"']([^\"']{1,80})[\"']|([A-Za-z][A-Za-z'\-]{1,40}(?:\s+[A-Za-z][A-Za-z'\-]{1,40})?))", re.IGNORECASE)
_SCHOOL_AT_PATTERN = re.compile(
    r"\bat(?:\s+the)?\s+([A-Za-z0-9][A-Za-z0-9'&\-\s]{0,120}?(?:Elementary School|Middle School|High School|School))\b",
    re.IGNORECASE,
)
_DISTRICT_PATTERN = re.compile(
    r"\b([A-Za-z0-9][A-Za-z0-9'&\-\s]{0,120}?(?:District|County|LEA))\b",
    re.IGNORECASE,
)
_GRADE_PATTERN = re.compile(r"\b(?:grade\s+)?([Kk]|[0-9]{1,2})(?:st|nd|rd|th)?\b")
_COUNTRY_PATTERN = re.compile(r"\b(?:born\s+in|from)\s+([A-Za-z][A-Za-z\s]{1,40})\b", re.IGNORECASE)
_DATE_RANGE_PATTERN = re.compile(r"\bbetween\s+([A-Za-z0-9\-/\s]+?)\s+and\s+([A-Za-z0-9\-/\s]+?)\b", re.IGNORECASE)
_SCHOOL_YEAR_PATTERN = re.compile(r"\b(20\d{2})\s*[-/]\s*(20\d{2})\b")
_COURSE_CODE_PATTERN = re.compile(r"\b([A-Z]{2,5}-?\d{1,4})\b")
_SECTION_PATTERN = re.compile(r"\bsection\s+([A-Za-z0-9_-]{1,20})\b", re.IGNORECASE)
_NEGATION_PATTERN = re.compile(r"\b(not|excluding|except|without|!=|doesn't|isn't|aren't)\b", re.IGNORECASE)
_COMPARATOR_PATTERN = re.compile(r"\b(above|below|greater\s+than|less\s+than|>=|<=|>|<|=|!=)\s+([A-Za-z0-9.%-]+)", re.IGNORECASE)

_RACE_TERMS = {
    "black": "BLACK",
    "african american": "BLACK",
    "white": "WHITE",
    "asian": "ASIAN",
    "hispanic": "HISPANIC",
    "latino": "HISPANIC",
    "latinx": "HISPANIC",
    "native american": "NATIVE_AMERICAN",
    "pacific islander": "PACIFIC_ISLANDER",
    "two or more": "MULTIRACIAL",
}

_ATTENDANCE_TERMS = {
    "absent": "absent",
    "tardy": "tardy",
    "present": "present",
}

_DISCIPLINE_TERMS = {
    "suspension": "suspension",
    "suspended": "suspension",
    "expulsion": "expulsion",
    "expelled": "expulsion",
    "referral": "referral",
}

_GRADING_PERIOD_TERMS = ("quarter", "semester", "trimester", "grading period")


def assign_slots(
    *,
    prompt: str,
    doc_entities: Sequence[Dict[str, Any]],
    topic_scores: Dict[str, float],
) -> Tuple[Tier2Slots, Dict[str, Any], Dict[str, Any], List[str]]:
    text = str(prompt or "").strip()
    lowered = text.lower()
    slots = Tier2Slots()
    warnings: List[str] = []

    _assign_names(text, slots)
    _assign_school(text, slots)
    _assign_district(text, slots)
    _assign_grade(lowered, slots)
    _assign_country(text, slots)
    _assign_race(lowered, slots)
    _assign_course_and_section(text, slots)
    _assign_calendar(text, lowered, slots)
    _assign_attendance(lowered, slots)
    _assign_discipline(lowered, slots)
    _assign_assessment_and_grades(text, lowered, slots)

    _merge_doc_entities(doc_entities, slots)

    operators = {
        "negation": bool(_NEGATION_PATTERN.search(text)),
        "comparators": _extract_comparators(text),
    }
    if operators["negation"]:
        slots.negations.append(Tier2ValueSlot(value="negation", confidence=0.8))

    intent = {
        "label": _infer_intent_label(topic_scores=topic_scores, slots=slots, prompt=lowered),
        "scores": _infer_intent_scores(topic_scores=topic_scores, slots=slots, prompt=lowered),
    }

    _dedupe_slots(slots)
    return slots, operators, intent, warnings


def _assign_names(text: str, slots: Tier2Slots) -> None:
    for match in _NAME_PATTERN.finditer(text):
        value = (match.group(1) or match.group(2) or "").strip(" \t\r\n.,;:!?()[]{}\"'")
        if not value:
            continue
        pieces = [p for p in re.split(r"\s+", value) if p]
        kind = "full" if len(pieces) > 1 else "unknown"
        slots.names.append(Tier2NameSlot(kind=kind, value=value, confidence=0.92))


def _assign_school(text: str, slots: Tier2Slots) -> None:
    for match in _SCHOOL_AT_PATTERN.finditer(text):
        value = match.group(1).strip(" \t\r\n.,;:!?()[]{}\"'")
        if value:
            slots.school.append(Tier2ValueSlot(value=value, confidence=0.9))


def _assign_district(text: str, slots: Tier2Slots) -> None:
    for match in _DISTRICT_PATTERN.finditer(text):
        value = match.group(1).strip(" \t\r\n.,;:!?()[]{}\"'")
        if value:
            slots.district.append(Tier2ValueSlot(value=value, confidence=0.84))


def _assign_grade(lowered: str, slots: Tier2Slots) -> None:
    for match in _GRADE_PATTERN.finditer(lowered):
        value = str(match.group(1) or "").strip()
        if value:
            slots.grade.append(Tier2ValueSlot(value=value.upper(), confidence=0.82))


def _assign_country(text: str, slots: Tier2Slots) -> None:
    for match in _COUNTRY_PATTERN.finditer(text):
        value = str(match.group(1) or "").strip(" \t\r\n.,;:!?()[]{}\"'")
        if value:
            slots.country.append(Tier2ValueSlot(value=value, confidence=0.78))


def _assign_race(lowered: str, slots: Tier2Slots) -> None:
    for token, canonical in _RACE_TERMS.items():
        if token in lowered:
            slots.race.append(Tier2ValueSlot(value=canonical, confidence=0.75))


def _assign_course_and_section(text: str, slots: Tier2Slots) -> None:
    course_code = _COURSE_CODE_PATTERN.search(text)
    if course_code:
        slots.course.append(Tier2CourseSlot(code=course_code.group(1), confidence=0.78))

    section_match = _SECTION_PATTERN.search(text)
    if section_match:
        slots.section.append(Tier2SectionSlot(id=section_match.group(1), confidence=0.82))

    lowered = text.lower()
    for course_name in ("algebra", "geometry", "biology", "english", "history", "math"):
        if course_name in lowered:
            slots.course.append(Tier2CourseSlot(name=course_name.title(), confidence=0.68))


def _assign_calendar(text: str, lowered: str, slots: Tier2Slots) -> None:
    date_range = _DATE_RANGE_PATTERN.search(text)
    if date_range:
        slots.calendar.append(
            Tier2CalendarSlot(
                date_range=f"{date_range.group(1).strip()} to {date_range.group(2).strip()}",
                confidence=0.82,
            )
        )

    school_year = _SCHOOL_YEAR_PATTERN.search(text)
    if school_year:
        slots.calendar.append(
            Tier2CalendarSlot(
                school_year=f"{school_year.group(1)}-{school_year.group(2)}",
                confidence=0.9,
            )
        )

    for marker in ("holiday", "semester", "term", "school day"):
        if marker in lowered:
            slots.calendar.append(Tier2CalendarSlot(event_type=marker, confidence=0.7))


def _assign_attendance(lowered: str, slots: Tier2Slots) -> None:
    for token, status in _ATTENDANCE_TERMS.items():
        if token in lowered:
            slots.attendance.append(Tier2AttendanceSlot(status=status, confidence=0.78))


def _assign_discipline(lowered: str, slots: Tier2Slots) -> None:
    for token, incident in _DISCIPLINE_TERMS.items():
        if token in lowered:
            slots.discipline.append(Tier2DisciplineSlot(incident_type=incident, confidence=0.8))


def _assign_assessment_and_grades(text: str, lowered: str, slots: Tier2Slots) -> None:
    for marker in ("assessment", "benchmark", "act", "sat", "test"):
        if marker in lowered:
            slots.assessments.append(Tier2AssessmentSlot(type=marker, confidence=0.74))

    for period in _GRADING_PERIOD_TERMS:
        if period in lowered:
            slots.grades.append(Tier2GradesSlot(grading_period=period, confidence=0.66))

    gpa_match = re.search(r"\bgpa\s*(?:above|over|>=|>|=)?\s*([0-9]+(?:\.[0-9]+)?)", lowered)
    if gpa_match:
        slots.grades.append(Tier2GradesSlot(gpa=gpa_match.group(1), confidence=0.85))


def _merge_doc_entities(doc_entities: Sequence[Dict[str, Any]], slots: Tier2Slots) -> None:
    for ent in doc_entities:
        label = str(ent.get("label") or "").upper()
        text = str(ent.get("text") or "").strip()
        score = float(ent.get("score") or 0.65)
        if not text:
            continue
        if label in {"PERSON_NAME", "SLOT_FIRST_NAME", "SLOT_LAST_NAME", "VALUE_LITERAL"}:
            kind = "unknown"
            if label == "SLOT_FIRST_NAME":
                kind = "first"
            elif label == "SLOT_LAST_NAME":
                kind = "last"
            slots.names.append(Tier2NameSlot(kind=kind, value=text, confidence=min(1.0, max(0.0, score))))
        elif label in {"ORG_NAME", "SLOT_SCHOOL_NAME"}:
            slots.school.append(Tier2ValueSlot(value=text, confidence=min(1.0, max(0.0, score))))
        elif label == "SLOT_DISTRICT_NAME":
            slots.district.append(Tier2ValueSlot(value=text, confidence=min(1.0, max(0.0, score))))
        elif label in {"SLOT_GRADE", "GRADE_LEVEL"}:
            slots.grade.append(Tier2ValueSlot(value=text, confidence=min(1.0, max(0.0, score))))
        elif label in {"SLOT_COUNTRY", "COUNTRY"}:
            slots.country.append(Tier2ValueSlot(value=text, confidence=min(1.0, max(0.0, score))))


def _extract_comparators(text: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for match in _COMPARATOR_PATTERN.finditer(text):
        op = str(match.group(1) or "").strip().lower()
        value = str(match.group(2) or "").strip()
        normalized = {
            "above": ">",
            "greater than": ">",
            "below": "<",
            "less than": "<",
        }.get(op, op)
        out.append({"slot": "unknown", "op": normalized, "value": value})
    return out


def _infer_intent_label(*, topic_scores: Dict[str, float], slots: Tier2Slots, prompt: str) -> str:
    if "count" in prompt or "how many" in prompt:
        return "intent_aggregate"
    if slots.names:
        return "intent_lookup_by_name"
    if slots.race or slots.grade or slots.country:
        return "intent_demographic_slice"
    if topic_scores:
        if max(topic_scores.values()) > 0.9:
            return "intent_filter"
    return "intent_select_list"


def _infer_intent_scores(*, topic_scores: Dict[str, float], slots: Tier2Slots, prompt: str) -> Dict[str, float]:
    out = {
        "intent_select_list": 0.4,
        "intent_filter": 0.5,
        "intent_aggregate": 0.1,
        "intent_lookup_by_name": 0.1,
        "intent_demographic_slice": 0.1,
    }
    if "count" in prompt or "how many" in prompt:
        out["intent_aggregate"] = 0.95
    if slots.names:
        out["intent_lookup_by_name"] = max(out["intent_lookup_by_name"], 0.92)
    if slots.race or slots.grade or slots.country:
        out["intent_demographic_slice"] = max(out["intent_demographic_slice"], 0.9)
    if topic_scores:
        out["intent_filter"] = max(out["intent_filter"], min(0.95, max(topic_scores.values())))
    # keep deterministic but normalized enough for consumers
    return {k: round(min(1.0, max(0.0, v)), 4) for k, v in out.items()}


def _dedupe_slots(slots: Tier2Slots) -> None:
    def _dedupe(items: Iterable[Any], key_fn):
        seen = set()
        out = []
        for item in items:
            key = key_fn(item)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    slots.names = _dedupe(slots.names, lambda item: (item.kind, item.value.lower()))
    slots.school = _dedupe(slots.school, lambda item: item.value.lower())
    slots.district = _dedupe(slots.district, lambda item: item.value.lower())
    slots.race = _dedupe(slots.race, lambda item: item.value.lower())
    slots.grade = _dedupe(slots.grade, lambda item: item.value.lower())
    slots.country = _dedupe(slots.country, lambda item: item.value.lower())
    slots.state = _dedupe(slots.state, lambda item: item.value.lower())
    slots.negations = _dedupe(slots.negations, lambda item: item.value.lower())
    slots.course = _dedupe(slots.course, lambda item: (str(item.code or "").lower(), str(item.name or "").lower(), str(item.subject or "").lower()))
    slots.section = _dedupe(slots.section, lambda item: (str(item.id or "").lower(), str(item.name or "").lower(), str(item.period or "").lower(), str(item.term or "").lower(), str(item.teacher_name or "").lower()))
    slots.calendar = _dedupe(slots.calendar, lambda item: (str(item.date or "").lower(), str(item.date_range or "").lower(), str(item.school_year or "").lower(), str(item.term_name or "").lower(), str(item.event_type or "").lower()))
    slots.attendance = _dedupe(slots.attendance, lambda item: (str(item.status or "").lower(), str(item.minutes or "").lower(), str(item.excuse or "").lower(), str(item.date or "").lower()))
    slots.discipline = _dedupe(slots.discipline, lambda item: (str(item.incident_type or "").lower(), str(item.action or "").lower(), str(item.duration_days or "").lower(), str(item.severity or "").lower(), str(item.date or "").lower()))
    slots.assessments = _dedupe(slots.assessments, lambda item: (str(item.name or "").lower(), str(item.type or "").lower(), str(item.score or "").lower(), str(item.performance_level or "").lower(), str(item.proficiency or "").lower(), str(item.date or "").lower()))
    slots.grades = _dedupe(slots.grades, lambda item: (str(item.student_grade_level or "").lower(), str(item.course_grade or "").lower(), str(item.gpa or "").lower(), str(item.credits or "").lower(), str(item.grading_period or "").lower()))
