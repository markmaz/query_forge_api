from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.config import (
    QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED,
    QF_PLAN_DOMAIN_LLM_EXPLANATION_MAX_TOKENS,
)
from app.exceptions.forge_error import ForgeError

logger = logging.getLogger(__name__)

EXPLANATION_LLM_ERRORS = (ForgeError,)


# ---------------------------------------------------------------------------
# Local copies of small helpers (also defined in service.py; copied to avoid
# circular imports)
# ---------------------------------------------------------------------------

def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _selected_domain_name(
    *, domain_candidates: Sequence[Mapping[str, Any]], selected_domain_id: int
) -> Optional[str]:
    selected = int(selected_domain_id)
    for row in domain_candidates:
        if _to_int(row.get("domain_id")) != selected:
            continue
        name = str(row.get("name") or "").strip()
        if name:
            return name
    return None


# ---------------------------------------------------------------------------
# Explanation helper functions (moved from service.py)
# ---------------------------------------------------------------------------

def _explanation_column_lookup(*, capabilities: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    rows = (
        list(capabilities.get("dimensions") or [])
        + list(capabilities.get("filter_columns") or [])
        + list(capabilities.get("time_columns") or [])
    )
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "":
            continue
        out[key] = dict(row)
    return out


def _humanize_token(value: str) -> str:
    words = [tok for tok in str(value or "").replace("_", " ").split() if tok]
    if not words:
        return ""
    return " ".join(word.capitalize() for word in words)


def _column_label_for_explanation(
    *, column_key: str, col_lookup: Mapping[str, Mapping[str, Any]]
) -> str:
    row = dict(col_lookup.get(_norm_key(column_key)) or {})
    label = str(row.get("label") or "").strip()
    if label:
        return label
    column_name = str(row.get("column_name") or "").strip()
    if column_name:
        return _humanize_token(column_name)
    token = str(column_key or "").strip()
    if "." in token:
        token = token.split(".", 1)[1]
    return _humanize_token(token or "field")


def _friendly_filter_op(op: str) -> str:
    mapping = {
        "=": "is",
        "==": "is",
        "eq": "is",
        "equals": "is",
        "!=": "is not",
        "<>": "is not",
        "ne": "is not",
        "not_equals": "is not",
        "in": "is one of",
        "not_in": "is not one of",
        "contains": "contains",
        "like": "contains",
        "starts_with": "starts with",
        "ends_with": "ends with",
        "gt": "is greater than",
        "gte": "is at least",
        "lt": "is less than",
        "lte": "is at most",
        "is_null": "is blank",
        "is_not_null": "is filled in",
    }
    return mapping.get(str(op or "").strip().lower(), "matches")


def _human_list(values: Sequence[str]) -> str:
    items = [str(v).strip() for v in list(values or []) if str(v).strip()]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _friendly_filter_clause(item: Mapping[str, Any]) -> str:
    label = str(item.get("label") or "").strip() or "field"
    op_label = str(item.get("op_label") or "").strip() or "matches"
    op = str(item.get("op") or "").strip().lower()
    if op in {"is_null", "is_not_null"}:
        return f"{label} {op_label}"

    if isinstance(item.get("values"), list):
        values = [str(v).strip() for v in list(item.get("values") or []) if str(v).strip()]
        if values:
            return f"{label} {op_label} {_human_list(values)}"
    if "value" in item and item.get("value") is not None:
        value = str(item.get("value")).strip()
        if value:
            return f"{label} {op_label} {value}"
    return f"{label} {op_label}"


def _normalize_explanation_summary(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    if text == "":
        return ""
    if len(text) > 600:
        text = text[:600].rstrip()
    return text


def _build_plan_explanation(
    *,
    selected_domain_id: int,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    domain_candidates: Sequence[Mapping[str, Any]],
    ranking_debug: Sequence[Mapping[str, Any]],
    shortlisted_columns: Sequence[Mapping[str, Any]],
    country_debug: Sequence[Mapping[str, Any]],
    school_year_debug: Sequence[Mapping[str, Any]],
    semester_debug: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    selected_domain_name = str(plan_json.get("domain_name") or "").strip()
    if selected_domain_name == "":
        selected_domain_name = _selected_domain_name(
            domain_candidates=domain_candidates,
            selected_domain_id=selected_domain_id,
        )

    selected_ranking = None
    for row in ranking_debug:
        if _to_int((row or {}).get("domain_id")) == int(selected_domain_id):
            selected_ranking = dict(row)
            break

    score = float((selected_ranking or {}).get("score") or 0.0)
    vector_score = float((selected_ranking or {}).get("vector_score") or 0.0)
    shortlist_count = int(
        (selected_ranking or {}).get("column_shortlist_count") or len(list(shortlisted_columns or []))
    )

    dim_rows = list((plan_json.get("selects") or {}).get("dimensions") or [])
    metric_rows = list((plan_json.get("selects") or {}).get("metrics") or [])
    filter_rows = list(plan_json.get("filters") or [])
    col_lookup = _explanation_column_lookup(capabilities=capabilities)

    shortlist_keys = {
        _norm_key(row.get("column_key"))
        for row in list(shortlisted_columns or [])
        if isinstance(row, Mapping)
    }
    dim_details: List[Dict[str, Any]] = []
    for item in dim_rows:
        key = _norm_key((item or {}).get("column_key"))
        if key == "":
            continue
        dim_details.append(
            {
                "column_key": key,
                "label": _column_label_for_explanation(column_key=key, col_lookup=col_lookup),
                "reason": (
                    "This field closely matched the wording in your question."
                    if key in shortlist_keys
                    else "This field helps answer your question and is available for this dataset."
                ),
            }
        )

    metric_details: List[Dict[str, Any]] = []
    domain_metric_lookup = {
        _norm_key(row.get("metric_key")): dict(row)
        for row in list(capabilities.get("domain_metrics") or [])
        if isinstance(row, Mapping) and _norm_key(row.get("metric_key"))
    }
    for item in metric_rows:
        metric_ref = _norm_key((item or {}).get("metric_ref"))
        if metric_ref == "":
            continue
        label = str(item.get("label") or "").strip()
        detail: Dict[str, Any] = {"metric_ref": metric_ref, "label": label or metric_ref}
        if metric_ref.startswith("domain_metric:"):
            key = metric_ref.split(":", 1)[1].strip()
            metric_meta = domain_metric_lookup.get(key) or {}
            detail["label"] = str(metric_meta.get("label") or detail["label"]).strip() or detail["label"]
            detail["reason"] = "This metric matches a summary/count style question."
        elif metric_ref.startswith("overlay:"):
            detail["reason"] = "This metric is a derived measure that best fits your request."
        elif metric_ref.startswith("user_metric:"):
            detail["reason"] = "This metric comes from your workspace-defined metric library."
        else:
            detail["reason"] = "This metric was selected because it best fits your question."
        metric_details.append(detail)

    filter_details: List[Dict[str, Any]] = []
    for item in filter_rows:
        if not isinstance(item, Mapping):
            continue
        key = _norm_key(item.get("column_key"))
        if key == "":
            continue
        op = str(item.get("op") or "").strip().lower()
        detail: Dict[str, Any] = {
            "column_key": key,
            "label": _column_label_for_explanation(column_key=key, col_lookup=col_lookup),
            "op": op,
            "op_label": _friendly_filter_op(op),
            "reason": "This condition came directly from your question.",
        }
        if "value" in item:
            detail["value"] = item.get("value")
        if "values" in item:
            detail["values"] = item.get("values")
        filter_details.append(detail)

    normalization_notes: List[str] = []
    if list(country_debug or []):
        normalization_notes.append("Country values were standardized (for example, US to United States).")
    if list(school_year_debug or []):
        normalization_notes.append("School-year phrases were converted to the actual school year.")
    if list(semester_debug or []):
        rewrite_count = sum(1 for row in semester_debug if bool((row or {}).get("rewritten_to_indicator")))
        if rewrite_count > 0:
            normalization_notes.append("Semester terms were mapped to your semester indicator fields.")
        else:
            normalization_notes.append("Semester terms were standardized to your configured semester labels.")

    summary_parts = [
        f"I used the '{selected_domain_name}' area because it was the best match for your question.",
    ]
    dim_labels = [
        str(item.get("label") or "").strip()
        for item in dim_details
        if str(item.get("label") or "").strip()
    ]
    if dim_labels:
        summary_parts.append(f"I selected {_human_list(dim_labels)} for the output columns.")
    metric_labels = [
        str(item.get("label") or "").strip()
        for item in metric_details
        if str(item.get("label") or "").strip()
    ]
    if metric_labels:
        summary_parts.append(f"I used {_human_list(metric_labels)} as the metric calculation.")
    filter_phrases = [_friendly_filter_clause(item) for item in filter_details]
    filter_phrases = [item for item in filter_phrases if item]
    if filter_phrases:
        summary_parts.append(f"I applied these conditions: {_human_list(filter_phrases)}.")
    if normalization_notes:
        summary_parts.extend(normalization_notes)

    return {
        "summary": " ".join(summary_parts),
        "domain": {
            "selected_domain_id": int(selected_domain_id),
            "selected_domain_name": selected_domain_name,
            "score": round(score, 5),
            "vector_score": round(vector_score, 5),
            "column_shortlist_count": shortlist_count,
            "reason": "Best overall match to your request, based on intent, wording, and available fields.",
        },
        "dimensions": dim_details,
        "metrics": metric_details,
        "filters": filter_details,
    }


# ---------------------------------------------------------------------------
# Public service class
# ---------------------------------------------------------------------------

class ExplanationService:
    """Builds the deterministic plan explanation object."""

    def __init__(
        self,
        *,
        llm_client: Any | None = None,
        llm_explanation_enabled: Optional[bool] = None,
    ) -> None:
        self._llm = llm_client
        self._llm_explanation_enabled = llm_explanation_enabled

    def build_explanation(
        self,
        *,
        selected_domain_id: int,
        plan_json: dict,
        capabilities: dict,
        domain_candidates: list,
        ranking_debug: list,
        shortlisted_columns: list,
        norm_debug: dict,
    ) -> dict:
        """
        Build and return the plan explanation dict.

        ``norm_debug`` is the ``.debug`` mapping from NormalizationPipeline.
        Keys are normalizer names: ``"country"``, ``"school_year"``, ``"semester"``.
        """
        country_debug = list(norm_debug.get("country") or [])
        school_year_debug = list(norm_debug.get("school_year") or [])
        semester_debug = list(norm_debug.get("semester") or [])
        return _build_plan_explanation(
            selected_domain_id=selected_domain_id,
            plan_json=plan_json,
            capabilities=capabilities,
            domain_candidates=domain_candidates,
            ranking_debug=ranking_debug,
            shortlisted_columns=shortlisted_columns,
            country_debug=country_debug,
            school_year_debug=school_year_debug,
            semester_debug=semester_debug,
        )

    def maybe_polish_summary(
        self,
        *,
        prompt: str,
        explanation: Mapping[str, Any],
    ) -> tuple[dict, Optional[dict]]:
        out = dict(explanation or {})
        fallback_summary = str(out.get("summary") or "").strip()
        out["summary_source"] = "deterministic"
        explanation_enabled = (
            bool(self._llm_explanation_enabled)
            if self._llm_explanation_enabled is not None
            else bool(QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED)
        )
        if not explanation_enabled:
            return out, {"enabled": False, "used": False}
        if fallback_summary == "":
            return out, {"enabled": True, "used": False, "reason": "missing_fallback_summary"}
        if self._llm is None:
            return out, {"enabled": True, "used": False, "reason": "missing_llm_client"}

        payload = {
            "user_question": str(prompt or "").strip(),
            "domain": str(((out.get("domain") or {}).get("selected_domain_name") or "")).strip(),
            "selected_columns": [
                str(item.get("label") or "").strip()
                for item in list(out.get("dimensions") or [])
                if str(item.get("label") or "").strip()
            ],
            "metrics": [
                str(item.get("label") or "").strip()
                for item in list(out.get("metrics") or [])
                if str(item.get("label") or "").strip()
            ],
            "filters": [
                {
                    "field": str(item.get("label") or "").strip(),
                    "operator": str(item.get("op_label") or "").strip(),
                    "value": item.get("value"),
                    "values": item.get("values"),
                }
                for item in list(out.get("filters") or [])
                if isinstance(item, Mapping)
            ],
            "fallback_summary": fallback_summary,
        }

        system_prompt = (
            "You rewrite analytics explanations for educators.\n"
            "Write plain language with no technical jargon, IDs, scores, or internal field keys.\n"
            "Keep it concise: 1-3 sentences.\n"
            "Return strict JSON only: {\"summary\":\"...\"}."
        )
        user_prompt = (
            "Rewrite this explanation into a friendly summary for school staff.\n"
            f"Input JSON:\n{json.dumps(payload, ensure_ascii=True)}"
        )
        try:
            trace = self._llm.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=True,
                max_tokens=QF_PLAN_DOMAIN_LLM_EXPLANATION_MAX_TOKENS,
            )
        except EXPLANATION_LLM_ERRORS as exc:
            logger.warning("planner_domain explanation polish failed err=%s", exc)
            return out, {"enabled": True, "used": False, "error": str(exc)}

        parsed = trace.get("parsed") if isinstance(trace.get("parsed"), Mapping) else {}
        candidate = str((parsed or {}).get("summary") or "").strip()
        candidate = _normalize_explanation_summary(candidate)
        if candidate:
            out["summary"] = candidate
            out["summary_source"] = "llm"

        return out, {
            "enabled": True,
            "used": bool(candidate),
            "error": trace.get("error"),
            "finish_reason": trace.get("finish_reason"),
            "content_preview": str(trace.get("content") or "")[:300],
        }
