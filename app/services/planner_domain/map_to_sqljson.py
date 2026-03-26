from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.models.query.ai_suggest import AddFilterEdit, AddGroupByEdit, AddSelectEdit, AddSortEdit, SetDomainEdit, SqlColumnKey
from app.services.sqljson_apply_service import apply_edits


def map_plan_v2_to_sqljson(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str,
) -> Dict[str, Any]:
    time_block = dict(plan_json.get("time") or {}) if isinstance(plan_json.get("time"), dict) else {}
    custom_time_column_key = (
        _norm_key(time_block.get("time_column_key"))
        if _should_apply_custom_time_filter(time_block)
        else ""
    )
    dim_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in list(capabilities.get("dimensions") or []) + list(capabilities.get("time_columns") or [])
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }
    filter_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in list(capabilities.get("filter_columns") or []) + list(capabilities.get("dimensions") or []) + list(capabilities.get("time_columns") or [])
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }
    domain_metric_lookup = {
        _norm_key(row.get("metric_key")): dict(row)
        for row in list(capabilities.get("domain_metrics") or [])
        if isinstance(row, dict) and _norm_key(row.get("metric_key"))
    }
    user_metric_lookup = {
        _norm_key(row.get("metric_id") or row.get("id")): dict(row)
        for row in list(capabilities.get("user_metrics") or [])
        if isinstance(row, dict) and _norm_key(row.get("metric_id") or row.get("id"))
    }
    overlay_lookup = {
        _norm_key(row.get("overlay_key")): dict(row)
        for row in list(capabilities.get("overlay_metrics") or [])
        if isinstance(row, dict) and _norm_key(row.get("overlay_key"))
    }

    base_domain_id = int(plan_json.get("base_domain_id") or 0)
    plan_intent = _norm_key(plan_json.get("intent"))
    plan_metrics = list((plan_json.get("selects") or {}).get("metrics") or [])
    is_list_without_metrics = plan_intent == "list" and len(plan_metrics) == 0
    edits: List[Any] = [SetDomainEdit(op="setDomain", domainId=base_domain_id)]
    selected_metric_refs: List[str] = []

    for item in list((plan_json.get("selects") or {}).get("dimensions") or []):
        key = _norm_key(item.get("column_key"))
        col = _to_sql_column_key(dim_lookup.get(key))
        if col is None:
            continue
        edits.append(AddSelectEdit(op="addSelect", col=col, alias=item.get("label")))

    for item in list(plan_json.get("filters") or []):
        if custom_time_column_key and _is_relative_time_placeholder_filter(
            item,
            time_column_key=custom_time_column_key,
        ):
            continue
        key = _norm_key(item.get("column_key"))
        col = _to_sql_column_key(filter_lookup.get(key))
        if col is None:
            continue
        op = _norm_filter_op(item.get("op"))
        if op is None:
            continue
        edits.append(
            AddFilterEdit(
                op="addFilter",
                col=col,
                operator=op,
                value=_filter_value_for_op(item=item, op=op),
            )
        )

    if not is_list_without_metrics:
        group_by_keys = [_norm_key(item) for item in list((plan_json.get("grouping") or {}).get("group_by") or [])]
        for key in group_by_keys:
            col = _to_sql_column_key(dim_lookup.get(key))
            if col is None:
                continue
            edits.append(AddGroupByEdit(op="addGroupBy", col=col))

    sql_json = apply_edits(None, edits, prompt=prompt)
    aggs = sql_json.get("aggs")
    if not isinstance(aggs, dict):
        aggs = {"enabled": False, "groupBy": [], "metrics": []}
        sql_json["aggs"] = aggs
    if not isinstance(aggs.get("metrics"), list):
        aggs["metrics"] = []

    metrics = plan_metrics
    for idx, metric in enumerate(metrics):
        metric_ref = _norm_key(metric.get("metric_ref"))
        if metric_ref == "":
            continue
        selected_metric_refs.append(metric_ref)
        kind, key = _split_metric_ref(metric_ref)
        label = str(metric.get("label") or "").strip() or None
        if kind == "domain_metric":
            domain_metric = domain_metric_lookup.get(key)
            node = _domain_metric_to_sql_metric(metric_key=key, metric=domain_metric, dim_lookup=dim_lookup, label=label)
            if node is not None:
                aggs["metrics"].append(node)
                aggs["enabled"] = True
            continue
        if kind == "user_metric":
            user_metric = user_metric_lookup.get(key)
            node = _user_metric_to_sql_metric(metric_id=key, metric=user_metric, label=label, idx=idx)
            if node is not None:
                aggs["metrics"].append(node)
                aggs["enabled"] = True
            continue
        if kind == "overlay":
            overlay = overlay_lookup.get(key)
            node = _overlay_metric_to_sql_metric(overlay_key=key, metric=overlay, label=label)
            if node is not None:
                aggs["metrics"].append(node)
                aggs["enabled"] = True
            continue

    if is_list_without_metrics:
        aggs["enabled"] = False
        aggs["metrics"] = []
        aggs["groupBy"] = []

    if time_block:
        sql_json.setdefault("meta", {})
        if isinstance(sql_json.get("meta"), dict):
            sql_json["meta"]["time"] = time_block
    if _should_apply_custom_time_filter(time_block):
        time_col = _to_sql_column_key(dim_lookup.get(_norm_key(time_block.get("time_column_key"))))
        start_date = time_block.get("start_date")
        end_date = time_block.get("end_date")
        if time_col is not None and start_date and end_date:
            time_filter_sql = apply_edits(
                sql_json,
                [AddFilterEdit(op="addFilter", col=time_col, operator="between", value=[start_date, end_date])],
                prompt=prompt,
            )
            sql_json = time_filter_sql

    sql_json = _apply_birth_month_date_part_filter(
        sql_json=sql_json,
        capabilities=capabilities,
        prompt=prompt,
    )

    sql_json = _apply_plan_order_by_sorting(sql_json=sql_json, plan_json=plan_json, dim_lookup=dim_lookup, prompt=prompt)
    _apply_default_sorting(sql_json)

    sql_json.setdefault("meta", {})
    if isinstance(sql_json.get("meta"), dict):
        sql_json["meta"]["tool"] = "planner_domain_v2"
        sql_json["meta"]["plan_v2_metric_refs"] = selected_metric_refs

    return sql_json


