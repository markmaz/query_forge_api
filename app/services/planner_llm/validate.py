from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


TIME_RANGE_RE = re.compile(r"\b(last year|this year|current school year|this semester|last semester|last month|this month)\b")
RATIO_HINT_RE = re.compile(r"\b(per|ratio|rate)\b")
_OVER_AGG_FUNCS = {"avg", "sum", "min", "max"}
_SAFE_NUMERIC_AGGS = {"count", "count_distinct", "sum", "avg", "min", "max"}


@dataclass
class ValidationResult:
    plan_json: Dict[str, Any]
    is_valid: bool
    errors: List[str]
    repairs_applied: List[str]


def validate_and_repair(
    *,
    plan_json: Dict[str, Any],
    candidates: Mapping[str, Sequence[Dict[str, Any]]],
    normalized_prompt: str,
    allow_pii: bool,
    group_by_cap: int = 8,
    max_domains: int = 3,
) -> ValidationResult:
    plan = _normalize_plan(plan_json)
    errors: List[str] = []
    repairs: List[str] = []

    col_lookup = _column_lookup(candidates.get("columns") or [])
    domains = [dict(row) for row in list(candidates.get("domains") or []) if isinstance(row, dict)]

    _repair_missing_columns(plan=plan, col_lookup=col_lookup, repairs=repairs)
    _repair_prompt_as_filter_value(plan=plan, normalized_prompt=normalized_prompt, errors=errors, repairs=repairs)
    _repair_long_filter_values(plan=plan, errors=errors, repairs=repairs)
    _repair_bad_aggregates(plan=plan, col_lookup=col_lookup, errors=errors, repairs=repairs)
    _repair_invalid_metric_types(plan=plan, col_lookup=col_lookup, errors=errors, repairs=repairs)
    _repair_group_by_cap(plan=plan, cap=max(1, int(group_by_cap)), repairs=repairs)
    _repair_pii(plan=plan, col_lookup=col_lookup, allow_pii=allow_pii, errors=errors, repairs=repairs)
    _repair_trend_time_grain(plan=plan, repairs=repairs)
    _repair_ratio_metric_requirement(plan=plan, normalized_prompt=normalized_prompt, errors=errors, repairs=repairs)
    _repair_promote_derived_metrics(plan=plan, repairs=repairs)
    _repair_domain_coverage_for_derived(
        plan=plan,
        col_lookup=col_lookup,
        domain_candidates=domains,
        max_domains=max_domains,
        errors=errors,
        repairs=repairs,
    )
    _repair_time_range_requirement(
        plan=plan,
        normalized_prompt=normalized_prompt,
        col_lookup=col_lookup,
        errors=errors,
        repairs=repairs,
    )

    is_valid = len(errors) == 0
    return ValidationResult(plan_json=plan, is_valid=is_valid, errors=errors, repairs_applied=repairs)


def _normalize_plan(plan_json: Dict[str, Any]) -> Dict[str, Any]:
    plan = dict(plan_json or {})
    plan["intent"] = str(plan.get("intent") or "list").strip().lower()
    grain = plan.get("grain") if isinstance(plan.get("grain"), dict) else {}
    plan["grain"] = {
        "entity": str(grain.get("entity") or "entity").strip() or "entity",
        "time_grain": grain.get("time_grain"),
    }
    selects = plan.get("selects") if isinstance(plan.get("selects"), dict) else {}
    plan["selects"] = {
        "metrics": [
            _normalize_metric_item(item, is_agg=False)
            for item in list(selects.get("metrics") or [])
            if isinstance(item, dict)
        ],
        "dimensions": [dict(item) for item in list(selects.get("dimensions") or []) if isinstance(item, dict)],
    }
    plan["filters"] = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, dict)]
    domains = [item for item in list(plan.get("domains") or []) if isinstance(item, (int, float, str))]
    plan["domains"] = [int(item) for item in domains if _to_int(item) is not None]
    aggregation = plan.get("aggregation") if isinstance(plan.get("aggregation"), dict) else {}
    plan["aggregation"] = {
        "group_by": [str(item) for item in list(aggregation.get("group_by") or []) if str(item).strip()],
        "metrics": [
            _normalize_metric_item(item, is_agg=True)
            for item in list(aggregation.get("metrics") or [])
            if isinstance(item, dict)
        ],
    }
    plan["derived_metrics"] = [
        dm for dm in (_normalize_derived_metric(item) for item in list(plan.get("derived_metrics") or []) if isinstance(item, dict)) if dm
    ]
    return plan


