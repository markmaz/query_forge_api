from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence


@dataclass(frozen=True)
class CanonicalTime:
    key: str
    confidence: float
    raw_text: str
    value: int | str | None = None


def normalize_time_terms(terms: Sequence[str], vertical: str) -> List[CanonicalTime]:
    vertical_key = str(vertical or "generic").strip().lower() or "generic"
    out: List[CanonicalTime] = []
    seen: set[str] = set()
    for raw in terms or []:
        text = _norm(raw)
        if text == "":
            continue
        rows = _normalize_education_time(text) if vertical_key == "education" else _normalize_generic_time(text)
        for row in rows:
            key = f"{row.key}::{row.value}"
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
    return out


def _normalize_education_time(text: str) -> List[CanonicalTime]:
    out: List[CanonicalTime] = []

    if _contains_any(text, ("current school year", "this school year")):
        out.append(CanonicalTime(key="CURRENT_SCHOOL_YEAR", confidence=0.98, raw_text=text))
        return out
    if _contains_any(text, ("this year",)):
        out.append(CanonicalTime(key="CURRENT_SCHOOL_YEAR", confidence=0.9, raw_text=text))
        return out
    if _contains_any(text, ("last school year", "previous school year")):
        out.append(CanonicalTime(key="PREVIOUS_SCHOOL_YEAR", confidence=0.97, raw_text=text))
        return out

    rolling = re.search(r"\bpast\s+(\d{1,2})\s+years?\b", text)
    if rolling:
        n = int(rolling.group(1))
        if 1 <= n <= 20:
            out.append(CanonicalTime(key="ROLLING_N_SCHOOL_YEARS", confidence=0.96, raw_text=text, value=n))
            return out

    span = re.search(r"\b(20\d{2})\s*[-/]\s*(\d{2,4})\b", text)
    if span:
        first = int(span.group(1))
        second_raw = span.group(2)
        second = int(second_raw) if len(second_raw) == 4 else int(str(first)[:2] + second_raw)
        if second >= first:
            out.append(
                CanonicalTime(
                    key="SCHOOL_YEAR_EXACT",
                    confidence=0.95,
                    raw_text=text,
                    value=f"{first}-{str(second)[-2:]}",
                )
            )
            return out

    year = re.search(r"\b(20\d{2})\b", text)
    if year:
        out.append(CanonicalTime(key="SCHOOL_YEAR_EXACT", confidence=0.88, raw_text=text, value=int(year.group(1))))
        return out

    return out


def _normalize_generic_time(text: str) -> List[CanonicalTime]:
    year = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if year:
        return [CanonicalTime(key="YEAR_EXACT", confidence=0.82, raw_text=text, value=int(year.group(1)))]
    return []


def _contains_any(text: str, needles: Sequence[str]) -> bool:
    return any(needle in text for needle in needles)


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


__all__ = ["CanonicalTime", "normalize_time_terms"]
