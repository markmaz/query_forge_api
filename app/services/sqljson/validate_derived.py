from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from app.exceptions.forge_error import ForgeError
from app.services.domain_resolver import DomainPlan

_WT_COLUMN_KEY_RE = re.compile(r"^wt(?P<wt>\d+)\.(?P<col>[A-Za-z_][A-Za-z0-9_]*)$")
_COLUMN_REF_RE = re.compile(r"^column:(?P<inner>.+)$", re.IGNORECASE)
_VALID_METRIC_FNS = {"count", "count_distinct", "sum", "avg", "min", "max"}
_NON_NUMERIC_DATA_TYPE_MARKERS = (
    "char",
    "text",
    "string",
    "json",
    "bool",
    "date",
    "time",
    "binary",
)
_NON_NUMERIC_NAME_MARKERS = ("_id", "id_", " id", "code", "_code")
INT_PARSE_ERRORS = (TypeError, ValueError)


@dataclass(frozen=True)
class DerivedValidationIssue:
    code: str
    path: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


def validate_and_normalize_derived_sqljson(
    q: Dict[str, Any],
    *,
    plan: Optional[DomainPlan] = None,
    column_catalog: Optional[Mapping[Tuple[int, str], Mapping[str, Any]]] = None,
    strict: bool = False,
) -> tuple[Dict[str, Any], list[Dict[str, str]], Dict[str, Any]]:
    """
    Normalize planner-style derived metric payloads into the legacy sqlJson shape.

    Returns: (normalized_query, issues, meta)
      - issues is a stable-coded list suitable for ForgeError.details.
      - meta contains derived_registry keyed by metric name.
    """

    src = copy.deepcopy(q or {})
    issues: list[DerivedValidationIssue] = []
    norm = copy.deepcopy(src)
    derived_registry: Dict[str, Dict[str, Any]] = {}

    provided_derived = norm.get("derived_metrics")
    if provided_derived is None and isinstance(norm.get("derivedMetrics"), list):
        provided_derived = norm.get("derivedMetrics")

    if provided_derived is not None:
        if not isinstance(provided_derived, list):
            issues.append(
                DerivedValidationIssue(
                    code="invalid_derived_metrics",
                    path="derived_metrics",
                    message="derived_metrics must be a list",
                )
            )
        else:
            for idx, raw in enumerate(provided_derived):
                path = f"derived_metrics[{idx}]"
                dm = _normalize_derived_metric(
                    raw,
                    path=path,
                    plan=plan,
                    column_catalog=column_catalog,
                    issues=issues,
                )
                if dm is None:
                    continue
                name = str(dm.get("name") or "").strip()
                if name in derived_registry:
                    issues.append(
                        DerivedValidationIssue(
                            code="duplicate_metric_name",
                            path=f"{path}.name",
                            message=f"Duplicate derived metric name: {name}",
                        )
                    )
                    continue
                derived_registry[name] = dm

    aggs = norm.get("aggs")
    if aggs is None:
        aggs = {}
    if not isinstance(aggs, dict):
        issues.append(
            DerivedValidationIssue(code="invalid_aggs_shape", path="aggs", message="aggs must be an object")
        )
        aggs = {}
    aggs.setdefault("enabled", False)
    aggs.setdefault("metrics", [])
    aggs.setdefault("groupBy", [])

    if not isinstance(aggs.get("metrics"), list):
        issues.append(
            DerivedValidationIssue(
                code="invalid_aggs_metrics",
                path="aggs.metrics",
                message="aggs.metrics must be a list",
            )
        )
        aggs["metrics"] = []
    if not isinstance(aggs.get("groupBy"), list):
        issues.append(
            DerivedValidationIssue(
                code="invalid_aggs_group_by",
                path="aggs.groupBy",
                message="aggs.groupBy must be a list",
            )
        )
        aggs["groupBy"] = []

    norm_metrics = _normalize_existing_expr_metrics(
        aggs.get("metrics") or [],
        plan=plan,
        column_catalog=column_catalog,
        issues=issues,
        derived_registry=derived_registry,
    )
    aggs["metrics"] = norm_metrics

    selects = norm.get("selects")
    if selects is not None:
        if not isinstance(selects, dict):
            issues.append(
                DerivedValidationIssue(code="invalid_selects", path="selects", message="selects must be an object")
            )
        else:
            _apply_selects_shape(
                norm=norm,
                aggs=aggs,
                selects=selects,
                derived_registry=derived_registry,
                plan=plan,
                column_catalog=column_catalog,
                issues=issues,
            )
        norm.pop("selects", None)

    if derived_registry:
        norm["derived_metrics"] = list(derived_registry.values())

    if aggs.get("groupBy") or aggs.get("metrics"):
        aggs["enabled"] = True
    norm["aggs"] = aggs

    issue_dicts = [issue.to_dict() for issue in issues]
    if strict and issue_dicts:
        first = issue_dicts[0]
        raise ForgeError(
            f"derived_validation_failed: {first['code']} at {first['path']}",
            status_code=400,
            details={"issues": issue_dicts},
        )

    return norm, issue_dicts, {"derived_registry": derived_registry}


