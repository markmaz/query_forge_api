from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple


def is_semester_column(col_meta: Dict[str, Any]) -> bool:
    semantic_type = str(col_meta.get("semantic_type") or "").strip().lower()
    column_name = str(col_meta.get("column_name") or "").strip().lower()

    if "school_year" in semantic_type or "school_year" in column_name:
        return False
    if "semester" in semantic_type or "term" in semantic_type:
        return True
    if "semester" in column_name or column_name in {"term", "term_name", "semester_name"}:
        return True
    return False


def normalize_semester_values(
    value_or_values: Any,
    *,
    today: Optional[date] = None,
    spring_label: str = "Spring",
    fall_label: str = "Fall",
    year_round_label: str = "Year Round",
    spring_month_range: Tuple[int, int] = (1, 5),
    fall_month_range: Tuple[int, int] = (8, 12),
    year_round_month_range: Tuple[int, int] = (6, 7),
) -> List[str]:
    values = _as_values(value_or_values)
    if not values:
        return []

    current_label = current_semester_label(
        today=today,
        spring_label=spring_label,
        fall_label=fall_label,
        year_round_label=year_round_label,
        spring_month_range=spring_month_range,
        fall_month_range=fall_month_range,
        year_round_month_range=year_round_month_range,
    )
    labels = [spring_label, year_round_label, fall_label]
    out: List[str] = []
    seen: set[str] = set()
    for raw in values:
        normalized = _normalize_single_semester_value(raw, current_label=current_label, labels=labels)
        if normalized is None:
            continue
        key = normalized.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out


def current_semester_label(
    *,
    today: Optional[date] = None,
    spring_label: str = "Spring",
    fall_label: str = "Fall",
    year_round_label: str = "Year Round",
    spring_month_range: Tuple[int, int] = (1, 5),
    fall_month_range: Tuple[int, int] = (8, 12),
    year_round_month_range: Tuple[int, int] = (6, 7),
) -> str:
    anchor = today or date.today()
    month = int(anchor.month)

    if _month_in_range(month, spring_month_range):
        return spring_label
    if _month_in_range(month, fall_month_range):
        return fall_label
    if _month_in_range(month, year_round_month_range):
        return year_round_label
    return spring_label


def _normalize_single_semester_value(
    raw_value: Any,
    *,
    current_label: str,
    labels: List[str],
) -> Optional[str]:
    if raw_value is None:
        return None
    token = str(raw_value or "").strip().lower()
    if token == "":
        return None

    spring_label, year_round_label, fall_label = labels

    if _contains_any(token, ("current semester", "this semester", "current term", "this term")):
        return current_label
    if _contains_any(token, ("last semester", "previous semester", "last term", "previous term", "prior semester")):
        idx = labels.index(current_label) if current_label in labels else 0
        return labels[(idx - 1) % len(labels)]
    if _contains_any(token, ("next semester", "next term")):
        idx = labels.index(current_label) if current_label in labels else 0
        return labels[(idx + 1) % len(labels)]

    if _contains_any(token, ("spring semester", "spring term", "spring", "sprint semester", "sprint term", "sprint")):
        return spring_label
    if _contains_any(token, ("fall semester", "fall term", "fall", "autumn")):
        return fall_label
    if _contains_any(token, ("year round", "year-round", "yearround")):
        return year_round_label

    if token == spring_label.strip().lower():
        return spring_label
    if token == fall_label.strip().lower():
        return fall_label
    if token == year_round_label.strip().lower():
        return year_round_label
    return None


def _month_in_range(month: int, month_range: Tuple[int, int]) -> bool:
    start = _normalize_month(month_range[0], default=1)
    end = _normalize_month(month_range[1], default=start)
    if start <= end:
        return start <= month <= end
    return month >= start or month <= end


def _normalize_month(value: Any, *, default: int) -> int:
    try:
        out = int(value)
    except Exception:
        return int(default)
    if out < 1 or out > 12:
        return int(default)
    return out


def _as_values(value_or_values: Any) -> List[Any]:
    if value_or_values is None:
        return []
    if isinstance(value_or_values, list):
        return list(value_or_values)
    return [value_or_values]


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


__all__ = [
    "current_semester_label",
    "is_semester_column",
    "normalize_semester_values",
]