def _domain_metric_to_sql_metric(
    *,
    metric_key: str,
    metric: Optional[Mapping[str, Any]],
    dim_lookup: Mapping[str, Dict[str, Any]],
    label: Optional[str],
) -> Optional[Dict[str, Any]]:
    data = dict(metric or {})
    sql_metric = data.get("sql_metric")
    if isinstance(sql_metric, Mapping):
        out = dict(sql_metric)
        out.setdefault("id", f"domain_metric:{metric_key}")
        if label is not None:
            out["label"] = label
        else:
            out.setdefault("label", str(data.get("label") or metric_key))
        out["metric_ref"] = f"domain_metric:{metric_key}"
        return out

    agg = str(data.get("agg") or "").strip().lower()
    if agg not in {"count", "count_distinct", "sum", "avg", "min", "max"}:
        agg = "count"

    field = None
    col_key = _norm_key(data.get("column_key"))
    if col_key:
        field = _to_sql_column_key(dim_lookup.get(col_key))
    if field is None:
        field = _infer_metric_field_from_key(metric_key=metric_key, metric=data, dim_lookup=dim_lookup)

    # Domain profiles often define count metrics without an explicit column_key.
    # Prefer a stable identifier-like column instead of COUNT(*) when possible.
    if field is None and agg in {"count", "count_distinct"}:
        field = _pick_fallback_metric_field(metric_key=metric_key, dim_lookup=dim_lookup)

    field_payload = field.model_dump(mode="json", exclude_none=False) if field is not None else None

    return {
        "id": f"domain_metric:{metric_key}",
        "fn": agg,
        "field": field_payload,
        "label": label or str(data.get("label") or metric_key),
        "metric_ref": f"domain_metric:{metric_key}",
    }


