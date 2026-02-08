from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

import spacy
from spacy.language import Language
from spacy.pipeline import EntityRuler
from spacy.tokens import Doc, Span

LABEL_ATTR = "ED_ATTR"
LABEL_VALUE = "ED_VALUE"
LABEL_RACE_TOKEN = "ED_RACE_TOKEN"
LABEL_BOOL_TRUE = "ED_BOOL_TRUE"
LABEL_BOOL_FALSE = "ED_BOOL_FALSE"
LABEL_METRIC_COUNT = "ED_METRIC_COUNT"
LABEL_TIME_THIS_YEAR = "ED_TIME_THIS_YEAR"
LABEL_SCHOOL_YEAR_LITERAL = "ED_SCHOOL_YEAR_LITERAL"

NAME_COLUMNS = {"first_name", "last_name", "middle_name", "display_name"}

ATTR_PHRASES: Dict[str, List[str]] = {
    "first_name": ["first name", "firstname", "given name"],
    "last_name": ["last name", "lastname", "surname", "family name"],
    "middle_name": ["middle name"],
    "display_name": ["display name", "preferred name", "nickname"],
    "birth_country": ["born in", "birth country", "country of birth", "birthplace"],
    "race_ethnicity": ["race", "ethnicity", "race ethnicity", "race/ethnicity"],
    "gender": ["gender", "sex"],
    "is_active_enrollment": ["enrolled", "currently enrolled", "active enrollment", "enrollment"],
    "school_year": ["school year"],
}

BOOL_FLAG_PHRASES: Dict[str, List[str]] = {
    "is_special_education_active": ["iep", "special education", "sped"],
    "is_enlglish_learner_active": ["ell", "el", "english learner"],
    "is_homeless": ["homeless"],
    "is_migrant_education_active": ["migrant", "migrant education"],
    "is_foster": ["foster"],
    "is_cte_active": ["cte"],
    "is_food_service_active": ["free lunch", "reduced lunch", "food service"],
    "is_economic_disadvantaged": ["economically disadvantaged", "econ disadvantaged"],
}

RACE_TOKEN_MAP: Dict[str, str] = {
    "black": "Black - African American",
    "african american": "Black - African American",
    "white": "White",
    "caucasian": "White",
    "latinx": "Latinx",
    "latino": "Latinx",
    "latina": "Latinx",
    "hispanic": "Latinx",
    "asian": "Asian",
    "multiple": "Multiple",
    "multiracial": "Multiple",
    "two or more races": "Multiple",
    "native american": "American Indian - Alaska Native",
    "american indian": "American Indian - Alaska Native",
    "alaska native": "American Indian - Alaska Native",
    "pacific islander": "Native Hawaiian - Pacific Islander",
    "native hawaiian": "Native Hawaiian - Pacific Islander",
}

COUNT_PHRASES = ["how many", "count", "number of"]
TIME_THIS_YEAR_PHRASES = ["this year", "current year"]

NEGATION_TOKENS = {"not", "no", "non", "without", "minus", "excluding", "except", "never"}
VALUE_SKIP = {
    "is",
    "are",
    "was",
    "were",
    "equals",
    "equal",
    "to",
    "of",
    "the",
    "a",
    "an",
    "student",
    "students",
}
BREAK_TOKENS = {"and", "or", "with", "by", "for", "from", "in", "on", "at", "that", "who"}


@dataclass(frozen=True)
class _Entity:
    label: str
    text: str
    norm: str
    start_char: int
    end_char: int
    start: int
    end: int
    ent_id: str


@lru_cache(maxsize=2)
def build_nlp() -> Language:
    nlp = spacy.blank("en")
    ruler: EntityRuler = nlp.add_pipe("entity_ruler", config={"phrase_matcher_attr": "LOWER"})
    ruler.add_patterns(_build_patterns())
    return nlp


