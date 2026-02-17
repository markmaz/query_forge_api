from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from app.models.ai_suggest import EditOperation, SqlColumnKey


def _new_id() -> str:
    return uuid4().hex


def _default_sqljson(prompt: Optional[str]) -> Dict[str, Any]:
    return {
        "version": 1,
        "domainId": None,
        "columns": [],
        "filters": None,
        "aggs": None,
        "sorting": [],
        "dataPrep": None,
        "distinct": False,
        "meta": {"prompt": prompt or ""},
    }


def _ensure_base_shape(sqljson: Dict[str, Any], prompt: Optional[str]) -> Dict[str, Any]:
    out = deepcopy(sqljson)
    out.setdefault("version", 1)
    out.setdefault("domainId", None)
    out.setdefault("columns", [])
    out.setdefault("filters", None)
    out.setdefault("aggs", None)
    out.setdefault("sorting", [])
    out.setdefault("dataPrep", None)
    out.setdefault("distinct", False)
    out.setdefault("meta", {})
    if not isinstance(out["meta"], dict):
        out["meta"] = {}
    if prompt is not None:
        out["meta"]["prompt"] = prompt
    else:
        out["meta"].setdefault("prompt", "")
    return out


def _col_to_dict(col: SqlColumnKey) -> Dict[str, Any]:
    return col.model_dump(mode="json", exclude_none=False)


def _col_signature(col: Dict[str, Any]) -> tuple:
    return (
        col.get("modelColumnId"),
        col.get("workspaceTableId"),
        (col.get("columnName") or "").strip().lower(),
        col.get("exprId"),
    )


def _sort_signature(sort_entry: Dict[str, Any]) -> tuple:
    col = sort_entry.get("col")
    if not isinstance(col, dict):
        return ("", "", "", "")
    return (*_col_signature(col), str(sort_entry.get("dir") or "").lower())


def _ensure_root_filter_group(sqljson: Dict[str, Any]) -> Dict[str, Any]:
    root = sqljson.get("filters")
    if not isinstance(root, dict) or root.get("type") != "group":
        root = {
            "type": "group",
            "id": _new_id(),
            "match": "and",
            "children": [],
        }
        sqljson["filters"] = root
    root.setdefault("id", _new_id())
    root.setdefault("match", "and")
    if not isinstance(root.get("children"), list):
        root["children"] = []
    return root


def _ensure_aggs(sqljson: Dict[str, Any]) -> Dict[str, Any]:
    aggs = sqljson.get("aggs")
    if not isinstance(aggs, dict):
        aggs = {"enabled": True, "groupBy": [], "metrics": []}
        sqljson["aggs"] = aggs
    aggs["enabled"] = True
    if not isinstance(aggs.get("groupBy"), list):
        aggs["groupBy"] = []
    if not isinstance(aggs.get("metrics"), list):
        aggs["metrics"] = []
    return aggs


def _map_filter_operator(op: str) -> str:
    mapping = {
        "=": "equals",
        "!=": "equals",
        "in": "in",
        "between": "between",
        "contains": "contains",
        "starts_with": "starts_with",
        "gt": "gt",
        "lt": "lt",
        "equals": "equals",
    }
    return mapping.get(op, "equals")


def apply_edits(
    current_sqljson: Optional[Dict[str, Any]],
    edits: Iterable[EditOperation],
    *,
    prompt: Optional[str] = None,
) -> Dict[str, Any]:
    sqljson = _default_sqljson(prompt) if not isinstance(current_sqljson, dict) else _ensure_base_shape(current_sqljson, prompt)

    for edit in edits:
        op = getattr(edit, "op", "")
        if op == "setDomain":
            previous_domain = sqljson.get("domainId")
            new_domain = getattr(edit, "domainId", None)
            sqljson["domainId"] = new_domain
            if previous_domain != new_domain:
                sqljson["columns"] = []
                sqljson["filters"] = None
                sqljson["aggs"] = None
                sqljson["sorting"] = []
                sqljson["dataPrep"] = None
            continue

        if op == "addSelect":
            col_dict = _col_to_dict(edit.col)
            alias = getattr(edit, "alias", None)
            sqljson.setdefault("columns", [])
            sqljson["columns"].append(
                {
                    "field": col_dict,
                    "alias": alias,
                }
            )
            continue

        if op == "addFilter":
            root = _ensure_root_filter_group(sqljson)
            condition = {
                "type": "condition",
                "id": _new_id(),
                "field": _col_to_dict(edit.col),
                "op": _map_filter_operator(getattr(edit, "operator", "equals")),
                "value": getattr(edit, "value", None),
            }
            root["children"].append(condition)
            continue

        if op == "addGroupBy":
            aggs = _ensure_aggs(sqljson)
            candidate = _col_to_dict(edit.col)
            existing = {_col_signature(item) for item in aggs["groupBy"] if isinstance(item, dict)}
            if _col_signature(candidate) not in existing:
                aggs["groupBy"].append(candidate)
            continue

        if op == "addAggregate":
            aggs = _ensure_aggs(sqljson)
            metric = {
                "id": _new_id(),
                "fn": getattr(edit, "func", "count"),
                "field": _col_to_dict(edit.col) if getattr(edit, "col", None) is not None else None,
                "label": getattr(edit, "alias", None),
            }
            aggs["metrics"].append(metric)
            continue

        if op == "addSort":
            sqljson.setdefault("sorting", [])
            candidate = {
                "col": _col_to_dict(edit.col),
                "dir": getattr(edit, "dir", "asc"),
            }
            existing = {
                _sort_signature(item)
                for item in sqljson["sorting"]
                if isinstance(item, dict)
            }
            if _sort_signature(candidate) not in existing:
                sqljson["sorting"].append(candidate)
            continue

    return sqljson
