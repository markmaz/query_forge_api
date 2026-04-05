from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.config import (
    QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED,
    QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_ITEMS,
    QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_TOKENS,
)
from app.exceptions.forge_error import ForgeError
from app.services.llm.prompts_plan_v2 import (
    NEXT_ACTIONS_JSON_SCHEMA,
    build_next_actions_developer_prompt,
    build_next_actions_user_prompt,
    build_system_prompt,
)

logger = logging.getLogger(__name__)

NEXT_ACTION_LLM_ERRORS = (ForgeError,)

# ---------------------------------------------------------------------------
# Allowed filter ops (copy of _NEXT_ACTION_ALLOWED_FILTER_OPS from service.py)
# ---------------------------------------------------------------------------
_NEXT_ACTION_ALLOWED_FILTER_OPS = {
    "=",
    "==",
    "eq",
    "equals",
    "!=",
    "<>",
    "ne",
    "not_equals",
    "in",
    "not_in",
    "contains",
    "like",
    "starts_with",
    "ends_with",
    "gt",
    "gte",
    "lt",
    "lte",
    "is_null",
    "is_not_null",
}

# ---------------------------------------------------------------------------
# Local helper copies (also in service.py; copied to avoid circular imports)
# ---------------------------------------------------------------------------

def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


# ---------------------------------------------------------------------------
# Module-level next-actions functions (moved from service.py)
# ---------------------------------------------------------------------------

