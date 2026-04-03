"""Semester normalization helpers."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.config import (
    QF_SEMESTER_FALL_END_MONTH,
    QF_SEMESTER_FALL_LABEL,
    QF_SEMESTER_FALL_START_MONTH,
    QF_SEMESTER_SPRING_END_MONTH,
    QF_SEMESTER_SPRING_LABEL,
    QF_SEMESTER_SPRING_START_MONTH,
    QF_SEMESTER_YEAR_ROUND_END_MONTH,
    QF_SEMESTER_YEAR_ROUND_LABEL,
    QF_SEMESTER_YEAR_ROUND_START_MONTH,
)
from app.services.planner.value_normalizers.semester import is_semester_column, normalize_semester_values

from ._time_shared import _extract_filter_values, _norm_key, _normalize_domain_time_policy

_SEMESTER_BUCKET_CONCEPT_KEYS: Dict[str, set[str]] = {
    "spring": {
        "SEMESTER_SPRING_FLAG",
        "IS_SPRING",
        "IS_SPRING_BLOCK",
    },
    "fall": {
        "SEMESTER_FALL_FLAG",
        "IS_FALL",
        "IS_FALL_BLOCK",
    },
    "year_round": {
        "SEMESTER_YEAR_ROUND_FLAG",
        "IS_YEAR_ROUND",
        "IS_YEAR_ROUND_BLOCK",
    },
}


def _semester_bucket_from_text(value: Any) -> str:
    raw = str(value or "").strip()
    if raw == "":
        return ""
    upper = raw.upper().replace("-", "_").replace(" ", "_")
    for bucket, concept_keys in _SEMESTER_BUCKET_CONCEPT_KEYS.items():
        if upper in concept_keys:
            return bucket

    token = raw.lower()
    if token == "":
        return ""
    normalized = token.replace("-", "_").replace(" ", "_")
    if any(marker in normalized for marker in ("year_round", "yearround", "yr_round", "yrround")):
        return "year_round"
    if "spring" in normalized or "sping" in normalized:
        return "spring"
    if "fall" in normalized or "autumn" in normalized:
        return "fall"
    return ""


def _infer_semester_indicator_columns_from_capabilities(
    *,
    capabilities: Mapping[str, Any],
) -> Dict[str, str]:
    rows = list(capabilities.get("filter_columns") or []) + list(capabilities.get("dimensions") or []) + list(
        capabilities.get("time_columns") or []
    )
    best: Dict[str, Tuple[float, str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("filterable") is False:
            continue
        column_key = _norm_key(row.get("column_key"))
        column_name = str(row.get("column_name") or "").strip().lower()
        if column_key == "" or column_name == "":
            continue

        bucket = _semester_bucket_from_text(column_name)
        if bucket == "":
            continue

        score = 0.0
        if column_name.startswith("is_"):
            score += 3.0
        if "block" in column_name:
            score += 1.5
        if "semester" in column_name or "term" in column_name:
            score += 1.0
        semantic_type = str(row.get("semantic_type") or "").strip().lower()
        if semantic_type in {"flag", "boolean"}:
            score += 1.0
        data_type = str(row.get("data_type") or "").strip().lower()
        if any(token in data_type for token in ("bool", "bit", "tinyint")):
            score += 0.5

        current = best.get(bucket)
        if current is None or score > current[0]:
            best[bucket] = (score, column_key)
    return {bucket: value for bucket, (_score, value) in best.items() if value}


def _normalize_semester_filters_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str = "",
    today: Optional[date] = None,
    semester_indicator_columns: Optional[Mapping[str, str]] = None,
    domain_time_policy: Optional[Mapping[str, Any]] = None,
    spring_label: str = QF_SEMESTER_SPRING_LABEL,
    fall_label: str = QF_SEMESTER_FALL_LABEL,
    year_round_label: str = QF_SEMESTER_YEAR_ROUND_LABEL,
    spring_month_range: Tuple[int, int] = (QF_SEMESTER_SPRING_START_MONTH, QF_SEMESTER_SPRING_END_MONTH),
    fall_month_range: Tuple[int, int] = (QF_SEMESTER_FALL_START_MONTH, QF_SEMESTER_FALL_END_MONTH),
    year_round_month_range: Tuple[int, int] = (QF_SEMESTER_YEAR_ROUND_START_MONTH, QF_SEMESTER_YEAR_ROUND_END_MONTH),
    **_extra: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    del prompt
    plan = dict(plan_json or {})
    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, dict)]
    if not filters:
        return plan, [], []
    time_policy = _normalize_domain_time_policy(domain_time_policy)
    semester_policy = dict(time_policy.get("semester") or {})
    policy_labels = dict(semester_policy.get("labels") or {})
    spring_label = str(policy_labels.get("spring") or spring_label)
    fall_label = str(policy_labels.get("fall") or fall_label)
    year_round_label = str(policy_labels.get("year_round") or year_round_label)
    policy_month_ranges = dict(semester_policy.get("month_ranges") or {})
    spring_month_range = tuple(policy_month_ranges.get("spring") or spring_month_range)
    fall_month_range = tuple(policy_month_ranges.get("fall") or fall_month_range)
    year_round_month_range = tuple(policy_month_ranges.get("year_round") or year_round_month_range)

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }

    debug_rows: List[Dict[str, Any]] = []
    indicator_lookup = {
        str(bucket or "").strip().lower(): _norm_key(column_key)
        for bucket, column_key in dict(semester_indicator_columns or {}).items()
        if str(bucket or "").strip() and _norm_key(column_key)
    }
    policy_indicator_lookup = {
        str(bucket or "").strip().lower(): _norm_key(column_key)
        for bucket, column_key in dict(semester_policy.get("indicator_columns") or {}).items()
        if str(bucket or "").strip() and _norm_key(column_key)
    }
    if policy_indicator_lookup:
        indicator_lookup.update(policy_indicator_lookup)
    if not indicator_lookup:
        indicator_lookup = _infer_semester_indicator_columns_from_capabilities(capabilities=capabilities)

    normalized_filters: List[Dict[str, Any]] = []
    for row in filters:
        key = _norm_key(row.get("column_key"))
        col_meta = col_lookup.get(key) or {}
        if not is_semester_column(col_meta):
            normalized_filters.append(row)
            continue

        raw_values = _extract_filter_values(row)
        terms = normalize_semester_values(
            raw_values,
            today=today,
            spring_label=spring_label,
            fall_label=fall_label,
            year_round_label=year_round_label,
            spring_month_range=spring_month_range,
            fall_month_range=fall_month_range,
            year_round_month_range=year_round_month_range,
        )
        debug_rows.append(
            {
                "column_key": key,
                "original": raw_values,
                "normalized": terms,
                "rewritten_to_indicator": False,
            }
        )
        if not terms:
            normalized_filters.append(row)
            continue

        op_norm = str(row.get("op") or "").strip().lower()
        normalized = dict(row)
        if len(terms) == 1:
            bucket = _semester_bucket_from_text(terms[0])
            indicator_key = indicator_lookup.get(bucket or "")
            if indicator_key and op_norm in {"in", "not_in", "eq", "equals", "=", "ne", "!=", "not_equals"}:
                normalized["column_key"] = indicator_key
                if op_norm in {"not_in", "ne", "!=", "not_equals"}:
                    normalized["op"] = "ne"
                else:
                    normalized["op"] = "eq"
                normalized["value"] = True
                normalized.pop("values", None)
                debug_rows[-1]["rewritten_to_indicator"] = True
                debug_rows[-1]["indicator_column_key"] = indicator_key
                debug_rows[-1]["indicator_bucket"] = bucket
                normalized_filters.append(normalized)
                continue

        if op_norm in {"in", "not_in"}:
            normalized["values"] = terms
            normalized.pop("value", None)
        elif op_norm in {"eq", "equals", "="}:
            normalized["op"] = "eq"
            if len(terms) == 1:
                normalized["value"] = terms[0]
                normalized.pop("values", None)
            else:
                normalized["op"] = "in"
                normalized["values"] = terms
                normalized.pop("value", None)
        elif op_norm in {"ne", "!=", "not_equals"}:
            normalized["op"] = "ne"
            if len(terms) == 1:
                normalized["value"] = terms[0]
                normalized.pop("values", None)
            else:
                normalized["op"] = "not_in"
                normalized["values"] = terms
                normalized.pop("value", None)
        else:
            if "values" in normalized:
                normalized["values"] = terms
                normalized.pop("value", None)
            else:
                normalized["value"] = terms[0]
        normalized_filters.append(normalized)

    plan["filters"] = normalized_filters
    return plan, [], debug_rows