def _normalize_metric_item(item: Dict[str, Any], *, is_agg: bool) -> Dict[str, Any]:
    metric_ref = _normalize_metric_ref(item.get("metric_ref"), item.get("column_key"))
    agg_raw = item.get("agg")
    agg: Optional[str] = None if agg_raw in (None, "") else str(agg_raw).strip().lower()
    if agg is not None and agg not in _SAFE_NUMERIC_AGGS:
        agg = None
    out: Dict[str, Any] = {
        "metric_ref": metric_ref,
        "agg": agg,
        "label": str(item.get("label") or "").strip() or None,
    }
    kind = str(item.get("kind") or "").strip().lower()
    if kind:
        out["kind"] = kind
    if not is_agg and out.get("kind") is None:
        out["kind"] = "numeric"
    return out


def _normalize_metric_ref(metric_ref: Any, column_key: Any) -> str:
    ref = str(metric_ref or "").strip()
    if ref == "":
        col = str(column_key or "").strip()
        if col:
            return f"column:{col.lower()}"
        return ""
    lower = ref.lower()
    if lower.startswith("column:"):
        return f"column:{lower.split(':', 1)[1].strip()}"
    if lower.startswith("derived:"):
        return f"derived:{lower.split(':', 1)[1].strip()}"
    return f"column:{lower}"


