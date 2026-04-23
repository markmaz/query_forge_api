from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

from app.models.query.ai_suggest import SqlColumnKey

_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def normalize_domain_key(value: Any) -> str:
    token = str(value or "").strip().lower()
    token = _TOKEN_RE.sub("_", token).strip("_")
    return token


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def tokenize(value: Any) -> list[str]:
    text = normalize_domain_key(value)
    return [part for part in text.split("_") if part]


def confidence_from_overlap(query: str, *parts: str) -> float:
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return 0.0
    doc_tokens: set[str] = set()
    for part in parts:
        doc_tokens.update(tokenize(part))
    if not doc_tokens:
        return 0.0
    overlap = query_tokens & doc_tokens
    return max(0.0, min(1.0, len(overlap) / max(1, len(query_tokens))))


def sql_column_key_from_row(row: Mapping[str, Any]) -> Optional[SqlColumnKey]:
    column_name = normalize_text(row.get("column_name"))
    if column_name == "":
        column_name = normalize_text(row.get("columnName"))
    if column_name == "":
        return None
    workspace_table_id = row.get("workspace_table_id")
    if workspace_table_id is None:
        workspace_table_id = row.get("workspaceTableId")
    workspace_column_id = row.get("workspace_column_id")
    if workspace_column_id is None:
        workspace_column_id = row.get("workspaceColumnId")
    model_column_id = row.get("model_column_id")
    if model_column_id is None:
        model_column_id = row.get("modelColumnId")
    if model_column_id is None:
        model_column_id = workspace_column_id
    return SqlColumnKey(
        modelColumnId=int(model_column_id) if model_column_id is not None else None,
        workspaceTableId=int(workspace_table_id) if workspace_table_id is not None else None,
        columnName=column_name,
        exprId=None,
        alias=None,
    )


def flatten_filter_groups(node: Any) -> list[dict[str, Any]]:
    if not isinstance(node, dict):
        return []
    if str(node.get("type") or "").strip().lower() == "condition":
        return [dict(node)]
    rows: list[dict[str, Any]] = []
    for child in list(node.get("children") or []):
        rows.extend(flatten_filter_groups(child))
    return rows


def dedupe_by_key(rows: Iterable[Dict[str, Any]], *, key_name: str) -> List[Dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = normalize_text(row.get(key_name)).lower()
        if key == "" or key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out