def _infer_metric_field_from_key(
    *,
    metric_key: str,
    metric: Mapping[str, Any],
    dim_lookup: Mapping[str, Dict[str, Any]],
) -> Optional[SqlColumnKey]:
    key_norm = _norm_key(metric_key)
    label_norm = _norm_key(metric.get("label"))
    if key_norm == "" and label_norm == "":
        return None

    def _score_row(row: Mapping[str, Any]) -> int:
        col_name = _norm_key(row.get("column_name"))
        col_key = _norm_key(row.get("column_key"))
        score = 0
        if col_name == key_norm:
            score += 200
        if col_key.endswith(f".{key_norm}") or col_key == key_norm:
            score += 160
        if key_norm and key_norm in col_name:
            score += 80
        if label_norm and label_norm in col_name:
            score += 40
        if _looks_numeric_column(row):
            score += 20
        return score

    best_row: Optional[Mapping[str, Any]] = None
    best_score = -1
    for row in dim_lookup.values():
        if not isinstance(row, Mapping):
            continue
        score = _score_row(row)
        if score <= 0:
            continue
        if score > best_score:
            best_score = score
            best_row = row
    return _to_sql_column_key(best_row)


def _looks_numeric_column(row: Mapping[str, Any]) -> bool:
    data_type = _norm_key(row.get("data_type"))
    col_name = _norm_key(row.get("column_name"))
    if any(token in data_type for token in ("int", "number", "float", "double", "decimal", "numeric")):
        return True
    return any(token in col_name for token in ("amount", "revenue", "cost", "price", "qty", "quantity", "count"))


def _pick_fallback_metric_field(
    *,
    metric_key: str,
    dim_lookup: Mapping[str, Dict[str, Any]],
) -> Optional[SqlColumnKey]:
    rows = [dict(row) for row in dim_lookup.values() if isinstance(row, Mapping)]
    if not rows:
        return None

    metric_key_norm = _norm_key(metric_key)

    student_markers = ("student_unique_id", "k_student_xyear", "k_student", "student_id")
    staff_markers = ("staff_unique_id", "k_staff", "staff_id")
    school_markers = ("school_unique_id", "k_school", "school_id", "school_number")
    generic_id_markers = ("_id", " id", "id_")

    preferred_markers: Tuple[str, ...]
    if any(token in metric_key_norm for token in ("enrollment", "student")):
        preferred_markers = student_markers + school_markers + staff_markers
    elif any(token in metric_key_norm for token in ("staff", "teacher", "principal")):
        preferred_markers = staff_markers + school_markers + student_markers
    elif "school" in metric_key_norm:
        preferred_markers = school_markers + student_markers + staff_markers
    else:
        preferred_markers = student_markers + staff_markers + school_markers

    by_name = []
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if col_name == "":
            continue
        by_name.append((col_name, row))

    for marker in preferred_markers:
        for col_name, row in by_name:
            if marker in col_name:
                candidate = _to_sql_column_key(row)
                if candidate is not None:
                    return candidate

    for col_name, row in by_name:
        if col_name == "id" or col_name.endswith(generic_id_markers):
            candidate = _to_sql_column_key(row)
            if candidate is not None:
                return candidate

    for row in rows:
        candidate = _to_sql_column_key(row)
        if candidate is not None:
            return candidate
    return None