def _normalize_derived_metric(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = str(item.get("name") or "").strip().lower()
    if name == "":
        return None
    kind = str(item.get("kind") or "ratio").strip().lower()
    if kind != "ratio":
        return None

    numerator = item.get("numerator")
    denominator = item.get("denominator")
    if not isinstance(numerator, dict):
        numerator = {
            "column_key": item.get("numerator_column_key"),
            "agg": item.get("numerator_agg") or "count_distinct",
        }
    if not isinstance(denominator, dict):
        denominator = {
            "column_key": item.get("denominator_column_key"),
            "agg": item.get("denominator_agg") or "count_distinct",
        }
    num_key = str(numerator.get("column_key") or "").strip().lower()
    den_key = str(denominator.get("column_key") or "").strip().lower()
    if num_key == "" or den_key == "":
        return None
    num_agg = str(numerator.get("agg") or "count_distinct").strip().lower()
    den_agg = str(denominator.get("agg") or "count_distinct").strip().lower()
    if num_agg not in _SAFE_NUMERIC_AGGS or den_agg not in _SAFE_NUMERIC_AGGS:
        return None
    return {
        "name": name,
        "kind": "ratio",
        "numerator": {"column_key": num_key, "agg": num_agg},
        "denominator": {"column_key": den_key, "agg": den_agg},
        "safe_divide": bool(item.get("safe_divide", True)),
    }


def _column_lookup(columns: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in columns:
        if not isinstance(row, dict):
            continue
        key = str(row.get("column_key") or "").strip().lower()
        if key == "":
            continue
        out[key] = dict(row)
    return out


def _derived_lookup(plan: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for dm in list(plan.get("derived_metrics") or []):
        if not isinstance(dm, dict):
            continue
        name = str(dm.get("name") or "").strip().lower()
        if name:
            out[name] = dm
    return out


def _split_metric_ref(metric_ref: Any) -> Tuple[str, str]:
    ref = str(metric_ref or "").strip().lower()
    if ref.startswith("column:"):
        return "column", ref.split(":", 1)[1].strip()
    if ref.startswith("derived:"):
        return "derived", ref.split(":", 1)[1].strip()
    if ref:
        return "column", ref
    return "", ""


def _repair_missing_columns(*, plan: Dict[str, Any], col_lookup: Dict[str, Dict[str, Any]], repairs: List[str]) -> None:
    derived = _derived_lookup(plan)

    before_dims = len(plan["selects"]["dimensions"])
    plan["selects"]["dimensions"] = [
        item for item in plan["selects"]["dimensions"] if str(item.get("column_key") or "").strip().lower() in col_lookup
    ]
    if len(plan["selects"]["dimensions"]) != before_dims:
        repairs.append("dropped_unknown_dimension_columns")

    before_filters = len(plan["filters"])
    plan["filters"] = [
        item for item in plan["filters"] if str(item.get("column_key") or "").strip().lower() in col_lookup
    ]
    if len(plan["filters"]) != before_filters:
        repairs.append("dropped_unknown_filter_columns")

    before_group = len(plan["aggregation"]["group_by"])
    plan["aggregation"]["group_by"] = [
        key for key in plan["aggregation"]["group_by"] if str(key).strip().lower() in col_lookup
    ]
    if len(plan["aggregation"]["group_by"]) != before_group:
        repairs.append("dropped_unknown_groupby_columns")

    before_select_metrics = len(plan["selects"]["metrics"])
    kept_select_metrics: List[Dict[str, Any]] = []
    for item in plan["selects"]["metrics"]:
        ref_kind, ref_value = _split_metric_ref(item.get("metric_ref"))
        if ref_kind == "column" and ref_value in col_lookup:
            kept_select_metrics.append(item)
            continue
        if ref_kind == "derived" and ref_value in derived:
            kept_select_metrics.append(item)
    plan["selects"]["metrics"] = kept_select_metrics
    if len(kept_select_metrics) != before_select_metrics:
        repairs.append("dropped_unknown_select_metrics")

    before_agg = len(plan["aggregation"]["metrics"])
    kept_agg_metrics: List[Dict[str, Any]] = []
    for item in plan["aggregation"]["metrics"]:
        ref_kind, ref_value = _split_metric_ref(item.get("metric_ref"))
        if ref_kind == "column" and ref_value in col_lookup:
            kept_agg_metrics.append(item)
            continue
        if ref_kind == "derived" and ref_value in derived:
            kept_agg_metrics.append(item)
    plan["aggregation"]["metrics"] = kept_agg_metrics
    if len(kept_agg_metrics) != before_agg:
        repairs.append("dropped_unknown_aggregate_metrics")


def _repair_prompt_as_filter_value(
    *,
    plan: Dict[str, Any],
    normalized_prompt: str,
    errors: List[str],
    repairs: List[str],
) -> None:
    prompt_key = _norm_text(normalized_prompt)
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for item in plan["filters"]:
        value = item.get("value")
        if isinstance(value, str) and _norm_text(value) == prompt_key:
            dropped += 1
            continue
        kept.append(item)
    if dropped > 0:
        repairs.append("removed_prompt_as_filter_value")
        errors.append("filter_value_equal_to_prompt_removed")
    plan["filters"] = kept


def _repair_long_filter_values(*, plan: Dict[str, Any], errors: List[str], repairs: List[str]) -> None:
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for item in plan["filters"]:
        value = item.get("value")
        op = str(item.get("op") or "").strip().lower()
        if op == "in" and isinstance(value, list) and len(value) > 1:
            too_long = any(isinstance(v, str) and len(v) > 80 for v in value)
            if too_long:
                dropped += 1
                continue
            kept.append(item)
            continue
        if isinstance(value, str) and len(value) > 80:
            dropped += 1
            continue
        kept.append(item)
    if dropped > 0:
        repairs.append("removed_overlong_filter_values")
        errors.append("overlong_filter_value_removed")
    plan["filters"] = kept


def _repair_bad_aggregates(
    *,
    plan: Dict[str, Any],
    col_lookup: Dict[str, Dict[str, Any]],
    errors: List[str],
    repairs: List[str],
) -> None:
    changed = 0
    for metric in plan["aggregation"]["metrics"]:
        ref_kind, ref_value = _split_metric_ref(metric.get("metric_ref"))
        if ref_kind != "column":
            continue
        agg = str(metric.get("agg") or "").strip().lower()
        if agg not in {"avg", "sum"}:
            continue
        row = col_lookup.get(ref_value) or {}
        semantic_type = str(row.get("semantic_type_strict") or "").strip().lower()
        data_type = str(row.get("data_type") or "").strip().lower()
        if semantic_type == "categorical" or data_type in {"text", "string", "varchar", "char"}:
            metric["agg"] = "count"
            changed += 1
    if changed > 0:
        repairs.append("repaired_bad_aggregate_types")
        errors.append("aggregate_mismatch_repaired")


def _repair_invalid_metric_types(
    *,
    plan: Dict[str, Any],
    col_lookup: Dict[str, Dict[str, Any]],
    errors: List[str],
    repairs: List[str],
) -> None:
    derived = _derived_lookup(plan)
    best_derived_name = next(iter(derived.keys()), "")
    removed_any = False
    replaced_any = False

    for section in ("selects", "aggregation"):
        metrics = plan[section]["metrics"]
        keep: List[Dict[str, Any]] = []
        for item in metrics:
            ref_kind, ref_value = _split_metric_ref(item.get("metric_ref"))
            agg = str(item.get("agg") or "").strip().lower()
            if ref_kind == "column" and agg in _OVER_AGG_FUNCS:
                row = col_lookup.get(ref_value) or {}
                if _is_invalid_metric_column(row):
                    if best_derived_name:
                        item["metric_ref"] = f"derived:{best_derived_name}"
                        item["agg"] = None
                        if section == "selects":
                            item["kind"] = "ratio"
                        replaced_any = True
                        keep.append(item)
                    else:
                        removed_any = True
                    continue
            keep.append(item)
        if section == "selects":
            plan["selects"]["metrics"] = keep
        else:
            plan["aggregation"]["metrics"] = keep

    if replaced_any:
        repairs.append("replaced_invalid_metrics_with_derived_ratio")
    if removed_any:
        repairs.append("removed_invalid_metrics")
        errors.append("invalid_metric_type")


def _is_invalid_metric_column(row: Dict[str, Any]) -> bool:
    data_type = str(row.get("data_type") or "").strip().lower()
    semantic = str(row.get("semantic_type_strict") or "").strip().lower()
    column_name = str(row.get("column_name") or "").strip().lower()
    if data_type in {"string", "varchar", "char", "text"}:
        return True
    if semantic in {"identifier", "id", "code"}:
        return True
    if column_name.endswith("_id") or column_name.endswith("_code"):
        return True
    if "_id_" in column_name or "fips" in column_name:
        return True
    return False


def _repair_promote_derived_metrics(*, plan: Dict[str, Any], repairs: List[str]) -> None:
    derived = _derived_lookup(plan)
    if not derived:
        return
    references = set()
    for item in plan["selects"]["metrics"]:
        ref_kind, ref_value = _split_metric_ref(item.get("metric_ref"))
        if ref_kind == "derived":
            references.add(ref_value)
    for item in plan["aggregation"]["metrics"]:
        ref_kind, ref_value = _split_metric_ref(item.get("metric_ref"))
        if ref_kind == "derived":
            references.add(ref_value)
    if references:
        return

    name = next(iter(derived.keys()))
    plan["selects"]["metrics"].append(
        {
            "metric_ref": f"derived:{name}",
            "agg": None,
            "kind": "ratio",
            "label": name,
        }
    )
    plan["aggregation"]["metrics"].append(
        {
            "metric_ref": f"derived:{name}",
            "agg": None,
            "label": name,
        }
    )
    repairs.append("promoted_derived_metric_to_selected")


def _repair_domain_coverage_for_derived(
    *,
    plan: Dict[str, Any],
    col_lookup: Dict[str, Dict[str, Any]],
    domain_candidates: Sequence[Dict[str, Any]],
    max_domains: int,
    errors: List[str],
    repairs: List[str],
) -> None:
    required_tables: set[str] = set()
    for dm in list(plan.get("derived_metrics") or []):
        if not isinstance(dm, dict):
            continue
        num = (dm.get("numerator") or {}).get("column_key")
        den = (dm.get("denominator") or {}).get("column_key")
        for key in (num, den):
            row = col_lookup.get(str(key or "").strip().lower()) or {}
            table = str(row.get("table") or "").strip().lower()
            if table:
                required_tables.add(table)
    if not required_tables:
        return

    selected_ids: List[int] = []
    for did in plan.get("domains") or []:
        if _to_int(did) is None:
            continue
        iv = int(did)
        if iv not in selected_ids:
            selected_ids.append(iv)
    if len(selected_ids) > max_domains:
        selected_ids = selected_ids[:max_domains]
        repairs.append("capped_domain_count")

    by_id: Dict[int, Dict[str, Any]] = {}
    ordered_domains: List[Dict[str, Any]] = []
    for row in domain_candidates:
        did = _to_int(row.get("domain_id"))
        if did is None:
            continue
        tables = [str(t).strip().lower() for t in list(row.get("tables") or []) if str(t).strip()]
        entry = {"domain_id": int(did), "tables": tables}
        by_id[int(did)] = entry
        ordered_domains.append(entry)

    def coverage(domain_ids: Sequence[int]) -> set[str]:
        out: set[str] = set()
        for did in domain_ids:
            out.update(set((by_id.get(int(did)) or {}).get("tables") or []))
        return out

    current_cov = coverage(selected_ids)
    missing = required_tables - current_cov
    added_domains = False
    if missing:
        for row in ordered_domains:
            if len(selected_ids) >= max_domains:
                break
            did = int(row["domain_id"])
            if did in selected_ids:
                continue
            row_tables = set(row.get("tables") or [])
            if not (row_tables & missing):
                continue
            selected_ids.append(did)
            added_domains = True
            missing = required_tables - coverage(selected_ids)
            if not missing:
                break

    plan["domains"] = selected_ids
    if required_tables - coverage(selected_ids):
        errors.append("derived_metric_domain_coverage_incomplete")
    elif added_domains:
        repairs.append("expanded_domains_for_derived_metrics")


def _repair_group_by_cap(*, plan: Dict[str, Any], cap: int, repairs: List[str]) -> None:
    group_by = list(plan["aggregation"]["group_by"])
    if len(group_by) <= cap:
        return
    plan["aggregation"]["group_by"] = group_by[:cap]
    repairs.append("capped_group_by_width")


def _repair_pii(
    *,
    plan: Dict[str, Any],
    col_lookup: Dict[str, Dict[str, Any]],
    allow_pii: bool,
    errors: List[str],
    repairs: List[str],
) -> None:
    if allow_pii:
        return

    pii_keys = {key for key, row in col_lookup.items() if bool(row.get("pii_flag"))}
    if not pii_keys:
        return

    def _drop(items: Sequence[Dict[str, Any]], *, use_metric_ref: bool = False) -> Tuple[List[Dict[str, Any]], int]:
        out: List[Dict[str, Any]] = []
        dropped = 0
        for item in items:
            if use_metric_ref:
                ref_kind, ref_value = _split_metric_ref(item.get("metric_ref"))
                if ref_kind == "column" and ref_value in pii_keys:
                    dropped += 1
                    continue
                out.append(dict(item))
                continue
            key = str(item.get("column_key") or "").strip().lower()
            if key in pii_keys:
                dropped += 1
                continue
            out.append(dict(item))
        return out, dropped

    metrics, dropped_metrics = _drop(plan["selects"]["metrics"], use_metric_ref=True)
    dims, dropped_dims = _drop(plan["selects"]["dimensions"])
    filters, dropped_filters = _drop(plan["filters"])
    agg_metrics, dropped_agg_metrics = _drop(plan["aggregation"]["metrics"], use_metric_ref=True)
    group_by = [k for k in plan["aggregation"]["group_by"] if str(k).strip().lower() not in pii_keys]
    dropped_group = len(plan["aggregation"]["group_by"]) - len(group_by)

    dropped_total = dropped_metrics + dropped_dims + dropped_filters + dropped_agg_metrics + dropped_group
    if dropped_total > 0:
        plan["selects"]["metrics"] = metrics
        plan["selects"]["dimensions"] = dims
        plan["filters"] = filters
        plan["aggregation"]["metrics"] = agg_metrics
        plan["aggregation"]["group_by"] = group_by
        repairs.append("dropped_pii_columns")
        errors.append("pii_columns_removed")


def _repair_trend_time_grain(*, plan: Dict[str, Any], repairs: List[str]) -> None:
    if str(plan.get("intent") or "").strip().lower() != "trend":
        return
    if str((plan.get("grain") or {}).get("time_grain") or "").strip():
        return
    plan["grain"]["time_grain"] = "month"
    repairs.append("set_default_trend_time_grain")


def _repair_ratio_metric_requirement(
    *,
    plan: Dict[str, Any],
    normalized_prompt: str,
    errors: List[str],
    repairs: List[str],
) -> None:
    if RATIO_HINT_RE.search(str(normalized_prompt or "").lower()) is None:
        return
    if list(plan.get("derived_metrics") or []):
        return

    refs: List[Tuple[str, str]] = []
    for item in list(plan["aggregation"]["metrics"]) + list(plan["selects"]["metrics"]):
        ref_kind, ref_value = _split_metric_ref(item.get("metric_ref"))
        if ref_kind != "column":
            continue
        agg = str(item.get("agg") or "").strip().lower() or "count_distinct"
        if agg not in _SAFE_NUMERIC_AGGS:
            agg = "count_distinct"
        token = f"{ref_value}|{agg}"
        if token not in [f"{r}|{a}" for r, a in refs]:
            refs.append((ref_value, agg))
    if len(refs) < 2:
        errors.append("ratio_metric_missing_definition")
        return

    num_key, num_agg = refs[0]
    den_key, den_agg = refs[1]
    plan["derived_metrics"].append(
        {
            "name": "ratio_auto",
            "kind": "ratio",
            "numerator": {"column_key": num_key, "agg": num_agg},
            "denominator": {"column_key": den_key, "agg": den_agg},
            "safe_divide": True,
        }
    )
    repairs.append("added_ratio_derived_metric")


def _repair_time_range_requirement(
    *,
    plan: Dict[str, Any],
    normalized_prompt: str,
    col_lookup: Dict[str, Dict[str, Any]],
    errors: List[str],
    repairs: List[str],
) -> None:
    if TIME_RANGE_RE.search(str(normalized_prompt or "").lower()) is None:
        return

    referenced = _collect_referenced_column_keys(plan)
    has_time = any(_is_time_column(col_lookup.get(key)) for key in referenced if key in col_lookup)
    if has_time:
        return

    for key, row in col_lookup.items():
        if not _is_time_column(row):
            continue
        plan["selects"]["dimensions"].append({"column_key": key, "label": "time"})
        if key not in plan["aggregation"]["group_by"]:
            plan["aggregation"]["group_by"].append(key)
        repairs.append("injected_time_dimension_for_time_range")
        return

    errors.append("time_range_requires_date_column")


def _collect_referenced_column_keys(plan: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for dim in plan["selects"]["dimensions"]:
        key = str(dim.get("column_key") or "").strip().lower()
        if key:
            out.append(key)
    for fil in plan["filters"]:
        key = str(fil.get("column_key") or "").strip().lower()
        if key:
            out.append(key)
    for key in list(plan["aggregation"]["group_by"] or []):
        k = str(key or "").strip().lower()
        if k:
            out.append(k)
    for metric in list(plan["selects"]["metrics"]) + list(plan["aggregation"]["metrics"]):
        ref_kind, ref_value = _split_metric_ref(metric.get("metric_ref"))
        if ref_kind == "column" and ref_value:
            out.append(ref_value)
    for dm in list(plan.get("derived_metrics") or []):
        if not isinstance(dm, dict):
            continue
        num = str(((dm.get("numerator") or {}).get("column_key") or "")).strip().lower()
        den = str(((dm.get("denominator") or {}).get("column_key") or "")).strip().lower()
        if num:
            out.append(num)
        if den:
            out.append(den)
    return list(dict.fromkeys(out))


def _is_time_column(row: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(row, dict):
        return False
    semantic = str(row.get("semantic_type_strict") or "").strip().lower()
    data_type = str(row.get("data_type") or "").strip().lower()
    name = str(row.get("column_name") or "").strip().lower()
    if semantic in {"time", "date", "datetime"}:
        return True
    if data_type in {"date", "datetime", "timestamp"}:
        return True
    return any(token in name for token in ("date", "year", "semester", "quarter", "month"))


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["ValidationResult", "validate_and_repair"]