def _normalize_existing_expr_metrics(
    raw_metrics: Sequence[Any],
    *,
    plan: Optional[DomainPlan],
    column_catalog: Optional[Mapping[Tuple[int, str], Mapping[str, Any]]],
    issues: list[DerivedValidationIssue],
    derived_registry: Dict[str, Dict[str, Any]],
) -> list[Dict[str, Any]]:
    out: list[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_metrics):
        path = f"aggs.metrics[{idx}]"
        if not isinstance(raw, dict):
            out.append(raw)
            continue
        fn = str(raw.get("fn") or "").strip().lower()
        if fn != "expr":
            out.append(raw)
            continue
        expr = raw.get("expr")
        if not isinstance(expr, dict):
            issues.append(
                DerivedValidationIssue(
                    code="invalid_expr_metric",
                    path=f"{path}.expr",
                    message="expr metric requires expr payload",
                )
            )
            out.append(raw)
            continue
        kind = str(expr.get("kind") or "").strip().lower()
        if kind != "ratio":
            issues.append(
                DerivedValidationIssue(
                    code="unsupported_derived_kind",
                    path=f"{path}.expr.kind",
                    message="Only ratio derived metrics are supported",
                )
            )
            out.append(raw)
            continue
        name = str(expr.get("name") or raw.get("id") or f"metric_{idx+1}").strip()
        normalized = _normalize_derived_metric(
            {"kind": "ratio", "name": name, **expr},
            path=f"{path}.expr",
            plan=plan,
            column_catalog=column_catalog,
            issues=issues,
        )
        if normalized is None:
            out.append(raw)
            continue
        derived_registry.setdefault(name, normalized)
        out.append(
            {
                **raw,
                "fn": "expr",
                "field": None,
                "expr": _derived_metric_to_expr(normalized),
            }
        )
    return out


