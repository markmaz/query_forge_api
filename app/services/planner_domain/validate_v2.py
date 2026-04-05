from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


_COLUMN_TOKEN_RE = re.compile(r"^wt\d+\.[a-z0-9_]+$")


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class ValidationResult:
    plan_json: Dict[str, Any]
    is_valid: bool
    issues: List[Dict[str, str]]
    repairs_applied: List[str]


def validate_and_repair_plan_v2(
    *,
    plan_json: Dict[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str,
    expected_base_domain_id: Optional[int] = None,
    extra_issues: Optional[Sequence[Mapping[str, Any]]] = None,
) -> ValidationResult:
    plan = _normalize_plan(plan_json)
    repairs: List[str] = []
    issues: List[ValidationIssue] = []

    dim_rows = [row for row in list(capabilities.get("dimensions") or []) if isinstance(row, dict)]
    time_rows = [row for row in list(capabilities.get("time_columns") or []) if isinstance(row, dict)]
    raw_filter_rows = [row for row in list(capabilities.get("filter_columns") or []) if isinstance(row, dict)]
    domain_metrics = [row for row in list(capabilities.get("domain_metrics") or []) if isinstance(row, dict)]
    user_metrics = [row for row in list(capabilities.get("user_metrics") or []) if isinstance(row, dict)]
    overlay_metrics = [row for row in list(capabilities.get("overlay_metrics") or []) if isinstance(row, dict)]

    filter_rows = raw_filter_rows
    if not filter_rows:
        filter_rows = [
            row
            for row in dim_rows + time_rows
            if row.get("filterable") is not False
        ]

    allowed_dim_keys = {
        _norm_key(row.get("column_key"))
        for row in dim_rows
        if _norm_key(row.get("column_key"))
    }
    allowed_filter_keys = {
        _norm_key(row.get("column_key"))
        for row in filter_rows
        if _norm_key(row.get("column_key"))
    }
    allowed_time_keys = {
        _norm_key(row.get("column_key"))
        for row in time_rows
        if _norm_key(row.get("column_key"))
    }
    dim_key_by_column_name = _unique_allowed_key_by_column_name(allowed_dim_keys)
    filter_key_by_column_name = _unique_allowed_key_by_column_name(allowed_filter_keys)
    time_key_by_column_name = _unique_allowed_key_by_column_name(allowed_time_keys)

    allowed_metric_refs = set()
    for row in domain_metrics:
        metric_key = _norm_key(row.get("metric_key"))
        if metric_key:
            allowed_metric_refs.add(f"domain_metric:{metric_key}")
    for row in user_metrics:
        metric_id = _norm_metric_id(row)
        if metric_id:
            allowed_metric_refs.add(f"user_metric:{metric_id}")
    for row in overlay_metrics:
        overlay_key = _norm_key(row.get("overlay_key"))
        if overlay_key:
            allowed_metric_refs.add(f"overlay:{overlay_key}")

    if expected_base_domain_id is not None:
        if _to_int(plan.get("base_domain_id")) != int(expected_base_domain_id):
            issues.append(
                ValidationIssue(
                    code="invalid_base_domain",
                    path="base_domain_id",
                    message="base_domain_id does not match selected domain",
                )
            )
    if _to_int(plan.get("base_domain_id")) is None:
        issues.append(
            ValidationIssue(
                code="missing_base_domain",
                path="base_domain_id",
                message="base_domain_id is required",
            )
        )

    dims = list((plan.get("selects") or {}).get("dimensions") or [])
    for idx, item in enumerate(dims):
        original_key = _norm_key(item.get("column_key"))
        key = _repair_column_key_by_name(
            key=original_key,
            allowed_keys=allowed_dim_keys,
            unique_by_column_name=dim_key_by_column_name,
        )
        item["column_key"] = key
        if key != original_key and original_key:
            repairs.append(f"remapped_dimension_column:{original_key}->{key}")
        if key not in allowed_dim_keys:
            issues.append(
                ValidationIssue(
                    code="invalid_dimension_column",
                    path=f"selects.dimensions[{idx}].column_key",
                    message=f"Column '{key}' is not allowed for this domain",
                )
            )

    group_by = [_norm_key(item) for item in list((plan.get("grouping") or {}).get("group_by") or []) if _norm_key(item)]
    dim_keys = [_norm_key(item.get("column_key")) for item in dims if _norm_key(item.get("column_key"))]
    if group_by != dim_keys:
        plan["grouping"]["group_by"] = list(dim_keys)
        repairs.append("normalized_group_by_dimensions")

    filters = list(plan.get("filters") or [])
    kept_filters: List[Dict[str, Any]] = []
    norm_prompt = _norm_text(prompt)
    for idx, item in enumerate(filters):
        original_key = _norm_key(item.get("column_key"))
        key = _repair_column_key_by_name(
            key=original_key,
            allowed_keys=allowed_filter_keys,
            unique_by_column_name=filter_key_by_column_name,
        )
        op = str(item.get("op") or "").strip().lower()
        value = item.get("value")

        item["column_key"] = key
        item["op"] = op or "="
        if key != original_key and original_key:
            repairs.append(f"remapped_filter_column:{original_key}->{key}")

        if key not in allowed_filter_keys:
            repairs.append(f"dropped_invalid_filter:{key}")
            continue

        if isinstance(value, str) and _norm_text(value) == norm_prompt:
            issues.append(
                ValidationIssue(
                    code="invalid_filter_value_prompt_echo",
                    path=f"filters[{idx}].value",
                    message="Filter value cannot equal full prompt",
                )
            )
            repairs.append("removed_prompt_echo_filter")
            continue

        if _is_self_referential_filter_value(column_key=key, value=value):
            repairs.append("removed_self_referential_filter")
            continue

        if _contains_column_token_value(op=op, value=value):
            repairs.append("removed_column_token_filter_value")
            continue

        if _is_missing_filter_value(op=op, item=item):
            repairs.append("removed_missing_filter_value")
            continue

        if _is_overlong_filter_value(op=op, value=value):
            issues.append(
                ValidationIssue(
                    code="invalid_filter_value_length",
                    path=f"filters[{idx}].value",
                    message="Filter value too long",
                )
            )
            repairs.append("removed_overlong_filter")
            continue

        kept_filters.append(item)
    plan["filters"] = kept_filters

    metric_items = list((plan.get("selects") or {}).get("metrics") or [])
    for idx, item in enumerate(metric_items):
        ref = _norm_metric_ref(item.get("metric_ref"))
        item["metric_ref"] = ref
        if ref not in allowed_metric_refs:
            issues.append(
                ValidationIssue(
                    code="unknown_metric_ref",
                    path=f"selects.metrics[{idx}].metric_ref",
                    message=f"Metric ref '{ref}' is not available for this domain",
                )
            )

    time_block = plan.get("time") if isinstance(plan.get("time"), dict) else {}
    original_time_col = _norm_key(time_block.get("time_column_key"))
    time_col = _repair_column_key_by_name(
        key=original_time_col,
        allowed_keys=allowed_time_keys,
        unique_by_column_name=time_key_by_column_name,
    )
    if time_col != original_time_col and original_time_col:
        repairs.append(f"remapped_time_column:{original_time_col}->{time_col}")
    if time_col and time_col not in allowed_time_keys:
        issues.append(
            ValidationIssue(
                code="invalid_time_column",
                path="time.time_column_key",
                message=f"time_column_key '{time_col}' is not allowed",
            )
        )
    if time_col:
        time_block["time_column_key"] = time_col
        plan["time"] = time_block

    order_items = list((plan.get("grouping") or {}).get("order_by") or [])
    normalized_order: List[Dict[str, Any]] = []
    for idx, item in enumerate(order_items):
        by = str(item.get("by") or "").strip().lower()
        direction = str(item.get("dir") or "asc").strip().lower()
        if direction not in {"asc", "desc"}:
            direction = "asc"
        kind, value = _split_order_by(by)
        if kind == "dimension" and value not in allowed_dim_keys:
            issues.append(
                ValidationIssue(
                    code="invalid_order_by_dimension",
                    path=f"grouping.order_by[{idx}].by",
                    message=f"order_by dimension '{value}' is invalid",
                )
            )
            continue
        if kind == "metric" and value not in {item.get("metric_ref") for item in metric_items}:
            issues.append(
                ValidationIssue(
                    code="invalid_order_by_metric",
                    path=f"grouping.order_by[{idx}].by",
                    message=f"order_by metric '{value}' is invalid",
                )
            )
            continue
        normalized_order.append({"by": by, "dir": direction})
    plan["grouping"]["order_by"] = normalized_order

    if _plan_is_empty(plan):
        issues.append(
            ValidationIssue(
                code="empty_plan",
                path="selects",
                message="Plan produced no selectable columns, metrics, or filters",
            )
        )

    if extra_issues:
        for item in extra_issues:
            if not isinstance(item, Mapping):
                continue
            code = str(item.get("code") or "validation_error").strip() or "validation_error"
            path = str(item.get("path") or "").strip()
            message = str(item.get("message") or code).strip() or code
            issues.append(ValidationIssue(code=code, path=path, message=message))

    return ValidationResult(
        plan_json=plan,
        is_valid=len(issues) == 0,
        issues=[issue.to_dict() for issue in issues],
        repairs_applied=repairs,
    )


def _normalize_plan(plan_json: Dict[str, Any]) -> Dict[str, Any]:
    src = dict(plan_json or {})
    selects = src.get("selects") if isinstance(src.get("selects"), dict) else {}
    grouping = src.get("grouping") if isinstance(src.get("grouping"), dict) else {}
    out = {
        "schema_version": 2,
        "trace_id": str(src.get("trace_id") or ""),
        "workspace_id": str(src.get("workspace_id") or ""),
        "vertical_norm": str(src.get("vertical_norm") or "generic").strip().lower() or "generic",
        "base_domain_id": _to_int(src.get("base_domain_id")),
        "domain_name": (str(src.get("domain_name") or "").strip() or None),
        "intent": str(src.get("intent") or "list").strip().lower() or "list",
        "selects": {
            "dimensions": [dict(item) for item in list(selects.get("dimensions") or []) if isinstance(item, dict)],
            "metrics": [dict(item) for item in list(selects.get("metrics") or []) if isinstance(item, dict)],
        },
        "filters": [dict(item) for item in list(src.get("filters") or []) if isinstance(item, dict)],
        "time": dict(src.get("time") or {}) if isinstance(src.get("time"), dict) else {},
        "grouping": {
            "group_by": [str(item) for item in list(grouping.get("group_by") or []) if str(item).strip()],
            "limit": _to_int(grouping.get("limit")),
            "order_by": [dict(item) for item in list(grouping.get("order_by") or []) if isinstance(item, dict)],
        },
    }
    debug = src.get("debug")
    out["debug"] = dict(debug) if isinstance(debug, dict) else None
    return out


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _norm_metric_ref(value: Any) -> str:
    ref = str(value or "").strip().lower()
    if ref.startswith(("domain_metric:", "user_metric:", "overlay:")):
        return ref
    return ref


def _norm_metric_id(row: Mapping[str, Any]) -> str:
    value = row.get("metric_id")
    if value is None:
        value = row.get("id")
    return _norm_key(value)


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _split_order_by(value: str) -> Tuple[str, str]:
    token = str(value or "").strip().lower()
    if token.startswith("dimension:"):
        return "dimension", token.split(":", 1)[1].strip()
    if token.startswith("metric:"):
        return "metric", token.split(":", 1)[1].strip()
    return "", token


def _column_name_from_key(value: str) -> str:
    token = _norm_key(value)
    if token == "":
        return ""
    if "." in token:
        return token.split(".", 1)[1].strip()
    return token


def _unique_allowed_key_by_column_name(allowed_keys: Sequence[str]) -> Dict[str, str]:
    counts: Dict[str, int] = {}
    first: Dict[str, str] = {}
    for raw in list(allowed_keys or []):
        key = _norm_key(raw)
        if key == "":
            continue
        column_name = _column_name_from_key(key)
        if column_name == "":
            continue
        counts[column_name] = int(counts.get(column_name) or 0) + 1
        if column_name not in first:
            first[column_name] = key
    return {column_name: key for column_name, key in first.items() if int(counts.get(column_name) or 0) == 1}


def _repair_column_key_by_name(
    *,
    key: str,
    allowed_keys: set[str],
    unique_by_column_name: Mapping[str, str],
) -> str:
    token = _norm_key(key)
    if token in allowed_keys:
        return token
    column_name = _column_name_from_key(token)
    if column_name == "":
        return token
    candidate = _norm_key(unique_by_column_name.get(column_name))
    if candidate and candidate in allowed_keys:
        return candidate
    return token


def _is_overlong_filter_value(*, op: str, value: Any) -> bool:
    op_norm = str(op or "").strip().lower()
    if op_norm in {"in", "not_in"} and isinstance(value, list) and len(value) > 1:
        return any(isinstance(item, str) and len(item) > 80 for item in value)
    return isinstance(value, str) and len(value) > 80


def _is_self_referential_filter_value(*, column_key: str, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return _norm_key(value) == _norm_key(column_key)


def _contains_column_token_value(*, op: str, value: Any) -> bool:
    op_norm = str(op or "").strip().lower()
    candidates: List[Any]
    if op_norm in {"in", "not_in", "between"} and isinstance(value, list):
        candidates = list(value)
    else:
        candidates = [value]
    for item in candidates:
        if not isinstance(item, str):
            continue
        token = _norm_key(item)
        if token and _COLUMN_TOKEN_RE.match(token):
            return True
    return False


def _is_missing_filter_value(*, op: str, item: Mapping[str, Any]) -> bool:
    op_norm = str(op or "").strip().lower()
    if op_norm in {"is_null", "is_not_null", "exists", "not_exists"}:
        return False
    if op_norm in {"in", "not_in", "between"}:
        values = item.get("values")
        if isinstance(values, list) and len(values) > 0:
            return False
        value = item.get("value")
        if value is None:
            return True
        if isinstance(value, str) and value.strip() == "":
            return True
        return False
    value = item.get("value")
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _plan_is_empty(plan: Mapping[str, Any]) -> bool:
    selects = plan.get("selects") if isinstance(plan.get("selects"), dict) else {}
    dimensions = list(selects.get("dimensions") or [])
    metrics = list(selects.get("metrics") or [])
    filters = list(plan.get("filters") or [])
    return len(dimensions) == 0 and len(metrics) == 0 and len(filters) == 0


__all__ = ["ValidationResult", "validate_and_repair_plan_v2"]
