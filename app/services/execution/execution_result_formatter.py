from __future__ import annotations

from typing import Any, Dict, Optional


def columns_from_manifest(manifest: Optional[Dict[str, Any]]) -> list[Dict[str, Any]]:
    if not isinstance(manifest, dict):
        return []
    schema = manifest.get("schema") or {}
    columns = schema.get("columns") or []
    if not isinstance(columns, list):
        return []
    out: list[Dict[str, Any]] = []
    for col in columns:
        if not isinstance(col, dict):
            continue
        name = col.get("name")
        if not name:
            continue
        item = {"key": name, "label": name}
        if "type" in col:
            item["dataType"] = col.get("type")
        if "nullable" in col:
            item["nullable"] = col.get("nullable")
        out.append(item)
    return out


def columns_from_rows(rows: list[Any]) -> list[Dict[str, Any]]:
    if not rows:
        return []
    first = rows[0]
    if isinstance(first, dict):
        return [{"key": key, "label": key} for key in first.keys()]
    return []


def exec_rows_to_dicts(qf_rows_any: list[Any], columns: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    if not qf_rows_any:
        return []
    if isinstance(qf_rows_any[0], dict):
        return qf_rows_any
    if not columns:
        return []
    keys = [column.get("key") for column in columns]
    out: list[Dict[str, Any]] = []
    for row in qf_rows_any:
        if not isinstance(row, (list, tuple)):
            continue
        out.append({keys[i]: (row[i] if i < len(row) else None) for i in range(len(keys))})
    return out


def extract_total(count_rows: list[Any]) -> Optional[int]:
    if not count_rows:
        return None
    first = count_rows[0]
    if isinstance(first, dict) and first:
        value = first.get("total") if "total" in first else next(iter(first.values()), None)
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if isinstance(first, (list, tuple)) and len(first) >= 1:
        try:
            return int(first[0])
        except (TypeError, ValueError):
            return None
    return None


def truncate_cell_value(value: Any, *, max_len: int = 80) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 1]}…"


def escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")


def rows_markdown(columns: list[Dict[str, Any]], rows: list[Dict[str, Any]], *, max_rows: int = 10) -> str:
    if not columns or not rows:
        return ""
    col_keys = [str(col.get("key") or "").strip() for col in columns if str(col.get("key") or "").strip()]
    if not col_keys:
        return ""
    sample = rows[: max(1, int(max_rows))]
    header = "| " + " | ".join(escape_markdown_cell(key) for key in col_keys) + " |"
    divider = "| " + " | ".join("---" for _ in col_keys) + " |"
    body_lines = []
    for row in sample:
        values = []
        for key in col_keys:
            raw = row.get(key) if isinstance(row, dict) else None
            values.append(escape_markdown_cell(truncate_cell_value(raw)))
        body_lines.append("| " + " | ".join(values) + " |")
    return "\n".join([header, divider, *body_lines])


def build_assistant_result_message(
    *,
    rows: list[Dict[str, Any]],
    columns: list[Dict[str, Any]],
    total: Any,
    limit: Any,
    offset: Any,
) -> Dict[str, Any]:
    shown = len(rows)
    total_int = None
    try:
        total_int = int(total)
    except (TypeError, ValueError):
        total_int = None
    summary = f"Query complete. Returned {shown} row(s)"
    if total_int is not None:
        summary += f" (total {total_int})"
    if limit is not None or offset is not None:
        summary += f". Limit={limit if limit is not None else 'n/a'}, Offset={offset if offset is not None else 'n/a'}"
    summary += "."
    table_md = rows_markdown(columns, rows)
    content = summary if table_md == "" else f"{summary}\n\n{table_md}"
    return {
        "role": "assistant",
        "content": content,
        "format": "markdown",
        "kind": "execution_result",
    }
