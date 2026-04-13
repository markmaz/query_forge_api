"""Entity normalizers: country, school name, and staff role filters."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.services.planner.value_normalizers.country import is_country_iso2_column, normalize_country_values
from app.services.planner_domain.column_scoring import (
    _is_staff_role_title_column_name,
    _is_technical_school_key_name,
    _prompt_explicitly_requests_school_key,
    _prompt_explicitly_requests_staff_classification,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


# ---------------------------------------------------------------------------
# Constants (copied from service.py)
# ---------------------------------------------------------------------------

_NON_WORD_RE = re.compile(r"[^a-z0-9\s]")

_STAFF_ROLE_VALUE_RE = re.compile(
    r"\b(assistant\s+principals?|principals?|teachers?|counselors?|counsellors?|coaches?|librarians?|superintendents?|nurses?|psychologists?|social\s+workers?)\b",
    re.IGNORECASE,
)

_STAFF_ROLE_CANONICAL: Dict[str, str] = {
    "assistant principal": "Assistant Principal",
    "assistant principals": "Assistant Principal",
    "principal": "Principal",
    "principals": "Principal",
    "teacher": "Teacher",
    "teachers": "Teacher",
    "counselor": "Counselor",
    "counselors": "Counselor",
    "counsellor": "Counselor",
    "counsellors": "Counselor",
    "coach": "Coach",
    "coaches": "Coach",
    "librarian": "Librarian",
    "librarians": "Librarian",
    "superintendent": "Superintendent",
    "superintendents": "Superintendent",
    "nurse": "Nurse",
    "nurses": "Nurse",
    "psychologist": "Psychologist",
    "psychologists": "Psychologist",
    "social worker": "Social Worker",
    "social workers": "Social Worker",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_text_for_match(value: str) -> str:
    text = str(value or "").strip().lower()
    text = _NON_WORD_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _district_term_positions(prompt_norm: str) -> List[int]:
    positions: List[int] = []
    for term in ("school district", "local education agency", "district", "lea"):
        start = 0
        while True:
            idx = prompt_norm.find(term, start)
            if idx < 0:
                break
            positions.append(idx)
            start = idx + len(term)
    positions.sort()
    return positions


def _appears_near_district(prompt_norm: str, value_norm: str, district_positions: Sequence[int]) -> bool:
    if prompt_norm == "" or value_norm == "":
        return False
    value_idx = prompt_norm.find(value_norm)
    if value_idx < 0:
        return False
    for pos in district_positions:
        if abs(pos - value_idx) <= 48:
            return True
    return False


def _looks_like_proper_noun_value(value: str) -> bool:
    text = str(value or "").strip()
    if text == "":
        return False
    if text.isdigit():
        return False
    return any(ch.isalpha() for ch in text)


def _extract_filter_values(filter_row: Mapping[str, Any]) -> List[str]:
    if isinstance(filter_row.get("values"), list):
        return [str(v).strip() for v in list(filter_row.get("values") or []) if str(v).strip()]
    if filter_row.get("value") is None:
        return []
    value = str(filter_row.get("value") or "").strip()
    return [value] if value else []


def _looks_like_human_school_name_value(value: Any) -> bool:
    text = str(value or "").strip()
    if text == "":
        return False
    if text.isdigit():
        return False
    if not any(ch.isalpha() for ch in text):
        return False
    if re.fullmatch(r"[A-Z0-9_\-]{2,16}", text):
        return False
    return True


def _extract_staff_role_value_from_prompt(prompt: str) -> Optional[str]:
    text = str(prompt or "").strip()
    if text == "":
        return None

    matches: List[str] = []
    for match in _STAFF_ROLE_VALUE_RE.finditer(text):
        token = " ".join(str(match.group(1) or "").strip().lower().split())
        canonical = _STAFF_ROLE_CANONICAL.get(token)
        if canonical:
            matches.append(canonical)
    if not matches:
        return None

    unique_matches = list(dict.fromkeys(matches))
    if len(unique_matches) != 1:
        return None
    return unique_matches[0]


# ---------------------------------------------------------------------------
# Public normalizers
# ---------------------------------------------------------------------------

def _normalize_country_filters_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    _prompt: str = "",
    **_extra: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
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
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }

    issues: List[Dict[str, str]] = []
    debug_rows: List[Dict[str, Any]] = []
    normalized_filters: List[Dict[str, Any]] = []
    for idx, row in enumerate(filters):
        key = _norm_key(row.get("column_key"))
        col_meta = col_lookup.get(key) or {}
        if not is_country_iso2_column(col_meta):
            normalized_filters.append(row)
            continue

        raw_values = _extract_filter_values(row)
        codes = normalize_country_values(raw_values)
        debug_rows.append(
            {
                "column_key": key,
                "original": raw_values,
                "normalized": codes,
            }
        )
        if not codes:
            original_preview = ", ".join(raw_values)[:120]
            issues.append(
                {
                    "code": "unresolved_filter_value",
                    "path": f"filters[{idx}]",
                    "message": f"Could not resolve country value '{original_preview}' to ISO2",
                }
            )
            logger.debug("country_normalizer unresolved column=%s values=%s", key, raw_values)
            continue

        op_norm = str(row.get("op") or "").strip().lower()
        normalized = dict(row)
        if op_norm in {"in", "not_in"}:
            normalized["values"] = codes
            normalized.pop("value", None)
        elif op_norm in {"eq", "equals", "="}:
            normalized["op"] = "eq"
            if len(codes) == 1:
                normalized["value"] = codes[0]
                normalized.pop("values", None)
            else:
                normalized["op"] = "in"
                normalized["values"] = codes
                normalized.pop("value", None)
        elif op_norm in {"ne", "!=", "not_equals"}:
            normalized["op"] = "ne"
            if len(codes) == 1:
                normalized["value"] = codes[0]
                normalized.pop("values", None)
            else:
                normalized["op"] = "not_in"
                normalized["values"] = codes
                normalized.pop("value", None)
        else:
            if "values" in normalized:
                normalized["values"] = codes
                normalized.pop("value", None)
            else:
                normalized["value"] = codes[0]
        normalized_filters.append(normalized)

    plan["filters"] = normalized_filters
    return plan, issues, debug_rows


def _normalize_school_name_filters_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str = "",
    **_extra: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, dict)]
    if not filters:
        return plan, [], []
    if _prompt_explicitly_requests_school_key(prompt):
        return plan, [], []

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }

    school_name_key = ""
    for row in col_lookup.values():
        col_name = str(row.get("column_name") or "").strip().lower()
        if col_name == "school_name":
            school_name_key = _norm_key(row.get("column_key"))
            break
    if school_name_key == "":
        return plan, [], []

    debug_rows: List[Dict[str, Any]] = []
    normalized_filters: List[Dict[str, Any]] = []
    for row in filters:
        key = _norm_key(row.get("column_key"))
        meta = col_lookup.get(key) or {}
        col_name = str(meta.get("column_name") or "").strip().lower()
        if not _is_technical_school_key_name(col_name):
            normalized_filters.append(row)
            continue

        raw_values = _extract_filter_values(row)
        should_rewrite = len(raw_values) > 0 and all(_looks_like_human_school_name_value(v) for v in raw_values)
        debug_item: Dict[str, Any] = {
            "column_key": key,
            "column_name": col_name,
            "values": raw_values,
            "rewritten": False,
        }
        if not should_rewrite:
            normalized_filters.append(row)
            debug_rows.append(debug_item)
            continue

        rewritten = dict(row)
        rewritten["column_key"] = school_name_key
        normalized_filters.append(rewritten)
        debug_item["rewritten"] = True
        debug_item["rewritten_to_column_key"] = school_name_key
        debug_rows.append(debug_item)

    plan["filters"] = normalized_filters
    return plan, [], debug_rows


def _normalize_staff_role_filters_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str = "",
    **_extra: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    if _prompt_explicitly_requests_staff_classification(prompt):
        return plan, [], []

    role_value = _extract_staff_role_value_from_prompt(prompt)
    if role_value is None:
        return plan, [], []

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }
    if not col_lookup:
        return plan, [], []

    role_title_candidates: List[Tuple[int, str]] = []
    for key, row in col_lookup.items():
        col_name = str(row.get("column_name") or "").strip().lower()
        if not _is_staff_role_title_column_name(col_name):
            continue
        if row.get("filterable") is False:
            continue
        # Prefer canonical role-title columns when multiple are available.
        priority = 100 if col_name == "position_title" else 90 if col_name == "classroom_position" else 80
        role_title_candidates.append((priority, key))
    if not role_title_candidates:
        return plan, [], []

    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, dict)]
    debug_rows: List[Dict[str, Any]] = []
    for row in filters:
        key = _norm_key(row.get("column_key"))
        meta = col_lookup.get(key) or {}
        col_name = str(meta.get("column_name") or "").strip().lower()
        if _is_staff_role_title_column_name(col_name):
            debug_rows.append(
                {
                    "action": "skip_existing_role_filter",
                    "column_key": key,
                    "column_name": col_name,
                    "value": row.get("value"),
                }
            )
            return plan, [], debug_rows

    role_title_candidates.sort(key=lambda item: item[0], reverse=True)
    target_key = role_title_candidates[0][1]
    appended = {"column_key": target_key, "op": "=", "value": role_value}
    filters.append(appended)
    plan["filters"] = filters
    debug_rows.append({"action": "appended_role_filter", "column_key": target_key, "value": role_value})
    return plan, [], debug_rows
