from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, List

import spacy
from spacy.language import Language
from spacy.pipeline import EntityRuler

LABEL_DOMAIN = "ED_DOMAIN"
LABEL_ENTITY = "ED_ENTITY"
LABEL_SCHOOL_YEAR = "ED_SCHOOL_YEAR"
LABEL_TERM = "ED_TERM"
LABEL_GRADING_PERIOD = "ED_GRADING_PERIOD"
LABEL_DATE_RANGE = "ED_DATE_RANGE"
LABEL_DATE = "ED_DATE"
LABEL_DEMOGRAPHIC = "ED_DEMOGRAPHIC"
LABEL_GRADE_LEVEL = "ED_GRADE_LEVEL"
LABEL_PROGRAM_FLAG = "ED_PROGRAM_FLAG"
LABEL_METRIC = "ED_METRIC"
LABEL_EVENT = "ED_EVENT"
LABEL_GROUP_BY = "ED_GROUP_BY"
LABEL_ORDER_BY = "ED_ORDER_BY"
LABEL_LIMIT = "ED_LIMIT"
LABEL_COMPARISON = "ED_COMPARISON"
LABEL_COLUMN_REF = "ED_COLUMN_REF"


@lru_cache(maxsize=2)
def build_nlp() -> Language:
    nlp = spacy.blank("en")
    ruler: EntityRuler = nlp.add_pipe("entity_ruler", config={"phrase_matcher_attr": "LOWER"})
    ruler.add_patterns(_build_patterns())
    return nlp


def extract_entities(text: str) -> Dict[str, Any]:
    text_val = text or ""
    nlp = build_nlp()
    doc = nlp(text_val)
    entities: List[Dict[str, Any]] = []
    for ent in doc.ents:
        entities.append(
            {
                "label": ent.label_,
                "text": ent.text,
                "norm": _normalize_entity(ent.label_, ent.text),
                "span": [ent.start_char, ent.end_char],
                "confidence": 1.0,
            }
        )

    return {
        "text": text_val,
        "entities": entities,
        "hints": {},
    }


def resolve_signals(workspace_id: str, extracted: Dict[str, Any]) -> Dict[str, Any]:
    del workspace_id
    return extracted


