"""Shared helpers for planner-domain time normalization."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Mapping, Optional
from zoneinfo import ZoneInfo


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_generic_year_column_name(column_name: str) -> bool:
    token = str(column_name or "").strip().lower()
    if token == "":
        return False
    return token in {"year", "year_num", "calendar_year", "fiscal_year"} or token.endswith("_year")


def _is_generic_quarter_column_name(column_name: str) -> bool:
    token = str(column_name or "").strip().lower()
    if token == "":
        return False
    return token in {"quarter", "quarter_num", "fiscal_quarter", "calendar_quarter"} or token.endswith("_quarter")


def _is_generic_month_column_name(column_name: str) -> bool:
    token = str(column_name or "").strip().lower()
    if token == "":
        return False
    return token in {"month", "month_num", "month_number", "report_month", "calendar_month_num"} or token.endswith("_month")


def _extract_filter_values(filter_row: Mapping[str, Any]) -> list[str]:
    if isinstance(filter_row.get("values"), list):
        return [str(v).strip() for v in list(filter_row.get("values") or []) if str(v).strip()]
    if filter_row.get("value") is None:
        return []
    value = str(filter_row.get("value") or "").strip()
    return [value] if value else []


def _normalize_domain_time_policy(policy: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "calendar_mode": "calendar",
        "fiscal_year_start_month": None,
        "school_year_start_month": None,
        "school_year_end_month": None,
        "timezone": None,
        "default_time_concept_key": None,
        "allow_relative_ranges": True,
        "default_grain": None,
        "relative_map": {},
        "semester": {
            "labels": {
                "spring": "Spring",
                "fall": "Fall",
                "year_round": "Year Round",
            },
            "month_ranges": {
                "spring": [1, 5],
                "fall": [8, 12],
                "year_round": [6, 7],
            },
            "indicator_columns": {},
        },
    }
    if not isinstance(policy, Mapping):
        return out
    calendar_mode = _norm_key(policy.get("calendar_mode"))
    if calendar_mode in {"calendar", "fiscal", "school_year"}:
        out["calendar_mode"] = calendar_mode
    fiscal_month = _to_int(policy.get("fiscal_year_start_month"))
    if fiscal_month is not None and 1 <= fiscal_month <= 12:
        out["fiscal_year_start_month"] = fiscal_month
    school_year_start = _to_int(policy.get("school_year_start_month"))
    if school_year_start is not None and 1 <= school_year_start <= 12:
        out["school_year_start_month"] = school_year_start
    school_year_end = _to_int(policy.get("school_year_end_month"))
    if school_year_end is not None and 1 <= school_year_end <= 12:
        out["school_year_end_month"] = school_year_end
    timezone_name = str(policy.get("timezone") or "").strip()
    out["timezone"] = timezone_name or None
    default_time_key = _norm_key(policy.get("default_time_concept_key"))
    out["default_time_concept_key"] = default_time_key or None
    if "allow_relative_ranges" in policy:
        out["allow_relative_ranges"] = bool(policy.get("allow_relative_ranges"))
    default_grain = _norm_key(policy.get("default_grain"))
    if default_grain in {"day", "week", "month", "quarter", "year"}:
        out["default_grain"] = default_grain
    rel = policy.get("relative_map")
    if isinstance(rel, Mapping):
        out["relative_map"] = {str(k): str(v) for k, v in dict(rel).items()}
    semester = policy.get("semester")
    if isinstance(semester, Mapping):
        labels = semester.get("labels")
        if isinstance(labels, Mapping):
            normalized_labels = {}
            for bucket in ("spring", "fall", "year_round"):
                text = str(labels.get(bucket) or "").strip()
                if text:
                    normalized_labels[bucket] = text
            if normalized_labels:
                out["semester"]["labels"].update(normalized_labels)
        month_ranges = semester.get("month_ranges")
        if isinstance(month_ranges, Mapping):
            normalized_ranges = {}
            for bucket in ("spring", "fall", "year_round"):
                raw = month_ranges.get(bucket)
                if isinstance(raw, (list, tuple)) and len(raw) == 2:
                    start = _to_int(raw[0])
                    end = _to_int(raw[1])
                    if start is not None and end is not None and 1 <= start <= 12 and 1 <= end <= 12:
                        normalized_ranges[bucket] = [start, end]
            if normalized_ranges:
                out["semester"]["month_ranges"].update(normalized_ranges)
        indicator_columns = semester.get("indicator_columns")
        if isinstance(indicator_columns, Mapping):
            normalized_indicator_columns = {}
            for bucket, raw in dict(indicator_columns).items():
                bucket_key = str(bucket or "").strip().lower()
                column_key = str(raw or "").strip()
                if bucket_key in {"spring", "fall", "year_round"} and column_key:
                    normalized_indicator_columns[bucket_key] = column_key
            if normalized_indicator_columns:
                out["semester"]["indicator_columns"] = normalized_indicator_columns
    return out


def _policy_anchor_date(*, today: Optional[date], timezone_name: str) -> date:
    if today is not None:
        return today
    tz = str(timezone_name or "").strip()
    if tz:
        try:
            return datetime.now(ZoneInfo(tz)).date()
        except Exception:
            pass
    return date.today()


def _add_months(base: date, months: int) -> date:
    month_index = (base.month - 1) + int(months)
    year = base.year + (month_index // 12)
    month = (month_index % 12) + 1
    return date(year, month, 1)


def _fiscal_year_start_for_date(*, anchor: date, fiscal_start_month: int) -> date:
    if anchor.month >= fiscal_start_month:
        return date(anchor.year, fiscal_start_month, 1)
    return date(anchor.year - 1, fiscal_start_month, 1)