def extract_signals(text: str) -> Dict[str, Any]:
    text_val = text or ""
    doc = build_nlp()(text_val)

    base_entities = _collect_entities(doc)
    by_label = _group_by_label(base_entities)

    debug_entities: List[Dict[str, Any]] = []
    bool_filters: List[Tuple[str, bool]] = []

    for ent in base_entities:
        label = ent.label
        if ent.label == LABEL_BOOL_TRUE:
            negated = _is_negated(doc, ent.start)
            label = LABEL_BOOL_FALSE if negated else LABEL_BOOL_TRUE
            bool_filters.append((ent.norm, not negated))
        debug_entities.append(
            {
                "label": label,
                "text": ent.text,
                "norm": ent.norm,
                "span": [ent.start_char, ent.end_char],
                "confidence": 1.0,
            }
        )

    metric = "COUNT" if by_label.get(LABEL_METRIC_COUNT) else None
    filters: List[Dict[str, Any]] = []
    seen = set()

    for column, value in bool_filters:
        _add_filter(filters, seen, column, value)

    for race_ent in by_label.get(LABEL_RACE_TOKEN, []):
        _add_filter(filters, seen, "race_ethnicity", race_ent.norm)

    value_entities: List[Dict[str, Any]] = []
    has_school_year = any(f["column"] == "school_year" for f in filters)

    for attr_ent in by_label.get(LABEL_ATTR, []):
        column = attr_ent.ent_id
        if not column:
            continue

        if column == "is_active_enrollment":
            value = not _is_negated(doc, attr_ent.start)
            _add_filter(filters, seen, column, value)
            continue

        if column == "school_year":
            year_value, value_span = _find_year_value(attr_ent, doc, by_label)
            if year_value:
                _add_filter(filters, seen, column, year_value)
                if value_span:
                    value_entities.append(_value_entity(doc, value_span, year_value))
                has_school_year = True
            continue

        if column == "race_ethnicity":
            value = _race_near(attr_ent, by_label)
            if value:
                _add_filter(filters, seen, column, value)
            else:
                value_text, value_span = _find_value_after(attr_ent, doc, allow_multi=True)
                if value_text:
                    norm_value = _normalize_race_token(value_text)
                    _add_filter(filters, seen, column, norm_value)
                    if value_span:
                        value_entities.append(_value_entity(doc, value_span, norm_value))
            continue

        if column in NAME_COLUMNS:
            value_text, value_span = _find_value_after(attr_ent, doc, allow_multi=False)
            if value_text:
                norm_value = _normalize_name(value_text)
                _add_filter(filters, seen, column, norm_value)
                if value_span:
                    value_entities.append(_value_entity(doc, value_span, norm_value))
            continue

        if column == "birth_country":
            value_text, value_span = _find_value_after(attr_ent, doc, allow_multi=True)
            if value_text:
                norm_value = _title_case(value_text)
                _add_filter(filters, seen, column, norm_value)
                if value_span:
                    value_entities.append(_value_entity(doc, value_span, norm_value))
            continue

        if column == "gender":
            value_text, value_span = _find_value_after(attr_ent, doc, allow_multi=False)
            if value_text:
                norm_value = _normalize_gender(value_text)
                _add_filter(filters, seen, column, norm_value)
                if value_span:
                    value_entities.append(_value_entity(doc, value_span, norm_value))
            continue

        value_text, value_span = _find_value_after(attr_ent, doc, allow_multi=True)
        if value_text:
            norm_value = _title_case(value_text)
            _add_filter(filters, seen, column, norm_value)
            if value_span:
                value_entities.append(_value_entity(doc, value_span, norm_value))

    if not has_school_year:
        if by_label.get(LABEL_SCHOOL_YEAR_LITERAL):
            year_value = by_label[LABEL_SCHOOL_YEAR_LITERAL][0].norm
            _add_filter(filters, seen, "school_year", year_value)
            has_school_year = True
        elif by_label.get(LABEL_TIME_THIS_YEAR):
            _add_filter(filters, seen, "school_year", "CURRENT")
            has_school_year = True

    if not any(f["column"] == "is_active_enrollment" for f in filters):
        if _has_enrolled_token(doc):
            value = not _is_negated_token(doc, "enrolled")
            _add_filter(filters, seen, "is_active_enrollment", value)

    debug_entities.extend(value_entities)
    debug_entities.sort(key=lambda item: item["span"][0])

    return {
        "text": text_val,
        "metric": metric,
        "filters": filters,
        "debug": {"entities": debug_entities},
    }