def _user_metric_to_sql_metric(
    *,
    metric_id: str,
    metric: Optional[Mapping[str, Any]],
    label: Optional[str],
    idx: int,
) -> Optional[Dict[str, Any]]:
    data = dict(metric or {})
    metric_node = data.get("sql_metric")
    if isinstance(metric_node, dict):
        out = dict(metric_node)
        out.setdefault("id", f"user_metric:{metric_id}")
        out.setdefault("label", label or str(data.get("label") or metric_id))
        out["metric_ref"] = f"user_metric:{metric_id}"
        return out
    return {
        "id": f"user_metric:{metric_id}",
        "fn": "user_metric",
        "field": None,
        "label": label or str(data.get("label") or f"user_metric_{idx+1}"),
        "metric_ref": f"user_metric:{metric_id}",
    }


def _overlay_metric_to_sql_metric(
    *,
    overlay_key: str,
    metric: Optional[Mapping[str, Any]],
    label: Optional[str],
) -> Optional[Dict[str, Any]]:
    data = dict(metric or {})
    return {
        "id": f"overlay:{overlay_key}",
        "fn": "overlay_metric",
        "overlay_key": overlay_key,
        "field": None,
        "label": label or str(data.get("label") or overlay_key),
        "metric_ref": f"overlay:{overlay_key}",
    }


def _to_sql_column_key(row: Optional[Mapping[str, Any]]) -> Optional[SqlColumnKey]:
    if not isinstance(row, Mapping):
        return None
    column_name = str(row.get("column_name") or "").strip()
    if column_name == "":
        return None
    return SqlColumnKey(
        modelColumnId=_to_int(row.get("model_column_id")),
        columnName=column_name,
        workspaceTableId=_to_int(row.get("workspace_table_id")),
        exprId=None,
        alias=None,
    )


def _apply_default_sorting(sql_json: Dict[str, Any]) -> None:
    sorting = sql_json.get("sorting")
    if isinstance(sorting, list) and len(sorting) > 0:
        return

    first_col = _first_output_column(sql_json.get("columns"))
    if first_col is None:
        sql_json["sorting"] = []
        return

    sql_json["sorting"] = [{"col": first_col, "dir": "asc"}]


def _apply_plan_order_by_sorting(
    *,
    sql_json: Dict[str, Any],
    plan_json: Mapping[str, Any],
    dim_lookup: Mapping[str, Dict[str, Any]],
    prompt: str,
) -> Dict[str, Any]:
    order_items = list((plan_json.get("grouping") or {}).get("order_by") or [])
    if not order_items:
        return sql_json

    sort_edits: List[Any] = []
    metric_sorts: List[Dict[str, Any]] = []
    for item in order_items:
        if not isinstance(item, Mapping):
            continue
        direction = str(item.get("dir") or "asc").strip().lower()
        if direction not in {"asc", "desc"}:
            direction = "asc"
        metric_ref = _order_by_metric_ref(item.get("by"))
        if metric_ref:
            metric_sorts.append({"metricRef": metric_ref, "dir": direction})
            continue
        key = _order_by_dimension_key(item.get("by"))
        if key == "":
            continue
        col = _to_sql_column_key(dim_lookup.get(key))
        if col is None:
            continue
        sort_edits.append(AddSortEdit(op="addSort", col=col, dir=direction))

    out = sql_json
    if sort_edits:
        out = apply_edits(out, sort_edits, prompt=prompt)

    if metric_sorts:
        sorting = list(out.get("sorting") or []) if isinstance(out.get("sorting"), list) else []
        seen = {
            (str(item.get("metricRef") or "").strip().lower(), str(item.get("dir") or "asc").strip().lower())
            for item in sorting
            if isinstance(item, Mapping) and str(item.get("metricRef") or "").strip()
        }
        for item in metric_sorts:
            key = (str(item.get("metricRef") or "").strip().lower(), str(item.get("dir") or "asc").strip().lower())
            if key in seen:
                continue
            seen.add(key)
            sorting.append(item)
        out["sorting"] = sorting
    return out


