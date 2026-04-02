from __future__ import annotations

import re

DEFAULT_TEMPERATURE = 0.2
DEFAULT_TOP_P = 0.8
DEFAULT_MAX_TOKENS = 700
MAX_REPAIR_PREVIOUS_OUTPUT_CHARS = 3000
MAX_RAW_MODEL_LOG_CHARS = 10000
ALLOWED_EDIT_OPS = {"setDomain", "addSelect", "addFilter", "addGroupBy", "addAggregate", "addSort"}
_ALLOWED_COL_KEYS = {"modelColumnId", "columnName", "workspaceTableId", "exprId", "alias"}
LEGACY_FILTER_OPERATOR_MAP = {
    "=": "equals",
    "==": "equals",
    "!=": "not_equals",
    "<>": "not_equals",
    "ne": "not_equals",
    "not_equal": "not_equals",
    "not_equals": "not_equals",
    "in": "in",
    "not in": "not_in",
    "not_in": "not_in",
    "gte": "gte",
    ">=": "gte",
    "lte": "lte",
    "<=": "lte",
    "is null": "is_null",
    "is_null": "is_null",
    "is not null": "is_not_null",
    "is_not_null": "is_not_null",
    "between": "between",
}
US_STATE_NAME_TO_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}
US_STATE_ABBR_TO_NAME = {abbr.lower(): name.title() for name, abbr in US_STATE_NAME_TO_ABBR.items()}
COUNTRY_NAME_TO_ABBR = {
    "united states": "US",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "mexico": "MX",
    "canada": "CA",
}
COUNTRY_ABBR_TO_NAME = {
    "us": "United States",
    "mx": "Mexico",
    "ca": "Canada",
}
ORDINAL_NUM_TO_WORD = {
    "1st": "first", "2nd": "second", "3rd": "third", "4th": "fourth",
    "5th": "fifth", "6th": "sixth", "7th": "seventh", "8th": "eighth",
    "9th": "ninth", "10th": "tenth", "11th": "eleventh", "12th": "twelfth",
    "13th": "thirteenth", "14th": "fourteenth", "15th": "fifteenth",
    "16th": "sixteenth", "17th": "seventeenth", "18th": "eighteenth",
    "19th": "nineteenth", "20th": "twentieth",
}
ORDINAL_WORD_TO_NUM = {word: num for num, word in ORDINAL_NUM_TO_WORD.items()}
ORDINAL_NUM_TO_INT = {
    token: int(re.match(r"^(\d+)", token).group(1))  # type: ignore[union-attr]
    for token in ORDINAL_NUM_TO_WORD
}
ORDINAL_WORD_TO_INT = {word: ORDINAL_NUM_TO_INT[token] for word, token in ORDINAL_WORD_TO_NUM.items()}
_QUOTED_LITERAL_RE = re.compile(r"'[^']+'|\"[^\"]+\"")
_YEAR_LITERAL_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_NUMBER_LITERAL_RE = re.compile(r"\b\d+\b")
_BOOLEAN_LITERAL_RE = re.compile(r"\b(?:true|false)\b", re.IGNORECASE)
_LABEL_VALUE_LITERAL_RE = re.compile(
    r"\b(?:name|first\s+name|last\s+name|student|teacher|school|district|city|state|email)\b\s+[A-Z][a-zA-Z'\-]*\b"
)


def _sanitize_col(col: dict) -> dict:
    return {k: col.get(k) for k in _ALLOWED_COL_KEYS if k in col}
