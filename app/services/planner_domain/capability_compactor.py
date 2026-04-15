"""Capability compaction helpers for planner-domain selection."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.config import (
    QF_PLAN_DOMAIN_FAST_MODE_MAX_DIMENSIONS,
    QF_PLAN_DOMAIN_FAST_MODE_MAX_FILTER_COLUMNS,
)
from app.services.domain.planner_capability_packing_policy_service import PlannerCapabilityPackingPolicyService
from app.services.domain.planner_projection_policy_service import PlannerProjectionPolicyService
from app.services.planner_domain.column_scoring import (
    _cap_columns_per_table,
    _has_adm_metric,
    _has_adm_signal_columns,
    _has_age_columns,
    _has_birth_date_columns,
    _has_calendar_day_columns,
    _has_canonical_name_columns,
    _has_preferred_state_column,
    _has_school_day_flag_columns,
    _has_staff_identity_column,
    _has_student_identity_column,
    _has_subgroup_column,
    _is_canonical_name_column_name,
    _is_name_column_needed_for_prompt,
    _is_preferred_name_column_name,
    _prompt_explicitly_requests_school_key,
)
from app.services.planner_domain.prompt_intents import (
    _looks_like_list_schools_prompt,
    _prompt_has_subgroup,
)
from app.services.planner_domain.prompt_signal_service import PromptSignalService


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _merge_dimension_rows(*, dimensions: Sequence[Mapping[str, Any]], time_columns: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in list(dimensions) + list(time_columns):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "" or key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _collect_domain_selection_shortlist_features(*, shortlisted_columns: Sequence[Mapping[str, Any]]) -> List[str]:
    features: List[str] = []
    if _has_subgroup_column(shortlisted_columns):
        features.append("SUBGROUP_COLUMN")
    if _has_student_identity_column(shortlisted_columns):
        features.append("STUDENT_IDENTITY_COLUMN")
    if _has_staff_identity_column(shortlisted_columns):
        features.append("STAFF_IDENTITY_COLUMN")
    if _has_adm_signal_columns(shortlisted_columns):
        features.append("ADM_SIGNAL_COLUMN")
    if _has_birth_date_columns(shortlisted_columns):
        features.append("BIRTH_DATE_COLUMN")
    if _has_age_columns(shortlisted_columns):
        features.append("AGE_COLUMN")
    if _has_calendar_day_columns(shortlisted_columns):
        features.append("CALENDAR_DAY_COLUMN")
    if _has_school_day_flag_columns(shortlisted_columns):
        features.append("SCHOOL_DAY_FLAG_COLUMN")
    return features


def _collect_domain_selection_capability_features(*, capabilities: Mapping[str, Any]) -> List[str]:
    features: List[str] = []
    if _has_adm_metric(capabilities):
        features.append("ADM_METRIC")
    return features


def _collect_capability_packing_features(*, full_dims: Sequence[Mapping[str, Any]]) -> List[str]:
    features: List[str] = []
    if _has_preferred_state_column(rows=full_dims):
        features.append("HAS_PREFERRED_STATE_COLUMN")
    if _has_canonical_name_columns(rows=full_dims):
        features.append("HAS_CANONICAL_NAME_COLUMNS")
    return features


def _slot_implies_student_listing(slot_hints: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(slot_hints, Mapping):
        return False
    intent = str(slot_hints.get("intent") or "").strip().lower()
    entity = str(slot_hints.get("entity") or "").strip().lower()
    return intent == "list" and entity in {"student", "students"}


def _slot_implies_school_listing(slot_hints: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(slot_hints, Mapping):
        return False
    intent = str(slot_hints.get("intent") or "").strip().lower()
    entity = str(slot_hints.get("entity") or "").strip().lower()
    return intent == "list" and entity in {"school", "schools"}


def _find_dimension_by_column_name(*, full_dims: Sequence[Mapping[str, Any]], target: str) -> Optional[Dict[str, Any]]:
    needle = str(target or "").strip().lower()
    if needle == "":
        return None
    for row in full_dims:
        col_name = str(row.get("column_name") or "").strip().lower()
        if col_name == needle:
            return dict(row)
    return None


def _find_dimension_by_column_name_candidates(
    *,
    full_dims: Sequence[Mapping[str, Any]],
    targets: Sequence[str],
) -> Optional[Dict[str, Any]]:
    normalized_targets = [str(target or "").strip().lower() for target in targets if str(target or "").strip()]
    if not normalized_targets:
        return None
    for target in normalized_targets:
        matched = _find_dimension_by_column_name(full_dims=full_dims, target=target)
        if matched is not None:
            return matched
    for row in full_dims:
        col_name = str(row.get("column_name") or "").strip().lower()
        if col_name == "":
            continue
        if any(target in col_name for target in normalized_targets):
            return dict(row)
    return None


def _concept_keys_for_row(row: Mapping[str, Any]) -> List[str]:
    out: List[str] = []
    for field_name in ("concept_key", "semantic_concept_key"):
        token = str(row.get(field_name) or "").strip().upper()
        if token and token not in out:
            out.append(token)
    return out


def _prepend_required_concept_dimensions(
    *,
    selected_dims: Sequence[Mapping[str, Any]],
    full_dims: Sequence[Mapping[str, Any]],
    required_concept_keys: Sequence[str],
) -> List[Dict[str, Any]]:
    by_concept: Dict[str, Dict[str, Any]] = {}
    for row in full_dims:
        if not isinstance(row, Mapping):
            continue
        for concept_key in _concept_keys_for_row(row):
            by_concept.setdefault(concept_key, dict(row))

    prefix: List[Dict[str, Any]] = []
    prefix_seen: set[str] = set()
    for concept_key in required_concept_keys:
        matched = by_concept.get(str(concept_key or "").strip().upper())
        if matched is None:
            continue
        key = _norm_key(matched.get("column_key"))
        if key == "" or key in prefix_seen:
            continue
        prefix.append(dict(matched))
        prefix_seen.add(key)

    out: List[Dict[str, Any]] = list(prefix)
    for row in selected_dims:
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "" or key in prefix_seen:
            continue
        out.append(dict(row))
        prefix_seen.add(key)
    return out


def _row_has_excluded_concepts(
    row: Mapping[str, Any],
    *,
    excluded_concept_keys: Sequence[str],
) -> bool:
    excluded = {str(item or "").strip().upper() for item in excluded_concept_keys if str(item or "").strip()}
    if not excluded:
        return False
    row_concepts = set(_concept_keys_for_row(row))
    return bool(row_concepts & excluded)


def _drop_excluded_concept_dimensions(
    *,
    selected_dims: Sequence[Mapping[str, Any]],
    excluded_concept_keys: Sequence[str],
) -> List[Dict[str, Any]]:
    if not excluded_concept_keys:
        return [dict(row) for row in selected_dims if isinstance(row, Mapping)]
    return [
        dict(row)
        for row in selected_dims
        if isinstance(row, Mapping) and not _row_has_excluded_concepts(row, excluded_concept_keys=excluded_concept_keys)
    ]


def _prepend_required_named_dimensions(
    *,
    selected_dims: Sequence[Mapping[str, Any]],
    full_dims: Sequence[Mapping[str, Any]],
    required_column_names: Sequence[str],
) -> List[Dict[str, Any]]:
    normalized_names = [str(item or "").strip().lower() for item in required_column_names if str(item or "").strip()]
    if not normalized_names:
        return [dict(row) for row in selected_dims if isinstance(row, Mapping)]

    by_name: Dict[str, Dict[str, Any]] = {}
    for row in full_dims:
        if not isinstance(row, Mapping):
            continue
        col_name = str(row.get("column_name") or "").strip().lower()
        if col_name and col_name not in by_name:
            by_name[col_name] = dict(row)

    prefix: List[Dict[str, Any]] = []
    prefix_seen: set[str] = set()
    for column_name in normalized_names:
        matched = by_name.get(column_name)
        if matched is None:
            continue
        key = _norm_key(matched.get("column_key"))
        if key == "" or key in prefix_seen:
            continue
        prefix.append(dict(matched))
        prefix_seen.add(key)

    out: List[Dict[str, Any]] = list(prefix)
    for row in selected_dims:
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "" or key in prefix_seen:
            continue
        out.append(dict(row))
        prefix_seen.add(key)
    return out


def _row_has_excluded_column_names(
    row: Mapping[str, Any],
    *,
    excluded_column_names: Sequence[str],
) -> bool:
    excluded = {str(item or "").strip().lower() for item in excluded_column_names if str(item or "").strip()}
    if not excluded:
        return False
    col_name = str(row.get("column_name") or "").strip().lower()
    return bool(col_name) and col_name in excluded


def _drop_excluded_named_dimensions(
    *,
    selected_dims: Sequence[Mapping[str, Any]],
    excluded_column_names: Sequence[str],
) -> List[Dict[str, Any]]:
    if not excluded_column_names:
        return [dict(row) for row in selected_dims if isinstance(row, Mapping)]
    return [
        dict(row)
        for row in selected_dims
        if isinstance(row, Mapping) and not _row_has_excluded_column_names(row, excluded_column_names=excluded_column_names)
    ]


def compact_capabilities_for_llm(
    capabilities: Mapping[str, Any],
    shortlisted_columns: Sequence[Mapping[str, Any]],
    prompt: str,
    slot_hints: Optional[Mapping[str, Any]] = None,
    fast_mode: bool = False,
    workspace_id: Optional[str] = None,
    projection_policy_service: Optional[PlannerProjectionPolicyService] = None,
    capability_packing_policy_service: Optional[PlannerCapabilityPackingPolicyService] = None,
    include_projection_policy_debug: bool = False,
) -> Dict[str, Any]:
    full_dims = [dict(row) for row in list(capabilities.get("dimensions") or []) if isinstance(row, dict)]
    full_time = [dict(row) for row in list(capabilities.get("time_columns") or []) if isinstance(row, dict)]
    full_filter_candidates = _merge_dimension_rows(dimensions=full_dims, time_columns=full_time)
    dim_by_key = {_norm_key(row.get("column_key")): row for row in full_dims if _norm_key(row.get("column_key"))}
    is_school_listing = _looks_like_list_schools_prompt(prompt) or _slot_implies_school_listing(slot_hints)
    prompt_signals = set(PromptSignalService().extract_signals(prompt=prompt))
    if is_school_listing:
        prompt_signals.update({"school_listing", "listing_intent"})
    if _slot_implies_student_listing(slot_hints):
        prompt_signals.update({"student_listing", "listing_intent", "needs_student_identity"})
    if _prompt_explicitly_requests_school_key(prompt):
        prompt_signals.add("explicit_school_key_request")
    policy_result = (projection_policy_service or PlannerProjectionPolicyService()).get_projection_requirements(
        workspace_id=workspace_id,
        base_domain_id=_to_int(capabilities.get("domain_id")),
        prompt_signals=sorted(prompt_signals),
    )
    packing_policy_result = (
        capability_packing_policy_service or PlannerCapabilityPackingPolicyService()
    ).get_packing_requirements(
        workspace_id=workspace_id,
        prompt_signals=sorted(prompt_signals),
        capability_features=_collect_capability_packing_features(full_dims=full_dims),
    )
    prefer_canonical_name_columns = bool(packing_policy_result.get("prefer_canonical_name_columns"))
    include_name_constraint_columns = bool(packing_policy_result.get("include_name_constraint_columns"))
    excluded_concept_keys = policy_result.get("excluded_concept_keys") or []
    required_column_names = policy_result.get("required_column_names") or []
    excluded_column_names = [
        *list(policy_result.get("excluded_column_names") or []),
        *list(packing_policy_result.get("excluded_column_names") or []),
    ]

    selected_dims: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in shortlisted_columns:
        key = _norm_key(row.get("column_key"))
        if key == "" or key in seen:
            continue
        base = dim_by_key.get(key) or dict(row)
        selected_dims.append(base)
        seen.add(key)

    if not selected_dims:
        selected_dims = full_dims[:40]
        seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}

    if _prompt_has_subgroup(prompt):
        for row in full_dims:
            key = _norm_key(row.get("column_key"))
            if key in seen:
                continue
            col_name = str(row.get("column_name") or key).lower()
            if any(token in col_name for token in ("race", "ethnicity", "hispanic", "latino")):
                selected_dims.append(row)
                seen.add(key)

    if policy_result.get("required_concept_keys"):
        selected_dims = _prepend_required_concept_dimensions(
            selected_dims=selected_dims,
            full_dims=full_dims,
            required_concept_keys=policy_result.get("required_concept_keys") or [],
        )
        seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
    if required_column_names:
        selected_dims = _prepend_required_named_dimensions(
            selected_dims=selected_dims,
            full_dims=full_dims,
            required_column_names=required_column_names,
        )
        seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
    prepend_column_names = packing_policy_result.get("prepend_column_names") or []
    if prepend_column_names:
        selected_dims = _prepend_required_named_dimensions(
            selected_dims=selected_dims,
            full_dims=full_dims,
            required_column_names=prepend_column_names,
        )
        seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
    append_first_match_column_name_groups = packing_policy_result.get("append_first_match_column_name_groups") or []
    for target_group in append_first_match_column_name_groups:
        matched_dim = _find_dimension_by_column_name_candidates(
            full_dims=full_dims,
            targets=tuple(str(item) for item in list(target_group or [])),
        )
        if matched_dim is None:
            continue
        matched_key = _norm_key(matched_dim.get("column_key"))
        if matched_key and matched_key not in seen:
            selected_dims.append(dict(matched_dim))
            seen.add(matched_key)
    append_column_names = {
        str(item).strip().lower()
        for item in list(packing_policy_result.get("append_column_names") or [])
        if str(item).strip()
    }
    if append_column_names:
        for row in full_dims:
            key = _norm_key(row.get("column_key"))
            if key in seen:
                continue
            col_name = str(row.get("column_name") or key).lower()
            if col_name in append_column_names:
                selected_dims.append(dict(row))
                seen.add(key)

    if prefer_canonical_name_columns:
        selected_dims = [
            dict(row)
            for row in selected_dims
            if not _is_preferred_name_column_name(str(row.get("column_name") or "").strip().lower())
        ]
        seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
        for row in full_dims:
            key = _norm_key(row.get("column_key"))
            if key in seen:
                continue
            col_name = str(row.get("column_name") or key).lower()
            if _is_canonical_name_column_name(col_name):
                selected_dims.append(row)
                seen.add(key)

    if include_name_constraint_columns:
        for row in full_dims:
            key = _norm_key(row.get("column_key"))
            if key in seen:
                continue
            col_name = str(row.get("column_name") or key).lower()
            if _is_name_column_needed_for_prompt(prompt=prompt, column_name=col_name):
                selected_dims.append(row)
                seen.add(key)

    selected_dims = _drop_excluded_concept_dimensions(
        selected_dims=selected_dims,
        excluded_concept_keys=excluded_concept_keys,
    )
    selected_dims = _drop_excluded_named_dimensions(
        selected_dims=selected_dims,
        excluded_column_names=excluded_column_names,
    )
    max_columns = max(12, int(QF_PLAN_DOMAIN_FAST_MODE_MAX_DIMENSIONS)) if fast_mode else 70
    per_table_cap = 8 if fast_mode else 14
    selected_dims = _cap_columns_per_table(selected_dims, max_columns=max_columns, per_table_cap=per_table_cap)
    selected_time = [dict(row) for row in full_time[: (8 if fast_mode else 12)]]

    filter_columns: List[Dict[str, Any]] = []
    filter_seen: set[str] = set()

    def _add_filter_row(row: Mapping[str, Any]) -> None:
        key = _norm_key(row.get("column_key"))
        if key == "" or key in filter_seen:
            return
        if row.get("filterable") is False:
            return
        if _row_has_excluded_concepts(row, excluded_concept_keys=excluded_concept_keys):
            return
        if _row_has_excluded_column_names(row, excluded_column_names=excluded_column_names):
            return
        col_name = str(row.get("column_name") or "").strip().lower()
        if prefer_canonical_name_columns and _is_preferred_name_column_name(col_name):
            return
        filter_columns.append(dict(row))
        filter_seen.add(key)

    for row in selected_dims:
        _add_filter_row(row)
    for row in selected_time:
        _add_filter_row(row)

    required_filter_column_names = {
        str(item).strip().lower()
        for item in list(packing_policy_result.get("required_filter_column_names") or [])
        if str(item).strip()
    }
    if required_filter_column_names:
        for row in full_filter_candidates:
            col_name = str(row.get("column_name") or "").strip().lower()
            if col_name in required_filter_column_names:
                _add_filter_row(row)

    if include_name_constraint_columns:
        for row in full_filter_candidates:
            col_name = str(row.get("column_name") or "").strip().lower()
            if _is_name_column_needed_for_prompt(prompt=prompt, column_name=col_name):
                _add_filter_row(row)

    max_filter_columns = max(12, int(QF_PLAN_DOMAIN_FAST_MODE_MAX_FILTER_COLUMNS)) if fast_mode else len(filter_columns)
    if len(filter_columns) > max_filter_columns:
        filter_columns = filter_columns[:max_filter_columns]

    result = {
        "domain_id": _to_int(capabilities.get("domain_id")) or 0,
        "domain_version": _to_int(capabilities.get("domain_version")) or 0,
        "dimensions": selected_dims,
        "time_columns": selected_time,
        "filter_columns": filter_columns,
        "domain_metrics": [dict(row) for row in list(capabilities.get("domain_metrics") or []) if isinstance(row, dict)],
        "user_metrics": [dict(row) for row in list(capabilities.get("user_metrics") or []) if isinstance(row, dict)],
        "overlay_metrics": [dict(row) for row in list(capabilities.get("overlay_metrics") or []) if isinstance(row, dict)],
    }
    if include_projection_policy_debug:
        result["projection_policy_debug"] = {
            "prompt_signals": sorted(prompt_signals),
            "matched_policies": [str(item) for item in list(policy_result.get("matched_policies") or []) if str(item or "").strip()],
            "projection_mode": str(policy_result.get("projection_mode") or "prepend"),
            "required_concept_keys": [str(item) for item in list(policy_result.get("required_concept_keys") or []) if str(item or "").strip()],
            "excluded_concept_keys": [str(item) for item in list(policy_result.get("excluded_concept_keys") or []) if str(item or "").strip()],
            "required_column_names": [str(item) for item in list(policy_result.get("required_column_names") or []) if str(item or "").strip()],
            "excluded_column_names": [str(item) for item in list(policy_result.get("excluded_column_names") or []) if str(item or "").strip()],
            "required_filter_concept_keys": [
                str(item) for item in list(policy_result.get("required_filter_concept_keys") or []) if str(item or "").strip()
            ],
            "required_join_tables": [str(item) for item in list(policy_result.get("required_join_tables") or []) if str(item or "").strip()],
        }
    return result


def full_capabilities_for_execution(capabilities: Mapping[str, Any]) -> Dict[str, Any]:
    dimensions = [dict(row) for row in list(capabilities.get("dimensions") or []) if isinstance(row, dict)]
    time_columns = [dict(row) for row in list(capabilities.get("time_columns") or []) if isinstance(row, dict)]
    filter_columns = [
        dict(row)
        for row in _merge_dimension_rows(dimensions=dimensions, time_columns=time_columns)
        if row.get("filterable") is not False
    ]
    return {
        "domain_id": _to_int(capabilities.get("domain_id")) or 0,
        "domain_version": _to_int(capabilities.get("domain_version")) or 0,
        "dimensions": dimensions,
        "time_columns": time_columns,
        "filter_columns": filter_columns,
        "domain_metrics": [dict(row) for row in list(capabilities.get("domain_metrics") or []) if isinstance(row, dict)],
        "user_metrics": [dict(row) for row in list(capabilities.get("user_metrics") or []) if isinstance(row, dict)],
        "overlay_metrics": [dict(row) for row in list(capabilities.get("overlay_metrics") or []) if isinstance(row, dict)],
    }