def _first_output_column(columns: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(columns, list) or len(columns) == 0:
        return None
    first = columns[0]
    if isinstance(first, dict):
        field = first.get("field")
        if isinstance(field, dict) and str(field.get("columnName") or "").strip():
            return dict(field)
        if str(first.get("columnName") or "").strip():
            return {
                "modelColumnId": _to_int(first.get("modelColumnId")),
                "columnName": str(first.get("columnName") or "").strip(),
                "workspaceTableId": _to_int(first.get("workspaceTableId")),
                "exprId": first.get("exprId"),
                "alias": first.get("alias"),
            }
    return None


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _split_metric_ref(value: str) -> Tuple[str, str]:
    token = _norm_key(value)
    if token.startswith("domain_metric:"):
        return "domain_metric", token.split(":", 1)[1].strip()
    if token.startswith("user_metric:"):
        return "user_metric", token.split(":", 1)[1].strip()
    if token.startswith("overlay:"):
        return "overlay", token.split(":", 1)[1].strip()
    return "", token


def _order_by_dimension_key(value: Any) -> str:
    token = _norm_key(value)
    if token.startswith("metric:"):
        return ""
    if token.startswith("dimension:"):
        return token.split(":", 1)[1].strip()
    return token


def _order_by_metric_ref(value: Any) -> str:
    token = _norm_key(value)
    if token.startswith("metric:"):
        return token.split(":", 1)[1].strip()
    return ""


def _norm_filter_op(value: Any) -> Optional[str]:
    token = str(value or "").strip().lower()
    mapping = {
        "=": "equals",
        "==": "equals",
        "eq": "equals",
        "equals": "equals",
        "!=": "not_equals",
        "<>": "not_equals",
        "ne": "not_equals",
        "not_equal": "not_equals",
        "not_equals": "not_equals",
        "in": "in",
        "not in": "not_in",
        "not_in": "not_in",
        "contains": "contains",
        "like": "contains",
        "starts_with": "starts_with",
        "startswith": "starts_with",
        "prefix": "starts_with",
        "gt": "gt",
        ">": "gt",
        "gte": "gte",
        ">=": "gte",
        "lt": "lt",
        "<": "lt",
        "lte": "lte",
        "<=": "lte",
        "between": "between",
        "exists": "is_not_null",
        "not_exists": "is_null",
        "is_null": "is_null",
        "is null": "is_null",
        "is_not_null": "is_not_null",
        "is not null": "is_not_null",
    }
    return mapping.get(token)


def _filter_value_for_op(*, item: Mapping[str, Any], op: str) -> Any:
    if op in {"is_null", "is_not_null"}:
        return None
    if op in {"in", "not_in", "between"} and isinstance(item.get("values"), list):
        return list(item.get("values") or [])
    return item.get("value")


def _is_relative_time_placeholder_filter(
    item: Mapping[str, Any],
    *,
    time_column_key: str,
) -> bool:
    if _norm_key(item.get("column_key")) != time_column_key:
        return False
    if _canonical_relative_time_token(item.get("value")) != "":
        return True
    values = item.get("values")
    if isinstance(values, list) and any(_canonical_relative_time_token(value) != "" for value in values):
        return True
    value = item.get("value")
    if isinstance(value, Mapping):
        if _canonical_relative_time_token(value.get("time_range")) != "":
            return True
        if _canonical_relative_time_token(value.get("time_period")) != "":
            return True
    return False


def _canonical_relative_time_token(value: Any) -> str:
    token = _norm_key(value).replace(" ", "_")
    aliases = {
        "this_month": "this_month",
        "current_month": "this_month",
        "last_month": "last_month",
        "previous_month": "last_month",
        "this_quarter": "this_quarter",
        "current_quarter": "this_quarter",
        "last_quarter": "last_quarter",
        "previous_quarter": "last_quarter",
        "fiscal_this_quarter": "fiscal_this_quarter",
        "fiscal_last_quarter": "fiscal_last_quarter",
        "this_year": "this_year",
        "current_year": "this_year",
        "last_year": "last_year",
        "previous_year": "last_year",
    }
    return aliases.get(token, "")


def _should_apply_custom_time_filter(time_block: Mapping[str, Any]) -> bool:
    time_range = _norm_key(time_block.get("time_range"))
    return time_range == "custom" and bool(time_block.get("time_column_key"))


def _apply_birth_month_date_part_filter(
    *,
    sql_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str,
) -> Dict[str, Any]:
    prompt_text = str(prompt or "").strip().lower()
    month_num = _extract_named_month_number(prompt_text)
    if month_num is None or not _prompt_has_birth_month_constraint(prompt_text):
        return dict(sql_json or {})

    birth_col = _resolve_birth_date_column(capabilities=capabilities)
    if birth_col is None:
        return dict(sql_json or {})

    out = dict(sql_json or {})
    data_prep = dict(out.get("dataPrep") or {}) if isinstance(out.get("dataPrep"), Mapping) else {}
    rules = [dict(item) for item in list(data_prep.get("rules") or []) if isinstance(item, Mapping)]

    base_ref = (
        f"id:{birth_col.get('modelColumnId')}"
        if birth_col.get("modelColumnId") is not None
        else f"name:{birth_col.get('columnName') or 'birth_date'}"
    )
    expr_id = f"dp:date_part:month:{base_ref}"
    alias = f"{str(birth_col.get('columnName') or 'birth_date').strip() or 'birth_date'}_month"
    output_col = {
        "modelColumnId": None,
        "columnName": alias,
        "workspaceTableId": None,
        "exprId": expr_id,
        "alias": alias,
    }

    if not any(str(rule.get("id") or "") == expr_id for rule in rules):
        rules.append(
            {
                "id": expr_id,
                "enabled": True,
                "op": "date_part",
                "part": "month",
                "target": dict(birth_col),
                "output": output_col,
                "applyScope": "query_wide",
            }
        )
    data_prep["enabled"] = True
    data_prep["rules"] = rules
    out["dataPrep"] = data_prep

    root = out.get("filters")
    if not isinstance(root, dict) or root.get("type") != "group":
        root = {"type": "group", "id": "birth-month-root", "match": "and", "children": []}
    children = [dict(item) for item in list(root.get("children") or []) if isinstance(item, Mapping)]
    if not any(
        isinstance(child.get("field"), Mapping)
        and str((child.get("field") or {}).get("exprId") or "") == expr_id
        and str(child.get("op") or "").lower() == "equals"
        and child.get("value") == month_num
        for child in children
    ):
        children.append(
            {
                "type": "condition",
                "id": f"birth-month-{month_num}",
                "field": output_col,
                "op": "equals",
                "value": month_num,
            }
        )
    root["children"] = children
    out["filters"] = root
    return out


def _prompt_has_birth_month_constraint(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    has_birth_context = any(
        token in text
        for token in (
            " birthday ",
            " birthdays ",
            " birth month ",
            " birthdate ",
            " date of birth ",
            " born in ",
            " births in ",
        )
    )
    return has_birth_context


def _extract_named_month_number(text: str) -> Optional[int]:
    month_map = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    match = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
        str(text or "").strip().lower(),
    )
    if match is None:
        return None
    return month_map.get(str(match.group(1) or "").lower())


def _resolve_birth_date_column(*, capabilities: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    rows = (
        list(capabilities.get("filter_columns") or [])
        + list(capabilities.get("dimensions") or [])
        + list(capabilities.get("time_columns") or [])
    )
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        col_name = str(row.get("column_name") or "").strip().lower()
        if col_name in {"birth_date", "date_of_birth", "dob"} or ("birth" in col_name and "date" in col_name):
            col = _to_sql_column_key(row)
            if col is not None:
                return col.model_dump(mode="json", exclude_none=False)
    return None


__all__ = ["map_plan_v2_to_sqljson"]
