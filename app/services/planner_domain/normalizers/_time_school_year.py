"""School-year normalization helpers."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.config import QF_SCHOOL_YEAR_END_MONTH, QF_SCHOOL_YEAR_START_MONTH
from app.services.planner.value_normalizers.school_year import (
    is_school_year_column,
    normalize_school_year_values,
)

from ._time_shared import _extract_filter_values, _norm_key


def _synthesize_school_year_filter_from_time_block(
    *,
    plan: Mapping[str, Any],
    col_lookup: Mapping[str, Dict[str, Any]],
    prompt: str,
    today: Optional[date],
    school_year_start_month: int,
    school_year_end_month: int,
) -> Optional[Dict[str, Any]]:
    time_block = dict(plan.get("time") or {})
    time_column_key = _norm_key(time_block.get("time_column_key"))
    if time_column_key == "":
        return None

    col_meta = col_lookup.get(time_column_key) or {}
    if not is_school_year_column(col_meta):
        return None

    prompt_text = str(prompt or "").strip()
    if prompt_text == "":
        return None

    years = normalize_school_year_values(
        prompt_text,
        today=today,
        school_year_start_month=school_year_start_month,
        school_year_end_month=school_year_end_month,
    )
    if not years:
        return None

    if len(years) == 1:
        return {"column_key": time_column_key, "op": "eq", "value": years[0]}
    return {"column_key": time_column_key, "op": "in", "values": years}


def _normalize_school_year_filters_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str = "",
    today: Optional[date] = None,
    school_year_start_month: int = QF_SCHOOL_YEAR_START_MONTH,
    school_year_end_month: int = QF_SCHOOL_YEAR_END_MONTH,
    **_extra: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, dict)]
    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }

    has_school_year_filter = any(
        is_school_year_column(col_lookup.get(_norm_key(row.get("column_key"))) or {})
        for row in filters
    )

    if not has_school_year_filter:
        synthesized = _synthesize_school_year_filter_from_time_block(
            plan=plan,
            col_lookup=col_lookup,
            prompt=prompt,
            today=today,
            school_year_start_month=school_year_start_month,
            school_year_end_month=school_year_end_month,
        )
        if synthesized is not None:
            filters = [*filters, synthesized]

    if not filters:
        return plan, [], []

    debug_rows: List[Dict[str, Any]] = []
    normalized_filters: List[Dict[str, Any]] = []
    for row in filters:
        key = _norm_key(row.get("column_key"))
        col_meta = col_lookup.get(key) or {}
        if not is_school_year_column(col_meta):
            normalized_filters.append(row)
            continue

        raw_values = _extract_filter_values(row)
        years = normalize_school_year_values(
            raw_values,
            today=today,
            school_year_start_month=school_year_start_month,
            school_year_end_month=school_year_end_month,
        )
        debug_rows.append(
            {
                "column_key": key,
                "original": raw_values,
                "normalized": years,
            }
        )
        if not years:
            normalized_filters.append(row)
            continue

        op_norm = str(row.get("op") or "").strip().lower()
        normalized = dict(row)
        if op_norm in {"in", "not_in"}:
            normalized["values"] = years
            normalized.pop("value", None)
        elif op_norm in {"eq", "equals", "="}:
            normalized["op"] = "eq"
            if len(years) == 1:
                normalized["value"] = years[0]
                normalized.pop("values", None)
            else:
                normalized["op"] = "in"
                normalized["values"] = years
                normalized.pop("value", None)
        elif op_norm in {"ne", "!=", "not_equals"}:
            normalized["op"] = "ne"
            if len(years) == 1:
                normalized["value"] = years[0]
                normalized.pop("values", None)
            else:
                normalized["op"] = "not_in"
                normalized["values"] = years
                normalized.pop("value", None)
        else:
            if "values" in normalized:
                normalized["values"] = years
                normalized.pop("value", None)
            else:
                normalized["value"] = years[0]
        normalized_filters.append(normalized)

    plan["filters"] = normalized_filters
    return plan, [], debug_rows