def _apply_selects_shape(
    *,
    norm: Dict[str, Any],
    aggs: Dict[str, Any],
    selects: Dict[str, Any],
    derived_registry: Dict[str, Dict[str, Any]],
    plan: Optional[DomainPlan],
    column_catalog: Optional[Mapping[Tuple[int, str], Mapping[str, Any]]],
    issues: list[DerivedValidationIssue],
) -> None:
    dimensions = selects.get("dimensions") or []
    metrics = selects.get("metrics") or []

    if not isinstance(dimensions, list):
        issues.append(
            DerivedValidationIssue(
                code="invalid_dimensions",
                path="selects.dimensions",
                message="selects.dimensions must be a list",
            )
        )
        dimensions = []
    if not isinstance(metrics, list):
        issues.append(
            DerivedValidationIssue(
                code="invalid_metrics",
                path="selects.metrics",
                message="selects.metrics must be a list",
            )
        )
        metrics = []

    norm_columns = norm.get("columns") if isinstance(norm.get("columns"), list) else []
    norm_group_by = aggs.get("groupBy") if isinstance(aggs.get("groupBy"), list) else []

    for idx, dim in enumerate(dimensions):
        col = _parse_column_key(
            dim,
            path=f"selects.dimensions[{idx}]",
            plan=plan,
            column_catalog=column_catalog,
            issues=issues,
        )
        if col is None:
            continue
        norm_columns.append(col)
        norm_group_by.append(col)

    norm["columns"] = _dedupe_col_refs(norm_columns)
    aggs["groupBy"] = _dedupe_col_refs(norm_group_by)

    norm_metrics = aggs.get("metrics") if isinstance(aggs.get("metrics"), list) else []
    for idx, raw_metric in enumerate(metrics):
        path = f"selects.metrics[{idx}]"
        if not isinstance(raw_metric, dict):
            issues.append(
                DerivedValidationIssue(
                    code="invalid_metric_entry",
                    path=path,
                    message="selects metric must be an object",
                )
            )
            continue
        metric_ref = raw_metric.get("metricRef")
        if metric_ref is None:
            metric_ref = raw_metric.get("metric_ref")
        label = raw_metric.get("label")
        if label is not None and not isinstance(label, str):
            label = None
        metric_id = raw_metric.get("id")
        if metric_id is None or not isinstance(metric_id, str):
            metric_id = f"m{idx+1}"

        if not isinstance(metric_ref, str) or not metric_ref.strip():
            issues.append(
                DerivedValidationIssue(
                    code="missing_metric_ref",
                    path=f"{path}.metricRef",
                    message="metricRef is required",
                )
            )
            continue

        ref_text = metric_ref.strip()
        ref_lower = ref_text.lower()
        if ref_lower.startswith("derived:"):
            dm_name = ref_text.split(":", 1)[1].strip()
            dm = derived_registry.get(dm_name)
            if dm is None:
                issues.append(
                    DerivedValidationIssue(
                        code="unknown_derived_metric_ref",
                        path=f"{path}.metricRef",
                        message=f"Unknown derived metric: {dm_name}",
                    )
                )
                continue
            norm_metrics.append(
                {
                    "id": metric_id,
                    "fn": "expr",
                    "field": None,
                    "label": (label or dm.get("label") or dm_name),
                    "expr": _derived_metric_to_expr(dm),
                }
            )
            continue

        parsed_col = _parse_column_key(
            ref_text,
            path=f"{path}.metricRef",
            plan=plan,
            column_catalog=column_catalog,
            issues=issues,
        )
        if parsed_col is None:
            continue
        fn = _normalize_metric_fn(raw_metric.get("agg") or raw_metric.get("fn") or "count")
        if fn is None:
            issues.append(
                DerivedValidationIssue(
                    code="invalid_metric_fn",
                    path=f"{path}.agg",
                    message="Invalid metric aggregation function",
                )
            )
            continue
        _validate_metric_type(
            fn=fn,
            field=parsed_col,
            path=f"{path}.metricRef",
            column_catalog=column_catalog,
            issues=issues,
        )
        norm_metrics.append(
            {
                "id": metric_id,
                "fn": fn,
                "field": parsed_col,
                "label": label or fn,
            }
        )

    aggs["metrics"] = norm_metrics


def _normalize_derived_metric(
    raw: Any,
    *,
    path: str,
    plan: Optional[DomainPlan],
    column_catalog: Optional[Mapping[Tuple[int, str], Mapping[str, Any]]],
    issues: list[DerivedValidationIssue],
) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        issues.append(
            DerivedValidationIssue(code="invalid_derived_metric", path=path, message="Derived metric must be an object")
        )
        return None
    kind = str(raw.get("kind") or "").strip().lower()
    if kind != "ratio":
        issues.append(
            DerivedValidationIssue(
                code="unsupported_derived_kind",
                path=f"{path}.kind",
                message="Only kind=ratio is supported",
            )
        )
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        issues.append(
            DerivedValidationIssue(
                code="missing_metric_name",
                path=f"{path}.name",
                message="Derived metric name is required",
            )
        )
        return None

    numerator = _normalize_ratio_side(
        raw.get("numerator"),
        path=f"{path}.numerator",
        plan=plan,
        column_catalog=column_catalog,
        issues=issues,
    )
    denominator = _normalize_ratio_side(
        raw.get("denominator"),
        path=f"{path}.denominator",
        plan=plan,
        column_catalog=column_catalog,
        issues=issues,
    )

    if numerator is None or denominator is None:
        return None

    safe_divide_raw = raw.get("safeDivide", raw.get("safe_divide", True))
    safe_divide = bool(safe_divide_raw)
    multiply_by = raw.get("multiplyBy", raw.get("multiply_by"))
    if multiply_by is not None:
        if not isinstance(multiply_by, (int, float)):
            issues.append(
                DerivedValidationIssue(
                    code="invalid_multiply_by",
                    path=f"{path}.multiplyBy",
                    message="multiplyBy must be numeric or null",
                )
            )
            multiply_by = None
        else:
            multiply_by = float(multiply_by)

    return {
        "kind": "ratio",
        "name": name,
        "label": raw.get("label") if isinstance(raw.get("label"), str) else None,
        "numerator": numerator,
        "denominator": denominator,
        "safe_divide": safe_divide,
        "multiply_by": multiply_by,
    }