def _build_patterns() -> List[Dict[str, Any]]:
    patterns: List[Dict[str, Any]] = []

    patterns += _phrase_patterns(
        LABEL_DOMAIN,
        [
            "attendance",
            "enrollment",
            "grades",
            "gpa",
            "transcript",
            "assessments",
            "assessment",
            "discipline",
            "programs",
            "program",
            "calendars",
            "calendar",
        ],
    )

    patterns += _phrase_patterns(
        LABEL_METRIC,
        [
            "absences",
            "absence",
            "tardy",
            "chronic absenteeism",
            "ada",
            "gpa",
            "credits",
            "credits earned",
            "report card",
            "test score",
            "scaled score",
            "performance level",
            "proficiency",
            "benchmark",
            "eoc",
        ],
    )

    patterns += _phrase_patterns(
        LABEL_EVENT,
        [
            "referral",
            "suspension",
            "expulsion",
            "iss",
            "oss",
        ],
    )

    patterns += _phrase_patterns(
        LABEL_PROGRAM_FLAG,
        [
            "iep",
            "sped",
            "504",
            "el",
            "ell",
            "homeless",
            "migrant",
            "foster",
            "economically disadvantaged",
            "econ disadvantaged",
            "gifted",
        ],
    )

    patterns += _phrase_patterns(
        LABEL_DEMOGRAPHIC,
        [
            "homeless",
            "migrant",
            "foster",
            "economically disadvantaged",
            "econ disadvantaged",
            "english learner",
            "special education",
        ],
    )

    patterns += _phrase_patterns(
        LABEL_TERM,
        [
            "term",
            "semester",
            "quarter",
        ],
    )

    patterns += _phrase_patterns(
        LABEL_GRADING_PERIOD,
        [
            "grading period",
            "marking period",
            "q1",
            "q2",
            "q3",
            "q4",
        ],
    )

    patterns += _phrase_patterns(
        LABEL_GROUP_BY,
        [
            "by school",
            "by district",
            "by grade",
            "by teacher",
            "by course",
            "by section",
        ],
    )

    patterns += _phrase_patterns(
        LABEL_ORDER_BY,
        [
            "order by",
            "sort by",
        ],
    )

    patterns += _phrase_patterns(
        LABEL_LIMIT,
        [
            "top",
            "limit",
        ],
    )

    patterns += _phrase_patterns(
        LABEL_COMPARISON,
        [
            "greater than",
            "less than",
            "at least",
            "at most",
        ],
    )

    patterns += _phrase_patterns(
        LABEL_SCHOOL_YEAR,
        [
            "school year",
        ],
    )

    patterns += [
        {
            "label": LABEL_SCHOOL_YEAR,
            "pattern": [
                {"LOWER": "sy"},
                {"TEXT": {"REGEX": r"^20\d{2}$"}},
            ],
        },
        {
            "label": LABEL_SCHOOL_YEAR,
            "pattern": [{"TEXT": {"REGEX": r"^20\d{2}[-/](?:\d{2}|20\d{2})$"}}],
        },
        {
            "label": LABEL_SCHOOL_YEAR,
            "pattern": [
                {"TEXT": {"REGEX": r"^20\d{2}$"}},
                {"TEXT": {"REGEX": r"^[-/–]$"}},
                {"TEXT": {"REGEX": r"^(?:\d{2}|20\d{2})$"}},
            ],
        },
        {
            "label": LABEL_GRADE_LEVEL,
            "pattern": [
                {"LOWER": {"IN": ["grade", "gr"]}},
                {"TEXT": {"REGEX": r"^(?:[1-9]|1[0-2]|k|K)$"}},
            ],
        },
        {
            "label": LABEL_GRADE_LEVEL,
            "pattern": [
                {"TEXT": {"REGEX": r"^(?:[1-9]|1[0-2])(st|nd|rd|th)$"}},
                {"LOWER": "grade"},
            ],
        },
        {
            "label": LABEL_GRADE_LEVEL,
            "pattern": [{"LOWER": "kindergarten"}],
        },
        {
            "label": LABEL_GRADE_LEVEL,
            "pattern": [{"TEXT": {"REGEX": r"^(?:K|k)$"}}],
        },
        {
            "label": LABEL_GRADE_LEVEL,
            "pattern": [{"TEXT": {"REGEX": r"^(?:[1-9]|1[0-2])(st|nd|rd|th)$"}}],
        },
        {
            "label": LABEL_DATE,
            "pattern": [{"TEXT": {"REGEX": r"^\d{4}-\d{2}-\d{2}$"}}],
        },
        {
            "label": LABEL_DATE,
            "pattern": [{"TEXT": {"REGEX": r"^\d{1,2}/\d{1,2}/\d{4}$"}}],
        },
        {
            "label": LABEL_DATE_RANGE,
            "pattern": [
                {"LOWER": {"IN": ["between", "from"]}},
                {"TEXT": {"REGEX": r"^\d{4}-\d{2}-\d{2}$"}},
                {"LOWER": {"IN": ["and", "to"]}},
                {"TEXT": {"REGEX": r"^\d{4}-\d{2}-\d{2}$"}},
            ],
        },
    ]

    return patterns


def _phrase_patterns(label: str, phrases: List[str]) -> List[Dict[str, Any]]:
    return [{"label": label, "pattern": phrase} for phrase in phrases]


def _normalize_entity(label: str, text: str) -> str:
    if label == LABEL_GRADE_LEVEL:
        return _normalize_grade_level(text)
    if label == LABEL_SCHOOL_YEAR:
        return _normalize_school_year(text)
    if label == LABEL_GROUP_BY:
        return _normalize_group_by(text)
    return _to_snake(text)


def _normalize_grade_level(text: str) -> str:
    value = text.strip().lower()
    if re.search(r"\b(k|kindergarten)\b", value):
        return "K"

    match = re.search(r"\b(1[0-2]|[1-9])(?:st|nd|rd|th)?\b", value)
    if match:
        return match.group(1)

    return _to_snake(text)


def _normalize_school_year(text: str) -> str:
    value = text.strip()
    match = re.search(r"(20\d{2})\s*[-/–]\s*(?:\d{2}|20\d{2})", value)
    if match:
        return match.group(1)

    match = re.search(r"\b(20\d{2})\b", value)
    if match:
        return match.group(1)

    return _to_snake(text)


def _normalize_group_by(text: str) -> str:
    value = text.strip().lower()
    if value.startswith("by "):
        value = value[3:]
    return _to_snake(value)


def _to_snake(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower())
    return cleaned.strip("_")