def _next_action_capability_payload(*, capabilities: Mapping[str, Any]) -> Dict[str, Any]:
    dims = [dict(row) for row in list(capabilities.get("dimensions") or []) if isinstance(row, Mapping)]
    time_columns = [dict(row) for row in list(capabilities.get("time_columns") or []) if isinstance(row, Mapping)]
    filter_columns = [dict(row) for row in list(capabilities.get("filter_columns") or []) if isinstance(row, Mapping)]

    dim_rows: List[Dict[str, Any]] = []
    seen_dim_keys: set[str] = set()
    for row in dims + time_columns:
        key = _norm_key(row.get("column_key"))
        if key == "" or key in seen_dim_keys:
            continue
        seen_dim_keys.add(key)
        dim_rows.append(
            {
                "column_key": key,
                "label": str(row.get("label") or "").strip(),
                "data_type": str(row.get("data_type") or "").strip().lower(),
            }
        )

    filter_rows: List[Dict[str, Any]] = []
    seen_filter_keys: set[str] = set()
    for row in filter_columns:
        if row.get("filterable") is False:
            continue
        key = _norm_key(row.get("column_key"))
        if key == "" or key in seen_filter_keys:
            continue
        seen_filter_keys.add(key)
        filter_rows.append(
            {
                "column_key": key,
                "label": str(row.get("label") or "").strip(),
                "data_type": str(row.get("data_type") or "").strip().lower(),
            }
        )

    metric_catalog: List[Dict[str, Any]] = []
    for row in list(capabilities.get("domain_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("metric_key"))
        if key:
            metric_catalog.append(
                {
                    "metric_ref": f"domain_metric:{key}",
                    "label": str(row.get("label") or "").strip(),
                }
            )
    for row in list(capabilities.get("user_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("metric_id") or row.get("id"))
        if key:
            metric_catalog.append(
                {
                    "metric_ref": f"user_metric:{key}",
                    "label": str(row.get("label") or "").strip(),
                }
            )
    for row in list(capabilities.get("overlay_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("overlay_key"))
        if key:
            metric_catalog.append(
                {
                    "metric_ref": f"overlay:{key}",
                    "label": str(row.get("label") or "").strip(),
                }
            )

    return {
        "allowed_dimensions": dim_rows[:80],
        "allowed_filter_columns": filter_rows[:80],
        "allowed_metric_refs": [str(row.get("metric_ref") or "") for row in metric_catalog],
        "metric_catalog": metric_catalog,
    }


def _next_action_plan_context(*, plan_json: Mapping[str, Any]) -> Dict[str, Any]:
    selects = plan_json.get("selects") or {}
    return {
        "intent": str(plan_json.get("intent") or "").strip().lower() or "list",
        "dimensions": [
            _norm_key((row or {}).get("column_key"))
            for row in list(selects.get("dimensions") or [])
            if isinstance(row, Mapping) and _norm_key((row or {}).get("column_key"))
        ],
        "metrics": [
            _norm_key((row or {}).get("metric_ref"))
            for row in list(selects.get("metrics") or [])
            if isinstance(row, Mapping) and _norm_key((row or {}).get("metric_ref"))
        ],
        "filters": [
            {
                "column_key": _norm_key(row.get("column_key")),
                "op": str(row.get("op") or "").strip().lower(),
                "value": row.get("value"),
                "values": row.get("values"),
            }
            for row in list(plan_json.get("filters") or [])
            if isinstance(row, Mapping) and _norm_key(row.get("column_key"))
        ],
    }


def _allowed_metric_refs_from_capabilities(*, capabilities: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for row in list(capabilities.get("domain_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("metric_key"))
        if key:
            out.add(f"domain_metric:{key}")
    for row in list(capabilities.get("user_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("metric_id") or row.get("id"))
        if key:
            out.add(f"user_metric:{key}")
    for row in list(capabilities.get("overlay_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("overlay_key"))
        if key:
            out.add(f"overlay:{key}")
    return out


def _column_name_from_key(key: Any) -> str:
    token = _norm_key(key)
    if token == "" or "." not in token:
        return ""
    return token.split(".", 1)[1]


def _unique_allowed_key_by_column_name(allowed_keys: Sequence[str]) -> Dict[str, str]:
    by_name: Dict[str, set[str]] = {}
    for raw_key in allowed_keys:
        key = _norm_key(raw_key)
        col_name = _column_name_from_key(key)
        if key == "" or col_name == "":
            continue
        by_name.setdefault(col_name, set()).add(key)
    return {
        col_name: sorted(keys)[0]
        for col_name, keys in by_name.items()
        if len(keys) == 1
    }


def _repair_allowed_key(
    *,
    key: str,
    allowed_keys: set[str],
    unique_key_by_column_name: Mapping[str, str],
) -> str:
    if key == "":
        return ""
    if key in allowed_keys:
        return key
    col_name = _column_name_from_key(key)
    if col_name == "":
        return ""
    return _norm_key(unique_key_by_column_name.get(col_name))


def _normalize_next_action_text(value: Any, *, max_len: int) -> str:
    text = " ".join(str(value or "").strip().split())
    if text == "":
        return ""
    if len(text) > max_len:
        text = text[:max_len].rstrip()
    return text


def _normalize_next_action_intent(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"aggregate", "agg", "summary"}:
        return "aggregate"
    if token in {"trend", "timeseries", "time_series", "time-series"}:
        return "trend"
    return "list"


def _normalize_next_action_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.7
    if number < 0.0:
        number = 0.0
    if number > 1.0:
        number = 1.0
    return round(number, 2)


def _normalize_next_action_filter_op(value: Any) -> str:
    token = str(value or "").strip().lower().replace(" ", "_")
    alias = {
        "not_equals": "ne",
        "equals": "eq",
        "notin": "not_in",
        "isnull": "is_null",
        "isnotnull": "is_not_null",
    }.get(token, token)
    if alias not in _NEXT_ACTION_ALLOWED_FILTER_OPS:
        return ""
    return alias


def _normalize_next_action_item(
    *,
    item: Any,
    allowed_dim_keys: set[str],
    dim_key_by_column_name: Mapping[str, str],
    allowed_filter_keys: set[str],
    filter_key_by_column_name: Mapping[str, str],
    allowed_metric_refs: set[str],
) -> Optional[Dict[str, Any]]:
    if not isinstance(item, Mapping):
        return None

    label = _normalize_next_action_text(item.get("label"), max_len=80)
    prompt = _normalize_next_action_text(item.get("prompt"), max_len=220)
    reason = _normalize_next_action_text(item.get("reason"), max_len=220)
    if not label or not prompt or not reason:
        return None

    intent = _normalize_next_action_intent(item.get("intent"))
    confidence = _normalize_next_action_confidence(item.get("confidence"))

    dimensions: List[str] = []
    for raw in list(item.get("dimensions") or []):
        key = _repair_allowed_key(
            key=_norm_key(raw),
            allowed_keys=allowed_dim_keys,
            unique_key_by_column_name=dim_key_by_column_name,
        )
        if key == "":
            continue
        if key not in dimensions:
            dimensions.append(key)

    metrics: List[str] = []
    for raw in list(item.get("metrics") or []):
        if isinstance(raw, Mapping):
            token = _norm_key(raw.get("metric_ref"))
        else:
            token = _norm_key(raw)
        if token == "":
            continue
        if token not in allowed_metric_refs:
            continue
        if token not in metrics:
            metrics.append(token)

    filters: List[Dict[str, Any]] = []
    for raw in list(item.get("filters") or []):
        if not isinstance(raw, Mapping):
            continue
        key = _repair_allowed_key(
            key=_norm_key(raw.get("column_key")),
            allowed_keys=allowed_filter_keys,
            unique_key_by_column_name=filter_key_by_column_name,
        )
        if key == "":
            continue
        op = _normalize_next_action_filter_op(raw.get("op"))
        if op == "":
            continue
        row: Dict[str, Any] = {"column_key": key, "op": op}
        values = raw.get("values")
        value = raw.get("value")
        if op in {"in", "not_in"}:
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                cleaned = [v for v in list(values) if v is not None]
            elif value is not None:
                cleaned = [value]
            else:
                cleaned = []
            if not cleaned:
                continue
            row["values"] = cleaned[:20]
        elif op in {"is_null", "is_not_null"}:
            pass
        elif value is not None:
            row["value"] = value
        elif isinstance(values, Sequence) and not isinstance(values, (str, bytes)) and list(values):
            row["value"] = list(values)[0]
        else:
            continue
        filters.append(row)

    if intent == "aggregate" and not metrics:
        return None
    if not dimensions and not metrics and not filters:
        return None

    return {
        "label": label,
        "prompt": prompt,
        "reason": reason,
        "intent": intent,
        "confidence": confidence,
        "dimensions": dimensions,
        "metrics": metrics,
        "filters": filters,
    }


def _normalize_next_actions(
    *,
    actions: Sequence[Any],
    original_prompt: str,
    capabilities: Mapping[str, Any],
    max_items: int,
) -> List[Dict[str, Any]]:
    allowed_dim_keys = {
        _norm_key(row.get("column_key"))
        for row in list(capabilities.get("dimensions") or []) + list(capabilities.get("time_columns") or [])
        if isinstance(row, Mapping) and _norm_key(row.get("column_key"))
    }
    allowed_filter_keys = {
        _norm_key(row.get("column_key"))
        for row in list(capabilities.get("filter_columns") or [])
        if isinstance(row, Mapping) and row.get("filterable") is not False and _norm_key(row.get("column_key"))
    }
    dim_key_by_column_name = _unique_allowed_key_by_column_name(allowed_dim_keys)
    filter_key_by_column_name = _unique_allowed_key_by_column_name(allowed_filter_keys)
    allowed_metric_refs = _allowed_metric_refs_from_capabilities(capabilities=capabilities)

    out: List[Dict[str, Any]] = []
    seen_prompts: set[str] = set()
    source_prompt = " ".join(str(original_prompt or "").strip().lower().split())
    for raw in list(actions or []):
        normalized = _normalize_next_action_item(
            item=raw,
            allowed_dim_keys=allowed_dim_keys,
            dim_key_by_column_name=dim_key_by_column_name,
            allowed_filter_keys=allowed_filter_keys,
            filter_key_by_column_name=filter_key_by_column_name,
            allowed_metric_refs=allowed_metric_refs,
        )
        if normalized is None:
            continue
        prompt_key = " ".join(str(normalized.get("prompt") or "").strip().lower().split())
        if prompt_key == "" or prompt_key in seen_prompts or prompt_key == source_prompt:
            continue
        seen_prompts.add(prompt_key)
        out.append(normalized)
        if len(out) >= max_items:
            break
    return out


# ---------------------------------------------------------------------------
# Public service class
# ---------------------------------------------------------------------------

class NextActionsService:
    """Generates in-domain next-action suggestions via LLM."""

    def __init__(self, *, llm_client=None) -> None:
        self._llm_client = llm_client

    def maybe_generate(
        self,
        *,
        plan_json: dict,
        capabilities: dict,
        prompt: str,
        selected_domain_id: int,
        selected_domain_name: str,
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Returns ``(next_actions_list, next_actions_trace_dict)``.

        Mirrors the behaviour of the former
        ``PlannerDomainService._maybe_generate_next_actions``.
        """
        if not QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED:
            return [], {"enabled": False, "used": False}

        max_items = max(1, min(int(QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_ITEMS or 3), 6))
        capability_payload = _next_action_capability_payload(capabilities=capabilities)
        if not capability_payload.get("allowed_dimensions") and not capability_payload.get("allowed_metric_refs"):
            return [], {"enabled": True, "used": False, "reason": "no_capabilities"}

        input_payload = {
            "user_question": str(prompt or "").strip(),
            "domain": {
                "domain_id": int(selected_domain_id),
                "domain_name": str(selected_domain_name or "").strip(),
                "domain_version": _to_int(capabilities.get("domain_version")) or 0,
            },
            "current_plan": _next_action_plan_context(plan_json=plan_json),
            "capabilities": capability_payload,
            "rules": {
                "stay_in_domain": True,
                "suggestion_count": {"min": 2, "max": max_items},
            },
            "schema": NEXT_ACTIONS_JSON_SCHEMA,
        }
        composed_user = (
            f"{build_next_actions_developer_prompt()}\n\n"
            f"{build_next_actions_user_prompt(payload=input_payload)}"
        )
        try:
            trace = self._llm_client.chat_json_with_trace(
                system_prompt=build_system_prompt(),
                user_prompt=composed_user,
                response_format=True,
                max_tokens=QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_TOKENS,
            )
        except NEXT_ACTION_LLM_ERRORS as exc:
            logger.warning("planner_domain next actions generation failed err=%s", exc)
            return [], {"enabled": True, "used": False, "error": str(exc)}

        parsed = trace.get("parsed") if isinstance(trace.get("parsed"), Mapping) else {}
        raw_actions = list((parsed or {}).get("next_actions") or [])
        normalized = _normalize_next_actions(
            actions=raw_actions,
            original_prompt=prompt,
            capabilities=capabilities,
            max_items=max_items,
        )
        retry_trace: Optional[Dict[str, Any]] = None
        if not normalized:
            retry_user_prompt = (
                f"{composed_user}\n\n"
                "Retry requirements:\n"
                "- Use exact allowed column_key values from capabilities.\n"
                "- If a column is uncertain, omit it.\n"
                "- Return at least 2 safe suggestions that remain inside this domain."
            )
            try:
                retry_trace = self._llm_client.chat_json_with_trace(
                    system_prompt=build_system_prompt(),
                    user_prompt=retry_user_prompt,
                    response_format=True,
                    max_tokens=QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_TOKENS,
                )
                retry_parsed = retry_trace.get("parsed") if isinstance(retry_trace.get("parsed"), Mapping) else {}
                retry_raw_actions = list((retry_parsed or {}).get("next_actions") or [])
                normalized = _normalize_next_actions(
                    actions=retry_raw_actions,
                    original_prompt=prompt,
                    capabilities=capabilities,
                    max_items=max_items,
                )
                if retry_raw_actions:
                    raw_actions = retry_raw_actions
            except NEXT_ACTION_LLM_ERRORS as exc:
                logger.warning("planner_domain next actions retry failed err=%s", exc)

        return normalized, {
            "enabled": True,
            "used": bool(normalized),
            "requested_items": len(raw_actions),
            "returned_items": len(normalized),
            "error": trace.get("error"),
            "finish_reason": trace.get("finish_reason"),
            "content_preview": str(trace.get("content") or "")[:300],
            "retried": retry_trace is not None,
            "retry_error": (retry_trace or {}).get("error") if retry_trace is not None else None,
            "retry_finish_reason": (retry_trace or {}).get("finish_reason") if retry_trace is not None else None,
            "retry_content_preview": str((retry_trace or {}).get("content") or "")[:300] if retry_trace is not None else "",
        }
