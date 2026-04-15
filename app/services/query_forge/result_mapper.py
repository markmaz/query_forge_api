"""Result-processing helpers for the query_forge package.

All functions are module-level (stateless) extractions from QueryForgeService.
"""
from __future__ import annotations

from typing import Any, Dict, List


def extract_total(count_rows: List[Any]) -> int:
    """Extract the integer total from a COUNT(*) result set."""
    if not count_rows:
        return 0
    first = count_rows[0]
    if isinstance(first, dict):
        return int(first.get("total") or 0)
    if isinstance(first, (list, tuple)) and len(first) >= 1:
        return int(first[0] or 0)
    return 0


def infer_cols(rows: List[Any]) -> List[Dict[str, Any]]:
    """Infer column metadata from the first result row (dict rows only)."""
    if not rows:
        return []
    first = rows[0]
    if isinstance(first, dict):
        return [{"key": k, "label": k} for k in first.keys()]
    return []


def rows_to_dicts(qf_result_rows: List[Any], columns: List[Any]) -> List[Dict[str, Any]]:
    """Normalise raw executor rows into a list of dicts keyed by column name."""
    if not qf_result_rows:
        return []
    if isinstance(qf_result_rows[0], dict):
        return qf_result_rows
    if not columns:
        return []
    if isinstance(columns[0], dict):
        keys = [c.get("key") for c in columns]
    else:
        keys = list(columns)
    out = []
    for row in qf_result_rows:
        if not isinstance(row, (list, tuple)):
            continue
        out.append({keys[i]: (row[i] if i < len(row) else None) for i in range(len(keys))})
    return out


def cols_from_json(q: dict) -> List[Dict[str, Any]]:
    """Derive column metadata from the query JSON itself (fallback path)."""
    aggs = (q.get("aggs") or {})
    if aggs.get("enabled"):
        cols: List[Dict[str, Any]] = []
        alias_map = {
            c.get("columnName"): (c.get("alias") or None)
            for c in (q.get("columns") or [])
            if isinstance(c, dict)
        }
        for gb in (aggs.get("groupBy") or []):
            raw = gb.get("columnName") if isinstance(gb, dict) else str(gb)
            cols.append({"key": raw, "label": (alias_map.get(raw) or raw)})
        for m in (aggs.get("metrics") or []):
            label = (m.get("label") or "").strip() or None
            fn = (m.get("fn") or "").strip() or "metric"
            key = label or fn
            cols.append({"key": key, "label": label or fn})
        return cols

    out: List[Dict[str, Any]] = []
    for c in (q.get("columns") or []):
        if not isinstance(c, dict):
            continue
        k = c.get("alias") or c.get("columnName")
        if not k:
            continue
        out.append({"key": k, "label": k})
    return out
