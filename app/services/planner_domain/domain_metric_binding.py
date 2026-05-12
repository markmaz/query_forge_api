from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_COUNT_PROMPT_RE = re.compile(r"\b(how many|count|number of|total)\b", re.IGNORECASE)
_STOP_TOKENS = {
    "a",
    "an",
    "and",
    "by",
    "count",
    "for",
    "how",
    "many",
    "metric",
    "number",
    "of",
    "run",
    "runs",
    "show",
    "studio",
    "the",
    "total",
    "workflow",
    "workflows",
}


def bind_prompt_domain_metric(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str,
) -> Dict[str, Any]:
    """Fill an empty metric selection from domain_profile metric metadata."""
    out = dict(plan_json or {})
    selects = dict(out.get("selects") or {}) if isinstance(out.get("selects"), Mapping) else {}
    if list(selects.get("metrics") or []):
        return out
    if not _prompt_wants_metric(prompt):
        return out

    metric = _best_metric(capabilities=capabilities, prompt=prompt)
    metric_key = str((metric or {}).get("metric_key") or "").strip().lower()
    if metric_key == "":
        return out

    selects["metrics"] = [{"metric_ref": f"domain_metric:{metric_key}"}]
    out["selects"] = selects
    if str(out.get("intent") or "").strip().lower() in {"", "list"}:
        out["intent"] = "aggregate"
    grouping = dict(out.get("grouping") or {}) if isinstance(out.get("grouping"), Mapping) else {}
    grouping.setdefault("group_by", [])
    grouping.setdefault("order_by", [])
    grouping.setdefault("limit", None)
    out["grouping"] = grouping
    return out


def _prompt_wants_metric(prompt: str) -> bool:
    text = str(prompt or "").strip()
    return bool(_COUNT_PROMPT_RE.search(text))


def _best_metric(*, capabilities: Mapping[str, Any], prompt: str) -> Optional[Mapping[str, Any]]:
    prompt_tokens = _meaningful_tokens(prompt)
    if not prompt_tokens:
        return None

    ranked: list[tuple[int, int, Mapping[str, Any]]] = []
    for idx, raw in enumerate(list(capabilities.get("domain_metrics") or [])):
        if not isinstance(raw, Mapping):
            continue
        metric_key = str(raw.get("metric_key") or "").strip().lower()
        if metric_key == "":
            continue
        metric_tokens = _meaningful_tokens(
            " ".join(
                [
                    metric_key,
                    str(raw.get("label") or ""),
                    str(raw.get("kind") or ""),
                    str(raw.get("agg") or ""),
                ]
            )
        )
        overlap = prompt_tokens & metric_tokens
        score = len(overlap) * 100
        if "completed" in prompt_tokens and "completed" in metric_tokens:
            score += 300
        if "needs" in prompt_tokens and "attention" in prompt_tokens and {"needs", "attention"} <= metric_tokens:
            score += 300
        if "failed" in prompt_tokens and ("failed" in metric_tokens or "failure" in metric_tokens):
            score += 250
        if "success" in prompt_tokens and ("success" in metric_tokens or "successful" in metric_tokens):
            score += 250
        if "run" in _tokens(prompt) or "runs" in _tokens(prompt):
            if "run" in _tokens(metric_key) or "runs" in _tokens(metric_key):
                score += 40
        if metric_key.endswith("_count") or str(raw.get("kind") or "").strip().lower() == "count":
            score += 10
        if metric_key == "run_count":
            score -= 20
        if score > 0:
            ranked.append((score, -idx, raw))
    if not ranked:
        return None
    ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
    return ranked[0][2]


def _meaningful_tokens(value: Any) -> set[str]:
    return {token for token in _tokens(value) if token not in _STOP_TOKENS}


def _tokens(value: Any) -> set[str]:
    return set(_TOKEN_RE.findall(str(value or "").strip().lower()))


__all__ = ["bind_prompt_domain_metric"]
