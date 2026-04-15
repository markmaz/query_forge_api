"""Metric normalizers: ADM defaults and top/bottom ranking filters."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Tuple

from app.services.planner_domain.conversation_context import normalize_plan_prompt
from app.services.planner_domain.prompt_intents import _prompt_has_adm_intent

# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


# ---------------------------------------------------------------------------
# Constants (copied from service.py)
# ---------------------------------------------------------------------------

_TOP_BOTTOM_LIMIT_RE = re.compile(r"\b(?P<kind>top|bottom)\s+(?P<limit>\d{1,4})\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _prompt_mentions_primary_school(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    return any(
        token in text
        for token in (
            "primary school",
            "primary-school",
            "is primary school",
            "primary flag",
        )
    )


def _prompt_mentions_grade_level_constraint(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    return any(
        token in text
        for token in (
            "grade level",
            "grades",
            "grade ",
            "pre-k",
            "prek",
            "prekindergarten",
            "p3",
            "p4",
        )
    )


def _score_metric_for_prompt(*, prompt_norm: str, metric_key: str, metric_label: Any) -> int:
    key = _norm_key(metric_key)
    label = _norm_key(metric_label)
    score = 0
    if "sales" in prompt_norm:
        if "sales_revenue" in key:
            score += 120
        if "sales" in key:
            score += 50
        if "revenue" in key:
            score += 60
    if "revenue" in prompt_norm and "revenue" in key:
        score += 60
    if "quota" in prompt_norm and "quota" in key:
        score += 60
    if "profit" in prompt_norm and "profit" in key:
        score += 60
    if "count" in prompt_norm and "count" in key:
        score += 40

    prompt_tokens = {tok for tok in re.split(r"[^a-z0-9]+", prompt_norm) if tok}
    key_tokens = {tok for tok in re.split(r"[^a-z0-9]+", key) if tok}
    label_tokens = {tok for tok in re.split(r"[^a-z0-9]+", label) if tok}
    overlap = len(prompt_tokens & (key_tokens | label_tokens))
    score += overlap * 5

    # If no signal is available, still allow deterministic fallback to first metric.
    if score == 0:
        score = 1
    return score


def _pick_metric_ref_for_top_bottom(*, prompt_norm: str, capabilities: Mapping[str, Any]) -> str:
    domain_metrics = [dict(row) for row in list(capabilities.get("domain_metrics") or []) if isinstance(row, Mapping)]
    user_metrics = [dict(row) for row in list(capabilities.get("user_metrics") or []) if isinstance(row, Mapping)]
    overlay_metrics = [dict(row) for row in list(capabilities.get("overlay_metrics") or []) if isinstance(row, Mapping)]

    ranked: List[Tuple[int, str]] = []
    for row in domain_metrics:
        metric_key = _norm_key(row.get("metric_key"))
        if metric_key == "":
            continue
        metric_ref = f"domain_metric:{metric_key}"
        score = _score_metric_for_prompt(prompt_norm=prompt_norm, metric_key=metric_key, metric_label=row.get("label"))
        ranked.append((score, metric_ref))
    for row in user_metrics:
        metric_id = _norm_key(row.get("metric_id") or row.get("id"))
        if metric_id == "":
            continue
        metric_ref = f"user_metric:{metric_id}"
        score = _score_metric_for_prompt(prompt_norm=prompt_norm, metric_key=metric_id, metric_label=row.get("label"))
        ranked.append((score, metric_ref))
    for row in overlay_metrics:
        overlay_key = _norm_key(row.get("overlay_key"))
        if overlay_key == "":
            continue
        metric_ref = f"overlay:{overlay_key}"
        score = _score_metric_for_prompt(prompt_norm=prompt_norm, metric_key=overlay_key, metric_label=row.get("label"))
        ranked.append((score, metric_ref))

    if not ranked:
        return ""
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


# ---------------------------------------------------------------------------
# Public normalizers
# ---------------------------------------------------------------------------

def _normalize_adm_default_filters_in_plan(
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
    if not _prompt_has_adm_intent(prompt):
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

    has_person_name_filter = False
    for row in filters:
        key = _norm_key(row.get("column_key"))
        col_name = str((col_lookup.get(key) or {}).get("column_name") or "").strip().lower()
        if col_name in {"first_name", "last_name"}:
            has_person_name_filter = True
            break
    if not has_person_name_filter:
        return plan, [], []

    preserve_primary_filter = _prompt_mentions_primary_school(prompt)
    preserve_grade_level_filter = _prompt_mentions_grade_level_constraint(prompt)
    debug_rows: List[Dict[str, Any]] = []
    normalized_filters: List[Dict[str, Any]] = []

    for row in filters:
        key = _norm_key(row.get("column_key"))
        col_name = str((col_lookup.get(key) or {}).get("column_name") or "").strip().lower()
        if col_name == "is_primary_school" and not preserve_primary_filter:
            debug_rows.append(
                {
                    "action": "dropped_default_filter",
                    "column_key": key,
                    "column_name": col_name,
                    "reason": "person_specific_adm_prompt",
                }
            )
            continue
        if col_name == "grade_level_adm" and not preserve_grade_level_filter:
            debug_rows.append(
                {
                    "action": "dropped_default_filter",
                    "column_key": key,
                    "column_name": col_name,
                    "reason": "person_specific_adm_prompt",
                }
            )
            continue
        normalized_filters.append(row)

    plan["filters"] = normalized_filters
    return plan, [], debug_rows


def _normalize_top_bottom_ranking_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str = "",
    **_extra: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    prompt_norm = normalize_plan_prompt(prompt).lower()
    match = _TOP_BOTTOM_LIMIT_RE.search(prompt_norm)
    if match is None:
        return plan, [], []

    ranking_kind = str(match.group("kind") or "").strip().lower()
    try:
        requested_limit = int(match.group("limit") or 0)
    except (TypeError, ValueError):
        requested_limit = 0
    if requested_limit <= 0:
        return plan, [], []
    requested_limit = min(requested_limit, 1000)

    grouping = dict(plan.get("grouping") or {}) if isinstance(plan.get("grouping"), Mapping) else {}
    grouping["limit"] = requested_limit

    selects = dict(plan.get("selects") or {}) if isinstance(plan.get("selects"), Mapping) else {}
    dimensions = [dict(item) for item in list(selects.get("dimensions") or []) if isinstance(item, Mapping)]
    metrics = [dict(item) for item in list(selects.get("metrics") or []) if isinstance(item, Mapping)]

    metric_ref = ""
    if metrics:
        metric_ref = _norm_key(metrics[0].get("metric_ref"))
    else:
        metric_ref = _pick_metric_ref_for_top_bottom(prompt_norm=prompt_norm, capabilities=capabilities)
        if metric_ref:
            metrics = [{"metric_ref": metric_ref}]
            selects["metrics"] = metrics
            plan["selects"] = selects

    if metrics and _norm_key(plan.get("intent")) != "aggregate":
        plan["intent"] = "aggregate"

    if len(list(grouping.get("group_by") or [])) == 0 and dimensions:
        grouping["group_by"] = [
            str(item.get("column_key") or "").strip()
            for item in dimensions
            if str(item.get("column_key") or "").strip()
        ]

    if metric_ref:
        metric_direction = "desc" if ranking_kind == "top" else "asc"
        grouping["order_by"] = [{"by": f"metric:{metric_ref}", "dir": metric_direction}]

    plan["grouping"] = grouping
    debug_rows = [
        {
            "action": "normalized_top_bottom_ranking",
            "kind": ranking_kind,
            "limit": requested_limit,
            "metric_ref": metric_ref,
        }
    ]
    return plan, [], debug_rows
