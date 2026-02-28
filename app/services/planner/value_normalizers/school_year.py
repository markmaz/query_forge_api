from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_YEAR_SPAN_RE = re.compile(r"\b(20\d{2})\s*[-/]\s*(\d{2,4})\b")

_CURRENT_TOKENS = (
    "current school year",
    "this school year",
    "current year",
    "this year",
)
_PREVIOUS_TOKENS = (
    "last school year",
    "previous school year",
    "prior school year",
)
_NEXT_TOKENS = (
    "next school year",
)


def is_school_year_column(col_meta: Dict[str, Any]) -> bool:
    semantic_type = str(col_meta.get("semantic_type") or "").strip().lower()
    if "school_year" in semantic_type:
        return True

    column_name = str(col_meta.get("column_name") or "").strip().lower()
    if "school_year" in column_name:
        return True
    return column_name in {"schoolyear", "academic_year", "school_year_id", "school_year_key"}


def normalize_school_year_values(
    value_or_values: Any,
    *,
    today: Optional[date] = None,
    school_year_start_month: int = 8,
    school_year_end_month: int = 7,
) -> List[int]:
    values = _as_values(value_or_values)
    if not values:
        return []

    current_sy = current_school_year(
        today=today,
        school_year_start_month=school_year_start_month,
        school_year_end_month=school_year_end_month,
    )
    out: List[int] = []
    seen: set[int] = set()
    for raw in values:
        normalized = _normalize_single_school_year_value(raw, current_school_year_value=current_sy)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def current_school_year(
    *,
    today: Optional[date] = None,
    school_year_start_month: int = 8,
    school_year_end_month: int = 7,
) -> int:
    anchor = today or date.today()
    start_month = _normalize_month(school_year_start_month, default=8)
    # End month is externally configurable for clarity and future rules;
    # the year rollover is anchored on the start month.
    _normalize_month(school_year_end_month, default=((start_month + 10) % 12) + 1)
    return int(anchor.year + 1) if int(anchor.month) >= int(start_month) else int(anchor.year)


def _normalize_single_school_year_value(raw_value: Any, *, current_school_year_value: int) -> Optional[int]:
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value if 1900 <= raw_value <= 2200 else None
    if isinstance(raw_value, float):
        year = int(raw_value)
        return year if float(raw_value).is_integer() and 1900 <= year <= 2200 else None

    text = str(raw_value or "").strip()
    if text == "":
        return None
    token = text.lower()

    if any(phrase in token for phrase in _CURRENT_TOKENS):
        return current_school_year_value
    if any(phrase in token for phrase in _PREVIOUS_TOKENS):
        return current_school_year_value - 1
    if any(phrase in token for phrase in _NEXT_TOKENS):
        return current_school_year_value + 1

    span_match = _YEAR_SPAN_RE.search(token)
    if span_match:
        first = int(span_match.group(1))
        second_raw = str(span_match.group(2) or "").strip()
        if len(second_raw) == 2:
            second = int(str(first)[:2] + second_raw)
        else:
            second = int(second_raw)
        if second >= first:
            return second

    year_match = _YEAR_RE.search(token)
    if year_match:
        return int(year_match.group(1))
    return None


def _as_values(value_or_values: Any) -> List[Any]:
    if value_or_values is None:
        return []
    if isinstance(value_or_values, list):
        return list(value_or_values)
    return [value_or_values]


def _normalize_month(value: Any, *, default: int) -> int:
    try:
        month = int(value)
    except Exception:
        return int(default)
    if month < 1 or month > 12:
        return int(default)
    return month


__all__ = [
    "current_school_year",
    "is_school_year_column",
    "normalize_school_year_values",
]