def _normalize_ratio_side(
    raw: Any,
    *,
    path: str,
    plan: Optional[DomainPlan],
    column_catalog: Optional[Mapping[Tuple[int, str], Mapping[str, Any]]],
    issues: list[DerivedValidationIssue],
) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        code = "missing_denominator" if path.endswith(".denominator") else "missing_numerator"
        issues.append(DerivedValidationIssue(code=code, path=path, message=f"{path.split('.')[-1]} is required"))
        return None

    fn = _normalize_metric_fn(raw.get("agg") or raw.get("fn"))
    if fn is None:
        issues.append(
            DerivedValidationIssue(
                code="invalid_agg_fn",
                path=f"{path}.agg",
                message="Invalid aggregate function for ratio side",
            )
        )
        return None

    field = _parse_column_key(
        raw.get("columnKey", raw.get("column_key", raw.get("field"))),
        path=f"{path}.columnKey",
        plan=plan,
        column_catalog=column_catalog,
        issues=issues,
    )
    if field is None:
        return None

    _validate_metric_type(fn=fn, field=field, path=f"{path}.columnKey", column_catalog=column_catalog, issues=issues)

    filters = raw.get("filters")
    if filters is not None and not isinstance(filters, dict):
        issues.append(
            DerivedValidationIssue(
                code="invalid_ratio_filters",
                path=f"{path}.filters",
                message="ratio side filters must be an object or null",
            )
        )
        filters = None

    return {"fn": fn, "field": field, "filters": filters}


def _parse_column_key(
    raw: Any,
    *,
    path: str,
    plan: Optional[DomainPlan],
    column_catalog: Optional[Mapping[Tuple[int, str], Mapping[str, Any]]],
    issues: list[DerivedValidationIssue],
) -> Optional[Dict[str, Any]]:
    if raw is None:
        issues.append(DerivedValidationIssue(code="missing_column_key", path=path, message="columnKey is required"))
        return None

    if isinstance(raw, dict):
        if "columnKey" in raw or "column_key" in raw:
            return _parse_column_key(
                raw.get("columnKey", raw.get("column_key")),
                path=path,
                plan=plan,
                column_catalog=column_catalog,
                issues=issues,
            )
        column_name = raw.get("columnName")
        if not isinstance(column_name, str) or not column_name.strip():
            issues.append(
                DerivedValidationIssue(
                    code="unknown_column_key",
                    path=path,
                    message="columnName is required",
                )
            )
            return None
        wt_id = raw.get("workspaceTableId")
        mid = raw.get("modelColumnId")
        expr_id = raw.get("exprId")
        if wt_id is not None:
            try:
                wt_id = int(wt_id)
            except INT_PARSE_ERRORS:
                issues.append(
                    DerivedValidationIssue(
                        code="unknown_column_key",
                        path=path,
                        message=f"Invalid workspaceTableId for {column_name}",
                    )
                )
                return None
        if mid is not None:
            try:
                mid = int(mid)
            except INT_PARSE_ERRORS:
                mid = None
        normalized = {
            "workspaceTableId": wt_id,
            "modelColumnId": mid,
            "columnName": column_name.strip(),
            "exprId": expr_id if isinstance(expr_id, str) else None,
        }
        _validate_column_existence(
            normalized,
            path=path,
            plan=plan,
            column_catalog=column_catalog,
            issues=issues,
        )
        return normalized

    if not isinstance(raw, str):
        issues.append(
            DerivedValidationIssue(
                code="unknown_column_key",
                path=path,
                message="columnKey must be a string or object",
            )
        )
        return None

    text = raw.strip()
    if not text:
        issues.append(DerivedValidationIssue(code="unknown_column_key", path=path, message="columnKey is empty"))
        return None

    ref_match = _COLUMN_REF_RE.match(text)
    if ref_match:
        text = ref_match.group("inner").strip()

    wt_match = _WT_COLUMN_KEY_RE.match(text)
    if wt_match:
        wt_id = int(wt_match.group("wt"))
        col_name = wt_match.group("col")
        normalized = {
            "workspaceTableId": wt_id,
            "modelColumnId": None,
            "columnName": col_name,
            "exprId": None,
        }
        _validate_column_existence(
            normalized,
            path=path,
            plan=plan,
            column_catalog=column_catalog,
            issues=issues,
        )
        return normalized

    if "." in text:
        issues.append(
            DerivedValidationIssue(
                code="unknown_column_key",
                path=path,
                message=f"Unsupported columnKey format: {text}",
            )
        )
        return None

    normalized = {
        "workspaceTableId": None,
        "modelColumnId": None,
        "columnName": text,
        "exprId": None,
    }
    _validate_column_existence(
        normalized,
        path=path,
        plan=plan,
        column_catalog=column_catalog,
        issues=issues,
    )
    return normalized