def _collect_entities(doc: Doc) -> List[_Entity]:
    entities: List[_Entity] = []
    for ent in doc.ents:
        norm = _normalize_entity(ent)
        entities.append(
            _Entity(
                label=ent.label_,
                text=ent.text,
                norm=norm,
                start_char=ent.start_char,
                end_char=ent.end_char,
                start=ent.start,
                end=ent.end,
                ent_id=ent.ent_id_,
            )
        )
    return entities


def _group_by_label(entities: Iterable[_Entity]) -> Dict[str, List[_Entity]]:
    grouped: Dict[str, List[_Entity]] = {}
    for ent in entities:
        grouped.setdefault(ent.label, []).append(ent)
    return grouped


def _normalize_entity(ent: Span) -> str:
    if ent.label_ == LABEL_ATTR:
        return ent.ent_id_ or ent.text
    if ent.label_ == LABEL_RACE_TOKEN:
        return _normalize_race_token(ent.text)
    if ent.label_ == LABEL_METRIC_COUNT:
        return "COUNT"
    if ent.label_ == LABEL_TIME_THIS_YEAR:
        return "CURRENT"
    if ent.label_ == LABEL_SCHOOL_YEAR_LITERAL:
        return _normalize_school_year(ent.text)
    if ent.label_ in {LABEL_BOOL_TRUE, LABEL_BOOL_FALSE}:
        return ent.ent_id_ or ent.text
    return ent.text


def _build_patterns() -> List[Dict[str, Any]]:
    patterns: List[Dict[str, Any]] = []

    for column, phrases in ATTR_PHRASES.items():
        for phrase in phrases:
            patterns.append({"label": LABEL_ATTR, "id": column, "pattern": phrase})

    for column, phrases in BOOL_FLAG_PHRASES.items():
        for phrase in phrases:
            patterns.append({"label": LABEL_BOOL_TRUE, "id": column, "pattern": phrase})

    for phrase in COUNT_PHRASES:
        patterns.append({"label": LABEL_METRIC_COUNT, "pattern": phrase})

    for phrase in TIME_THIS_YEAR_PHRASES:
        patterns.append({"label": LABEL_TIME_THIS_YEAR, "pattern": phrase})

    for phrase in RACE_TOKEN_MAP:
        patterns.append({"label": LABEL_RACE_TOKEN, "pattern": phrase})

    patterns += [
        {"label": LABEL_SCHOOL_YEAR_LITERAL, "pattern": [{"TEXT": {"REGEX": r"^20\d{2}$"}}]},
        {
            "label": LABEL_SCHOOL_YEAR_LITERAL,
            "pattern": [{"TEXT": {"REGEX": r"^20\d{2}[-/](?:\d{2}|20\d{2})$"}}],
        },
        {
            "label": LABEL_SCHOOL_YEAR_LITERAL,
            "pattern": [
                {"TEXT": {"REGEX": r"^20\d{2}$"}},
                {"TEXT": {"REGEX": r"^[-/]$"}},
                {"TEXT": {"REGEX": r"^(?:\d{2}|20\d{2})$"}},
            ],
        },
    ]

    return patterns


def _add_filter(filters: List[Dict[str, Any]], seen: set, column: str, value: Any) -> None:
    key = (column, "=", value)
    if key in seen:
        return
    seen.add(key)
    filters.append({"column": column, "op": "=", "value": value})


def _normalize_race_token(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"\s+", " ", value)
    return RACE_TOKEN_MAP.get(value, _title_case(text))


def _normalize_school_year(text: str) -> str:
    value = text.strip()
    match = re.search(r"(20\d{2})\s*[-/]\s*(?:\d{2}|20\d{2})", value)
    if match:
        return match.group(1)
    match = re.search(r"\b(20\d{2})\b", value)
    if match:
        return match.group(1)
    return value


def _normalize_name(text: str) -> str:
    return _title_case(text)


