"""Relative-time and generic year keyword normalizers."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.config import QF_SCHOOL_YEAR_END_MONTH, QF_SCHOOL_YEAR_START_MONTH
from app.services.planner.value_normalizers.school_year import current_school_year
from app.services.planner_domain.column_scoring import _has_birth_date_columns
from app.services.planner_domain.conversation_context import normalize_plan_prompt
from app.services.planner_domain.prompt_intents import (
    _extract_named_month_number,
    _prompt_has_birth_month_constraint,
)

from ._time_shared import (
    _add_months,
    _extract_filter_values,
    _fiscal_year_start_for_date,
    _is_generic_month_column_name,
    _is_generic_quarter_column_name,
    _is_generic_year_column_name,
    _norm_key,
    _normalize_domain_time_policy,
    _policy_anchor_date,
    _to_int,
)


def _canonical_relative_time_token(raw: Any) -> str:
    token = _norm_key(raw).replace("-", "_").replace(" ", "_")
    aliases = {
        "today": "today",
        "current_day": "today",
        "this_day": "today",
        "yesterday": "yesterday",
        "previous_day": "yesterday",
        "this_week": "this_week",
        "current_week": "this_week",
        "last_week": "last_week",
        "previous_week": "last_week",
        "this_month": "this_month",
        "current_month": "this_month",
        "last_month": "last_month",
        "previous_month": "last_month",
        "this_year": "this_year",
        "current_year": "this_year",
        "last_year": "last_year",
        "previous_year": "last_year",
        "this_quarter": "this_quarter",
        "current_quarter": "this_quarter",
        "last_quarter": "last_quarter",
        "previous_quarter": "last_quarter",
        "fiscal_this_quarter": "fiscal_this_quarter",
        "this_fiscal_quarter": "fiscal_this_quarter",
        "current_fiscal_quarter": "fiscal_this_quarter",
        "fiscal_last_quarter": "fiscal_last_quarter",
        "last_fiscal_quarter": "fiscal_last_quarter",
        "previous_fiscal_quarter": "fiscal_last_quarter",
    }
    return aliases.get(token, "")


def _prompt_relative_day_phrase(prompt_norm: str) -> str:
    text = str(prompt_norm or "").strip().lower()
    if re.search(r"\byesterday\b", text) is not None:
        return "yesterday"
    if re.search(r"\btoday\b", text) is not None:
        return "today"
    return ""


def _prompt_relative_week_phrase(prompt_norm: str) -> str:
    text = str(prompt_norm or "").strip().lower()
    if re.search(r"\b(last|previous)\s+week\b", text) is not None:
        return "last_week"
    if re.search(r"\b(this|current)\s+week\b", text) is not None:
        return "this_week"
    return ""


def _prompt_relative_month_phrase(prompt_norm: str) -> str:
    text = str(prompt_norm or "").strip().lower()
    if re.search(r"\b(last|previous)\s+month\b", text) is not None:
        return "last_month"
    if re.search(r"\b(this|current)\s+month\b", text) is not None:
        return "this_month"
    return ""


def _prompt_relative_year_phrase(prompt_norm: str) -> str:
    text = str(prompt_norm or "").strip().lower()
    if re.search(r"\b(last|previous)\s+year\b", text) is not None:
        return "last_year"
    if re.search(r"\b(this|current)\s+year\b", text) is not None:
        return "this_year"
    return ""


def _prompt_relative_quarter_phrase(prompt_norm: str) -> str:
    text = str(prompt_norm or "").strip().lower()
    if re.search(r"\b(last|previous)\s+fiscal\s+quarter\b", text) is not None:
        return "fiscal_last_quarter"
    if re.search(r"\b(this|current)\s+fiscal\s+quarter\b", text) is not None:
        return "fiscal_this_quarter"
    if re.search(r"\b(last|previous)\s+quarter\b", text) is not None:
        return "last_quarter"
    if re.search(r"\b(this|current)\s+quarter\b", text) is not None:
        return "this_quarter"
    return ""


def _resolve_relative_token_from_map(*, prompt_norm: str, relative_map: Mapping[str, Any]) -> str:
    text = _norm_key(prompt_norm)
    if text == "" or not isinstance(relative_map, Mapping):
        return ""

    items: List[Tuple[str, str]] = []
    for raw_key, raw_value in dict(relative_map).items():
        key = _norm_key(raw_key)
        value = _canonical_relative_time_token(raw_value)
        if key == "" or value == "":
            continue
        items.append((key, value))
    if not items:
        return ""
    items.sort(key=lambda item: len(item[0]), reverse=True)
    for key, value in items:
        if text == key:
            return value
        pattern = rf"(^|[^a-z0-9]){re.escape(key)}($|[^a-z0-9])"
        if re.search(pattern, text) is not None:
            return value
    return ""


def _resolve_relative_token_from_filters(filters: Sequence[Mapping[str, Any]]) -> str:
    for row in filters:
        if not isinstance(row, Mapping):
            continue
        value = row.get("value")
        if isinstance(value, Mapping):
            token = _canonical_relative_time_token(value.get("time_range"))
            if token != "":
                return token
            period = _norm_key(value.get("time_period"))
            if period == "quarter":
                return "this_quarter"
            if period == "month":
                return "this_month"
            if period == "year":
                return "this_year"
        token = _canonical_relative_time_token(row.get("value"))
        if token != "":
            return token
        for item in list(row.get("values") or []):
            token = _canonical_relative_time_token(item)
            if token != "":
                return token
    return ""


def _resolve_relative_token_from_time_block(time_block: Mapping[str, Any]) -> str:
    block_token = _canonical_relative_time_token(time_block.get("time_range"))
    if block_token != "":
        return block_token

    start_token = _canonical_relative_time_token(time_block.get("start_date"))
    end_token = _canonical_relative_time_token(time_block.get("end_date"))
    if start_token != "" and start_token == end_token:
        return start_token
    return ""


def _resolve_relative_time_token(
    *,
    prompt_norm: str,
    time_block: Mapping[str, Any],
    filters: Sequence[Mapping[str, Any]],
    relative_map: Mapping[str, Any],
) -> str:
    direct = _prompt_relative_day_phrase(prompt_norm)
    if direct == "":
        direct = _prompt_relative_week_phrase(prompt_norm)
    if direct == "":
        direct = _prompt_relative_quarter_phrase(prompt_norm)
    if direct == "":
        direct = _prompt_relative_month_phrase(prompt_norm)
    if direct == "":
        direct = _prompt_relative_year_phrase(prompt_norm)

    mapped = _resolve_relative_token_from_map(prompt_norm=prompt_norm, relative_map=relative_map)
    if mapped != "":
        return mapped
    if direct != "":
        return direct

    block_token = _resolve_relative_token_from_time_block(time_block)
    if block_token != "":
        return block_token

    return _resolve_relative_token_from_filters(filters)


def _relative_time_grain(relative_token: str) -> str:
    token = _canonical_relative_time_token(relative_token)
    if token in {"today", "yesterday"}:
        return "day"
    if token.endswith("_week"):
        return "week"
    if token.endswith("_quarter"):
        return "quarter"
    if token.endswith("_year"):
        return "year"
    return "month"


def _current_quarter_range(
    *,
    anchor: date,
    use_fiscal: bool,
    fiscal_start_month: Optional[int],
) -> Tuple[date, date]:
    if use_fiscal and fiscal_start_month is not None and 1 <= fiscal_start_month <= 12:
        fy_start = _fiscal_year_start_for_date(anchor=anchor, fiscal_start_month=fiscal_start_month)
        months_since_fy = (anchor.year - fy_start.year) * 12 + (anchor.month - fy_start.month)
        quarter_index = max(0, months_since_fy // 3)
        quarter_start = _add_months(fy_start, quarter_index * 3)
        quarter_end = _add_months(quarter_start, 3) - timedelta(days=1)
        return quarter_start, quarter_end

    quarter_start_month = ((anchor.month - 1) // 3) * 3 + 1
    quarter_start = date(anchor.year, quarter_start_month, 1)
    quarter_end = _add_months(quarter_start, 3) - timedelta(days=1)
    return quarter_start, quarter_end


def _last_quarter_range(
    *,
    anchor: date,
    use_fiscal: bool,
    fiscal_start_month: Optional[int],
) -> Tuple[date, date]:
    current_q_start, _ = _current_quarter_range(
        anchor=anchor,
        use_fiscal=use_fiscal,
        fiscal_start_month=fiscal_start_month,
    )
    last_q_start = _add_months(current_q_start, -3)
    last_q_end = current_q_start - timedelta(days=1)
    return last_q_start, last_q_end


def _compute_relative_range(
    *,
    token: str,
    anchor: date,
    policy: Mapping[str, Any],
) -> Tuple[Optional[date], Optional[date], str]:
    canonical_token = _canonical_relative_time_token(token)
    if canonical_token == "":
        return None, None, ""

    if canonical_token == "today":
        return anchor, anchor, "today"
    if canonical_token == "yesterday":
        yesterday = anchor - timedelta(days=1)
        return yesterday, yesterday, "yesterday"
    if canonical_token in {"this_week", "last_week"}:
        week_start = _norm_key(policy.get("week_start"))
        start_offset = (anchor.weekday() + 1) % 7 if week_start == "sunday" else anchor.weekday()
        this_week_start = anchor - timedelta(days=start_offset)
        if canonical_token == "this_week":
            return this_week_start, anchor, "this week"
        last_week_start = this_week_start - timedelta(days=7)
        last_week_end = this_week_start - timedelta(days=1)
        return last_week_start, last_week_end, "last week"

    if canonical_token == "last_month":
        this_month_start = date(anchor.year, anchor.month, 1)
        end_date = this_month_start - timedelta(days=1)
        start_date = date(end_date.year, end_date.month, 1)
        return start_date, end_date, "last month"
    if canonical_token == "this_month":
        start_date = date(anchor.year, anchor.month, 1)
        return start_date, anchor, "this month"

    calendar_mode = _norm_key(policy.get("calendar_mode"))
    fiscal_start = _to_int(policy.get("fiscal_year_start_month"))
    use_fiscal_quarter = canonical_token in {"fiscal_this_quarter", "fiscal_last_quarter"} or (
        canonical_token in {"this_quarter", "last_quarter"}
        and calendar_mode == "fiscal"
        and fiscal_start is not None
        and 1 <= fiscal_start <= 12
    )

    if canonical_token in {"this_quarter", "fiscal_this_quarter"}:
        start_date, quarter_end = _current_quarter_range(anchor=anchor, use_fiscal=use_fiscal_quarter, fiscal_start_month=fiscal_start)
        del quarter_end
        return start_date, anchor, "this quarter"
    if canonical_token in {"last_quarter", "fiscal_last_quarter"}:
        start_date, end_date = _last_quarter_range(anchor=anchor, use_fiscal=use_fiscal_quarter, fiscal_start_month=fiscal_start)
        return start_date, end_date, "last quarter"

    use_fiscal_year = calendar_mode == "fiscal" and fiscal_start is not None and 1 <= fiscal_start <= 12
    if canonical_token == "this_year":
        if use_fiscal_year:
            start_date = _fiscal_year_start_for_date(anchor=anchor, fiscal_start_month=int(fiscal_start))
            return start_date, anchor, "this year"
        return date(anchor.year, 1, 1), anchor, "this year"
    if canonical_token == "last_year":
        if use_fiscal_year:
            fy_start = _fiscal_year_start_for_date(anchor=anchor, fiscal_start_month=int(fiscal_start))
            start_date = _add_months(fy_start, -12)
            end_date = fy_start - timedelta(days=1)
            return start_date, end_date, "last year"
        return date(anchor.year - 1, 1, 1), date(anchor.year - 1, 12, 31), "last year"

    return None, None, ""


def _resolve_named_month_range(
    *,
    prompt_norm: str,
    anchor: date,
    policy: Mapping[str, Any],
) -> Optional[Tuple[date, date, str, str, int, bool]]:
    text = str(prompt_norm or "").strip().lower()
    if text == "":
        return None

    match = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b(?:\s+(\d{4}))?",
        text,
    )
    if match is None:
        return None

    month_name = str(match.group(1) or "").lower()
    month_num = _extract_named_month_number(month_name)
    if month_num is None:
        return None
    explicit_year = match.group(2)
    school_year_anchored = False
    if explicit_year:
        year = int(explicit_year)
    elif _norm_key(policy.get("calendar_mode")) == "school_year":
        school_year_start_month = _to_int(policy.get("school_year_start_month")) or QF_SCHOOL_YEAR_START_MONTH
        school_year_end_month = _to_int(policy.get("school_year_end_month")) or QF_SCHOOL_YEAR_END_MONTH
        current_sy = current_school_year(
            today=anchor,
            school_year_start_month=school_year_start_month,
            school_year_end_month=school_year_end_month,
        )
        year = current_sy - 1 if month_num >= school_year_start_month else current_sy
        school_year_anchored = True
    else:
        year = anchor.year
    start_date = date(year, month_num, 1)
    end_date = _add_months(start_date, 1) - timedelta(days=1)
    return start_date, end_date, month_name, month_name, year, school_year_anchored


def _best_time_column_key_for_relative_range(*, capabilities: Mapping[str, Any]) -> str:
    best_key = ""
    best_score = -1
    rows: List[Tuple[int, Mapping[str, Any]]] = []
    for row in list(capabilities.get("time_columns") or []):
        if isinstance(row, Mapping):
            rows.append((3, row))
    for row in list(capabilities.get("filter_columns") or []):
        if isinstance(row, Mapping):
            rows.append((2, row))
    for row in list(capabilities.get("dimensions") or []):
        if isinstance(row, Mapping):
            rows.append((1, row))

    for source_weight, row in rows:
        key = _norm_key(row.get("column_key"))
        if key == "":
            continue
        column_name = str(row.get("column_name") or "").strip().lower()
        data_type = str(row.get("data_type") or "").strip().lower()
        date_like = (
            column_name in {"date_key", "date", "order_date", "transaction_date", "sales_date", "invoice_date"}
            or "date" in column_name
            or "time" in column_name
            or column_name.endswith("_at")
            or data_type in {"date", "datetime", "timestamp"}
        )
        if not date_like:
            continue
        score = source_weight * 100
        if column_name in {"date_key", "date", "order_date", "transaction_date", "sales_date", "invoice_date"}:
            score += 200
        if "date" in column_name:
            score += 80
        if "time" in column_name or column_name.endswith("_at"):
            score += 40
        if data_type in {"date", "datetime", "timestamp"}:
            score += 50
        if score > best_score:
            best_score = score
            best_key = key
    return best_key


def _resolve_time_column_key_for_relative_range(
    *,
    explicit_time_column_key: Any,
    policy_default_time_column_key: Any,
    capabilities: Mapping[str, Any],
) -> str:
    valid_keys = {
        _norm_key(row.get("column_key"))
        for row in (
            list(capabilities.get("time_columns") or [])
            + list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
        )
        if isinstance(row, Mapping) and _norm_key(row.get("column_key"))
    }

    explicit_key = _norm_key(explicit_time_column_key)
    if explicit_key and explicit_key in valid_keys:
        return explicit_key

    policy_key = _norm_key(policy_default_time_column_key)
    if policy_key and policy_key in valid_keys:
        return policy_key

    return _best_time_column_key_for_relative_range(capabilities=capabilities)


def _is_time_period_filter_value(filter_row: Mapping[str, Any]) -> bool:
    value = filter_row.get("value")
    if isinstance(value, Mapping):
        if _norm_key(value.get("type")) == "time_period":
            return True
        if _canonical_relative_time_token(value.get("time_range")) != "":
            return True
    for item in list(filter_row.get("values") or []):
        if _canonical_relative_time_token(item) != "":
            return True
    return False


def _normalize_relative_time_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str = "",
    domain_time_policy: Optional[Mapping[str, Any]] = None,
    today: Optional[date] = None,
    **_extra: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    time_block = dict(plan.get("time") or {}) if isinstance(plan.get("time"), dict) else {}
    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, Mapping)]
    prompt_norm = normalize_plan_prompt(prompt)
    policy = _normalize_domain_time_policy(domain_time_policy)
    if not bool(policy.get("allow_relative_ranges", True)):
        return plan, [], []
    if _prompt_has_birth_month_constraint(prompt_norm) and _has_birth_date_columns(
        list(capabilities.get("filter_columns") or [])
        + list(capabilities.get("dimensions") or [])
        + list(capabilities.get("time_columns") or [])
    ):
        return plan, [], [{"action": "relative_time_skipped", "reason": "birth_month_prompt_uses_date_part"}]

    relative_token = _resolve_relative_time_token(
        prompt_norm=prompt_norm,
        time_block=time_block,
        filters=filters,
        relative_map=policy.get("relative_map") if isinstance(policy.get("relative_map"), Mapping) else {},
    )
    anchor = _policy_anchor_date(today=today, timezone_name=str(policy.get("timezone") or ""))
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    relative_phrase = ""
    normalization_action = "normalized_relative_time"
    debug_payload: Dict[str, Any] = {}

    if relative_token != "":
        start_date, end_date, relative_phrase = _compute_relative_range(
            token=relative_token,
            anchor=anchor,
            policy=policy,
        )
        debug_payload["relative_token"] = relative_token
    else:
        named_month = _resolve_named_month_range(prompt_norm=prompt_norm, anchor=anchor, policy=policy)
        if named_month is None:
            return plan, [], []
        start_date, end_date, relative_phrase, matched_month, matched_year, school_year_anchored = named_month
        normalization_action = "normalized_named_month_time"
        debug_payload.update(
            {
                "matched_month": matched_month,
                "matched_year": matched_year,
                "school_year_anchored": school_year_anchored,
            }
        )

    if start_date is None or end_date is None:
        return plan, [], []

    time_column_key = _resolve_time_column_key_for_relative_range(
        explicit_time_column_key=time_block.get("time_column_key"),
        policy_default_time_column_key=policy.get("default_time_concept_key"),
        capabilities=capabilities,
    )
    if time_column_key == "":
        return plan, [], [{"action": "relative_time_skipped", "reason": "no_time_column_available"}]

    time_block["time_range"] = "custom"
    time_block["start_date"] = start_date.isoformat()
    time_block["end_date"] = end_date.isoformat()
    time_block["time_column_key"] = time_column_key
    if _norm_key(time_block.get("time_grain")) == "":
        default_grain = _norm_key(policy.get("default_grain"))
        if default_grain in {"day", "week", "month", "quarter", "year"}:
            time_block["time_grain"] = default_grain
        else:
            time_block["time_grain"] = _relative_time_grain(relative_token)
    plan["time"] = time_block

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, Mapping) and _norm_key(row.get("column_key"))
    }
    dropped_keys: List[str] = []
    normalized_filters: List[Dict[str, Any]] = []
    for row in filters:
        key = _norm_key(row.get("column_key"))
        column_name = str((col_lookup.get(key) or {}).get("column_name") or "").strip().lower()
        if _is_time_period_filter_value(row):
            dropped_keys.append(key or "(time_period)")
            continue
        if (
            _is_generic_month_column_name(column_name)
            or _is_generic_year_column_name(column_name)
            or _is_generic_quarter_column_name(column_name)
        ):
            dropped_keys.append(key)
            continue
        normalized_filters.append(row)
    plan["filters"] = normalized_filters

    debug_rows: List[Dict[str, Any]] = [
        {
            "action": normalization_action,
            "relative_phrase": relative_phrase,
            "policy_calendar_mode": policy.get("calendar_mode"),
            "policy_timezone": policy.get("timezone"),
            "time_column_key": time_column_key,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "dropped_time_filters": dropped_keys,
            **debug_payload,
        }
    ]
    return plan, [], debug_rows


def _normalize_year_keyword_filters_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str = "",
    today: Optional[date] = None,
    **_extra: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    del prompt
    plan = dict(plan_json or {})
    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, dict)]
    if not filters:
        return plan, [], []

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, Mapping) and _norm_key(row.get("column_key"))
    }
    if not col_lookup:
        return plan, [], []

    year_now = int((today or date.today()).year)
    debug_rows: List[Dict[str, Any]] = []
    normalized_filters: List[Dict[str, Any]] = []
    for row in filters:
        key = _norm_key(row.get("column_key"))
        col_name = str((col_lookup.get(key) or {}).get("column_name") or "").strip().lower()
        if not _is_generic_year_column_name(col_name):
            normalized_filters.append(row)
            continue
        if col_name == "school_year":
            normalized_filters.append(row)
            continue

        values = _extract_filter_values(row)
        if not values:
            normalized_filters.append(row)
            continue

        normalized_vals: List[int] = []
        changed = False
        for raw in values:
            token = _norm_key(raw)
            if token in {"current_year", "current year", "this_year", "this year"}:
                normalized_vals.append(year_now)
                changed = True
                continue
            if token in {"last_year", "last year", "previous_year", "previous year"}:
                normalized_vals.append(year_now - 1)
                changed = True
                continue
            if token.isdigit() and len(token) == 4:
                normalized_vals.append(int(token))
                changed = True
                continue
            normalized_vals = []
            changed = False
            break

        if not changed or not normalized_vals:
            normalized_filters.append(row)
            continue

        out_row = dict(row)
        op_norm = _norm_key(out_row.get("op"))
        if op_norm in {"in", "not_in"} or len(normalized_vals) > 1:
            out_row["op"] = "in" if op_norm in {"in", "eq", "equals", "="} else "not_in"
            out_row["values"] = normalized_vals
            out_row.pop("value", None)
        else:
            out_row["op"] = "eq" if op_norm in {"eq", "equals", "="} else out_row.get("op") or "eq"
            out_row["value"] = normalized_vals[0]
            out_row.pop("values", None)
        normalized_filters.append(out_row)
        debug_rows.append(
            {
                "action": "normalized_year_keyword",
                "column_key": key,
                "column_name": col_name,
                "original_values": values,
                "normalized_values": normalized_vals,
            }
        )

    plan["filters"] = normalized_filters
    return plan, [], debug_rows