def _normalize_metric_fn(raw: Any) -> Optional[str]:
    fn = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if fn == "countdistinct":
        fn = "count_distinct"
    if fn not in _VALID_METRIC_FNS:
        return None
    return fn


def _validate_column_existence(
    col: Dict[str, Any],
    *,
    path: str,
    plan: Optional[DomainPlan],
    column_catalog: Optional[Mapping[Tuple[int, str], Mapping[str, Any]]],
    issues: list[DerivedValidationIssue],
) -> None:
    wt_id = col.get("workspaceTableId")
    col_name = str(col.get("columnName") or "").strip()
    if not col_name:
        return

    if wt_id is not None and plan is not None:
        plan_table_ids = {int(t.workspace_table_id) for t in (plan.tables or [])}
        if int(wt_id) not in plan_table_ids:
            issues.append(
                DerivedValidationIssue(
                    code="unknown_column_key",
                    path=path,
                    message=f"workspaceTableId {wt_id} is not part of the selected domain",
                )
            )
            return

    if wt_id is not None and column_catalog:
        key = (int(wt_id), col_name.lower())
        if key not in column_catalog:
            issues.append(
                DerivedValidationIssue(
                    code="unknown_column_key",
                    path=path,
                    message=f"Unknown columnKey wt{wt_id}.{col_name}",
                )
            )


def _validate_metric_type(
    *,
    fn: str,
    field: Dict[str, Any],
    path: str,
    column_catalog: Optional[Mapping[Tuple[int, str], Mapping[str, Any]]],
    issues: list[DerivedValidationIssue],
) -> None:
    if fn not in {"sum", "avg", "min", "max"}:
        return
    col_name = str(field.get("columnName") or "").strip()
    if not col_name:
        return

    wt_id = field.get("workspaceTableId")
    catalog_data_type = ""
    if wt_id is not None and column_catalog:
        payload = column_catalog.get((int(wt_id), col_name.lower())) or {}
        catalog_data_type = str(payload.get("data_type") or "").strip().lower()
    non_numeric_type = any(token in catalog_data_type for token in _NON_NUMERIC_DATA_TYPE_MARKERS)
    name_lower = col_name.lower()
    looks_identifier = (
        name_lower.endswith("id")
        or name_lower.startswith("k_")
        or any(marker in name_lower for marker in _NON_NUMERIC_NAME_MARKERS)
    )
    if non_numeric_type or looks_identifier:
        issues.append(
            DerivedValidationIssue(
                code="invalid_metric_type",
                path=path,
                message=f"{fn} is invalid for non-numeric identifier-like column {col_name}",
            )
        )


def _dedupe_col_refs(items: Iterable[Any]) -> list[Dict[str, Any]]:
    out: list[Dict[str, Any]] = []
    seen: set[tuple] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (
            item.get("workspaceTableId"),
            item.get("modelColumnId"),
            item.get("columnName"),
            item.get("exprId"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _derived_metric_to_expr(dm: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind": "ratio",
        "name": dm.get("name"),
        "numerator": {
            "fn": dm["numerator"]["fn"],
            "field": dm["numerator"]["field"],
            "filters": dm["numerator"].get("filters"),
        },
        "denominator": {
            "fn": dm["denominator"]["fn"],
            "field": dm["denominator"]["field"],
            "filters": dm["denominator"].get("filters"),
        },
        "safe_divide": bool(dm.get("safe_divide", True)),
        "multiply_by": dm.get("multiply_by"),
    }