def _normalize_gender(text: str) -> str:
    value = text.strip().lower()
    if value in {"male", "m", "man", "boy"}:
        return "Male"
    if value in {"female", "f", "woman", "girl"}:
        return "Female"
    return _title_case(text)


def _title_case(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return cleaned
    return " ".join(part.capitalize() for part in cleaned.split(" "))


def _race_near(attr_ent: _Entity, by_label: Dict[str, List[_Entity]]) -> Optional[str]:
    race_entities = by_label.get(LABEL_RACE_TOKEN, [])
    if not race_entities:
        return None
    for race_ent in race_entities:
        if race_ent.start >= attr_ent.end and race_ent.start - attr_ent.end <= 8:
            return race_ent.norm
    return race_entities[0].norm


def _find_year_value(
    attr_ent: _Entity,
    doc: Doc,
    by_label: Dict[str, List[_Entity]],
) -> Tuple[Optional[str], Optional[Tuple[int, int]]]:
    for year_ent in by_label.get(LABEL_SCHOOL_YEAR_LITERAL, []):
        if year_ent.start >= attr_ent.end and year_ent.start - attr_ent.end <= 8:
            return year_ent.norm, (year_ent.start, year_ent.end)
    for time_ent in by_label.get(LABEL_TIME_THIS_YEAR, []):
        if time_ent.start >= attr_ent.end and time_ent.start - attr_ent.end <= 8:
            return "CURRENT", (time_ent.start, time_ent.end)
    return None, None


def _find_value_after(
    attr_ent: _Entity,
    doc: Doc,
    *,
    allow_multi: bool,
    max_distance: int = 8,
) -> Tuple[Optional[str], Optional[Tuple[int, int]]]:
    start_idx = attr_ent.end
    end_limit = min(len(doc), start_idx + max_distance)
    idx = start_idx
    while idx < end_limit:
        tok = doc[idx]
        if tok.is_space or tok.is_punct:
            idx += 1
            continue
        if tok.lower_ in VALUE_SKIP:
            idx += 1
            continue
        if tok.text in {"'", '"'}:
            idx += 1
            continue
        if not tok.is_alpha and not tok.like_num:
            idx += 1
            continue
        if allow_multi:
            value, span = _collect_phrase(doc, idx, end_limit)
            if value:
                return value, span
        else:
            return tok.text, (idx, idx + 1)
        idx += 1
    return None, None


def _collect_phrase(doc: Doc, start: int, end_limit: int, max_words: int = 3) -> Tuple[str, Tuple[int, int]]:
    words: List[str] = []
    idx = start
    while idx < end_limit and len(words) < max_words:
        tok = doc[idx]
        if not tok.is_alpha:
            break
        if tok.lower_ in BREAK_TOKENS:
            break
        words.append(tok.text)
        idx += 1
    return " ".join(words), (start, idx)


def _value_entity(doc: Doc, span: Tuple[int, int], norm_value: str) -> Dict[str, Any]:
    start, end = span
    if start >= len(doc):
        return {
            "label": LABEL_VALUE,
            "text": norm_value,
            "norm": norm_value,
            "span": [0, 0],
            "confidence": 1.0,
        }
    start_char = doc[start].idx
    end_char = doc[end - 1].idx + len(doc[end - 1]) if end - 1 < len(doc) else start_char
    text = doc.text[start_char:end_char]
    return {
        "label": LABEL_VALUE,
        "text": text,
        "norm": norm_value,
        "span": [start_char, end_char],
        "confidence": 1.0,
    }


def _is_negated(doc: Doc, start_token: int, window: int = 3) -> bool:
    start = max(0, start_token - window)
    for tok in doc[start:start_token]:
        if tok.lower_ in NEGATION_TOKENS:
            return True
        if tok.lower_.startswith("non") and len(tok.lower_) > 3:
            return True
    return False


def _is_negated_token(doc: Doc, token_text: str) -> bool:
    for tok in doc:
        if tok.lower_ == token_text:
            return _is_negated(doc, tok.i)
    return False


def _has_enrolled_token(doc: Doc) -> bool:
    for tok in doc:
        if tok.lower_ in {"enrolled", "enrollment"}:
            return True
    return False
