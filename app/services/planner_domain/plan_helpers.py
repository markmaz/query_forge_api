"""Shared planning utilities — pure logic, no service dependencies."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.services.planner_domain.prompt_intents import _dedupe_text_items
from app.services.planner_domain.normalizers.entity import (
    _appears_near_district,
    _district_term_positions,
    _extract_filter_values,
    _looks_like_proper_noun_value,
    _normalize_text_for_match,
)

_DISTRICT_LEA_TERM_RE = re.compile(
    r"\b(district|school district|lea|local education agency)\b", re.IGNORECASE
)


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_text_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    items = [str(item).strip() for item in value if str(item).strip()]
    return _dedupe_text_items(items)


def _parse_constraints(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "unknown").strip().lower() or "unknown"
        text = str(item.get("text") or "").strip()
        op = str(item.get("op") or "unknown").strip().lower() or "unknown"
        value_hint_raw = item.get("value_hint")
        notes_raw = item.get("notes")
        value_hint = str(value_hint_raw).strip() if value_hint_raw not in (None, "") else None
        notes = str(notes_raw).strip() if notes_raw not in (None, "") else None
        if text == "" and value_hint is None:
            continue
        out.append(
            {
                "kind": kind,
                "text": text or str(value_hint or ""),
                "op": op,
                "value_hint": value_hint,
                "notes": notes,
            }
        )
    return out


def _dedupe_constraints(values: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in values:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "unknown").strip().lower() or "unknown"
        text = " ".join(str(item.get("text") or "").strip().split())
        op = str(item.get("op") or "unknown").strip().lower() or "unknown"
        value_hint = (
            " ".join(str(item.get("value_hint") or "").strip().split())
            if item.get("value_hint") not in (None, "")
            else ""
        )
        notes = (
            " ".join(str(item.get("notes") or "").strip().split())
            if item.get("notes") not in (None, "")
            else ""
        )
        if text == "" and value_hint == "":
            continue
        key = (kind, text.lower(), op, value_hint.lower(), notes.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "kind": kind,
                "text": text or value_hint,
                "op": op,
                "value_hint": value_hint or None,
                "notes": notes or None,
            }
        )
    return out


def _selected_domain_name(
    *, domain_candidates: Sequence[Mapping[str, Any]], selected_domain_id: int
) -> Optional[str]:
    selected = int(selected_domain_id)
    for row in domain_candidates:
        if _to_int(row.get("domain_id")) != selected:
            continue
        name = str(row.get("name") or "").strip()
        if name:
            return name
    return None


def _serialize_domain_candidates_for_debug(
    domain_candidates: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in list(domain_candidates or []):
        if not isinstance(row, Mapping):
            continue
        reasons = _dedupe_text_items(
            [str(item) for item in list(row.get("reason") or []) if str(item).strip()]
        )
        source = str(row.get("source") or "vector").strip() or "vector"
        semantic_reasons = [reason for reason in reasons if reason.startswith("semantic_")]
        semantic_recall = bool(source == "semantic_vector" or semantic_reasons)
        if source == "provided":
            recall_mode = "provided"
        elif semantic_recall:
            recall_mode = "semantic"
        else:
            recall_mode = "vector"
        out.append(
            {
                "domain_id": _to_int(row.get("domain_id")),
                "name": str(row.get("name") or "").strip() or None,
                "score": round(float(row.get("score") or 0.0), 5),
                "source": source,
                "reason": reasons,
                "semantic_recall": semantic_recall,
                "semantic_reasons": semantic_reasons,
                "recall_mode": recall_mode,
            }
        )
    return out


def _should_retry_after_validation(issues: Sequence[Mapping[str, Any]]) -> bool:
    retryable_codes = {
        "empty_plan",
        "invalid_filter_value_prompt_echo",
        "invalid_dimension_column",
        "invalid_filter_column",
        "unknown_metric_ref",
        "invalid_order_by_dimension",
        "invalid_order_by_metric",
    }
    for issue in issues:
        code = str(issue.get("code") or "").strip().lower()
        if code in retryable_codes:
            return True
    return False


def _format_validation_feedback(issues: Sequence[Mapping[str, Any]]) -> str:
    if not issues:
        return ""
    lines: List[str] = []
    for issue in issues[:8]:
        code = str(issue.get("code") or "unknown").strip()
        path = str(issue.get("path") or "").strip()
        message = str(issue.get("message") or "").strip()
        if path:
            lines.append(f"{code} at {path}: {message}")
        else:
            lines.append(f"{code}: {message}")
    return "; ".join(lines)


def _district_county_retry_hint(
    *,
    normalized_prompt: str,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
) -> Optional[str]:
    prompt = str(normalized_prompt or "").strip()
    if prompt == "" or _DISTRICT_LEA_TERM_RE.search(prompt) is None:
        return None

    prompt_norm = _normalize_text_for_match(prompt)
    district_positions = _district_term_positions(prompt_norm)
    if not district_positions:
        return None

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }
    filters = [dict(item) for item in list(plan_json.get("filters") or []) if isinstance(item, dict)]
    for row in filters:
        key = _norm_key(row.get("column_key"))
        meta = col_lookup.get(key) or {}
        column_name = str(meta.get("column_name") or key).strip().lower()
        if not (key.endswith(".name_of_county") or "county" in column_name):
            continue
        values = _extract_filter_values(row)
        if not values:
            continue
        for value in values:
            if not _looks_like_proper_noun_value(value):
                continue
            if _appears_near_district(
                prompt_norm, _normalize_text_for_match(value), district_positions
            ):
                return (
                    "You likely mapped a district name to a geographic county column. "
                    "If the user meant a district/LEA, use lea_name for the proper noun "
                    "and reserve county columns for geography."
                )
    return None
