from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from app.ports.sql_executor import ForgeQueryPort

_GENERIC_METRIC_TOKENS = {
    "count",
    "counts",
    "flowforge",
    "many",
    "number",
    "run",
    "runs",
    "studio",
    "total",
    "workflow",
    "workflows",
}


def apply_domain_profile_metric_bindings(
    *,
    sql: ForgeQueryPort,
    workspace_id: str,
    domain_id: int | None,
    prompt: str,
    role_guardrails: Mapping[str, Any],
) -> dict[str, Any]:
    out = {key: list(value) if isinstance(value, list) else value for key, value in dict(role_guardrails or {}).items()}
    if domain_id is None or not _prompt_implies_count(prompt):
        return out

    metrics = _load_domain_profile_metrics(sql=sql, workspace_id=workspace_id, domain_id=domain_id)
    metric = _select_metric_for_prompt(metrics=metrics, prompt=prompt)
    row = _metric_to_column_row(metric)
    if row is None:
        return out

    _prepend_unique(out, "metric_columns", row)
    _prepend_unique(out, "allowed_columns", row)
    return out


def _load_domain_profile_metrics(*, sql: ForgeQueryPort, workspace_id: str, domain_id: int) -> list[dict[str, Any]]:
    rows = sql.execute_query_mappings(
        """
        SELECT metrics
        FROM domain_profile
        WHERE workspace_id = :workspace_id
          AND domain_id = :domain_id
        LIMIT 1
        """,
        {"workspace_id": workspace_id, "domain_id": int(domain_id)},
    )
    if not rows:
        return []
    raw = rows[0].get("metrics")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _select_metric_for_prompt(*, metrics: Sequence[Mapping[str, Any]], prompt: str) -> Mapping[str, Any] | None:
    rows: list[tuple[float, int, Mapping[str, Any]]] = []
    for index, metric in enumerate(metrics):
        score = _metric_prompt_score(metric=metric, prompt=prompt)
        if score <= 0:
            continue
        rows.append((score, -index, metric))
    if not rows:
        return None
    rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return rows[0][2]


def _metric_prompt_score(*, metric: Mapping[str, Any], prompt: str) -> float:
    prompt_tokens = {_stem(token) for token in _tokens(prompt)}
    if not prompt_tokens:
        return 0.0
    key = str(metric.get("metric_key") or metric.get("key") or "").strip()
    label = str(metric.get("label") or "").strip()
    metric_tokens = {_stem(token) for token in _tokens(f"{key} {label}")}
    distinctive = {token for token in metric_tokens if token not in _GENERIC_METRIC_TOKENS}
    if distinctive:
        matched = distinctive & prompt_tokens
        if matched == distinctive:
            return 1.0 + (len(matched) * 0.05)
        if matched:
            return 0.72 + (len(matched) * 0.03)
        return 0.0
    if key.lower() in {"run_count", "record_count", "row_count"}:
        return 0.55
    return 0.0


def _metric_to_column_row(metric: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(metric, Mapping):
        return None
    sql_metric = metric.get("sql_metric")
    field = sql_metric.get("field") if isinstance(sql_metric, Mapping) else None
    if not isinstance(field, Mapping):
        return None
    model_column_id = _to_int(field.get("modelColumnId") or field.get("model_column_id"))
    column_name = str(field.get("columnName") or field.get("column_name") or "").strip()
    if model_column_id is None or column_name == "":
        return None
    metric_key = str(metric.get("metric_key") or metric.get("key") or column_name).strip().upper()
    return {
        "model_column_id": model_column_id,
        "workspace_table_id": _to_int(field.get("workspaceTableId") or field.get("workspace_table_id")),
        "table_name": field.get("tableName") or field.get("table_name") or "domain_profile_metric",
        "column_name": column_name,
        "concept_key": metric_key,
        "semantic_type": "metric",
        "final_score": 100.0,
        "effective_weight": 100.0,
        "source": "domain_profile_metric",
        "metric_agg": str(sql_metric.get("fn") or metric.get("agg") or "count").strip().lower()
        if isinstance(sql_metric, Mapping)
        else "count",
        "metric_label": str(sql_metric.get("label") or metric.get("label") or metric_key).strip()
        if isinstance(sql_metric, Mapping)
        else metric_key,
    }


def _prepend_unique(payload: dict[str, Any], key: str, row: Mapping[str, Any]) -> None:
    rows = [dict(item) for item in list(payload.get(key) or []) if isinstance(item, dict)]
    row_mid = _to_int(row.get("model_column_id"))
    deduped = [item for item in rows if _to_int(item.get("model_column_id")) != row_mid]
    payload[key] = [dict(row), *deduped]


def _prompt_implies_count(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return re.search(r"\b(how many|count|number of|total|distinct|unique)\b", text) is not None


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", str(value or "").lower().replace("_", " ")) if token]


def _stem(token: str) -> str:
    text = str(token or "").strip().lower()
    if len(text) > 4 and text.endswith("ies"):
        return f"{text[:-3]}y"
    if len(text) > 3 and text.endswith("s"):
        return text[:-1]
    return text


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

