from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Optional, Set

_STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "to",
    "and",
    "or",
    "in",
    "on",
    "for",
    "with",
    "by",
    "field",
    "column",
    "value",
    "data",
}

_IDENTIFIER_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.strip().lower()
    text = _NON_ALNUM_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_identifier(value: object) -> List[str]:
    raw = str(value or "").strip()
    if raw == "":
        return []
    # Handle snake/kebab/space first, then camel-case chunks.
    chunks = re.split(r"[_\-\s\.]+", raw)
    out: list[str] = []
    for chunk in chunks:
        if chunk == "":
            continue
        parts = _IDENTIFIER_RE.findall(chunk)
        if parts:
            out.extend(parts)
        else:
            out.append(chunk)
    return [normalize_text(token) for token in out if normalize_text(token)]


def normalize_identifier(value: object) -> str:
    parts = split_identifier(value)
    return "_".join(parts)


def token_set(*values: object) -> Set[str]:
    out: Set[str] = set()
    for value in values:
        text = normalize_text(value)
        if text:
            for token in text.split(" "):
                if token and token not in _STOPWORDS:
                    out.add(token)
        for token in split_identifier(value):
            if token and token not in _STOPWORDS:
                out.add(token)
    return out


def token_overlap_score(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = {t for t in left if t}
    right_set = {t for t in right if t}
    if not left_set or not right_set:
        return 0.0
    overlap = len(left_set.intersection(right_set))
    denom = max(len(left_set), len(right_set), 1)
    return float(overlap) / float(denom)


def detect_type_family(value: Optional[str]) -> str:
    text = normalize_text(value)
    if not text:
        return "unknown"
    if any(token in text for token in ("date", "time", "timestamp")):
        return "date"
    if any(token in text for token in ("int", "decimal", "numeric", "number", "float", "double")):
        return "numeric"
    if any(token in text for token in ("bool", "bit")):
        return "boolean"
    if any(token in text for token in ("char", "text", "string", "varchar")):
        return "string"
    return "other"


def type_compatibility(source_type: Optional[str], candidate_type: Optional[str]) -> float:
    left = detect_type_family(source_type)
    right = detect_type_family(candidate_type)
    if left == "unknown" or right == "unknown":
        return 0.5
    if left == right:
        return 1.0
    if {left, right} <= {"numeric", "boolean"}:
        return 0.6
    return 0.0


def looks_like_field_name(value: object) -> bool:
    text = str(value or "").strip()
    if text == "":
        return False
    norm = normalize_identifier(text)
    if norm == "":
        return False
    if len(norm) > 120:
        return False
    if norm.isdigit():
        return False
    # very long sentence-like cells are usually descriptions, not field names
    return len(text.split()) <= 8
