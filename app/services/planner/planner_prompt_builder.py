from __future__ import annotations

import json
from typing import Any, Dict, Mapping

from app.services.planner.semantic_candidate_models import SemanticCandidatePayload


def build_compact_semantic_planner_developer_prompt() -> str:
    return (
        "You are a constrained semantic query planner.\n"
        "Return strict JSON only matching the response schema.\n"
        "Never generate SQL.\n"
        "Use only provided candidate concept keys.\n"
        "Never invent concept keys, metrics, dimensions, filters, values, or domains.\n"
        "Prefer NAME/LABEL concepts for grouping when user says 'by X'.\n"
        "Do not add filters unless user asked for a restriction.\n"
        "Do not infer time range or time grain unless user asked for time.\n"
        "If a business term maps to multiple metrics and no default is provided, ask for clarification.\n"
        "Use intent='aggregate' for totals, sums, counts, averages, and grouped 'by' requests.\n"
        "No markdown, prose, code fences, or comments.\n"
    )


def build_compact_semantic_planner_user_prompt(
    *,
    prompt: str,
    normalized_prompt: str,
    workspace_id: str,
    vertical_norm: str,
    candidates: SemanticCandidatePayload,
    conversation_context: Mapping[str, Any],
) -> str:
    domain_obj = candidates.domain.model_dump(mode="json") if candidates.domain is not None else None
    payload = {
        "prompt": str(prompt or "").strip(),
        "normalized_prompt": str(normalized_prompt or "").strip(),
        "workspace_id": str(workspace_id or "").strip(),
        "vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic",
        "base_domain_key": str(candidates.base_domain_key or "").strip() or None,
        "domain": domain_obj,
        "metric_candidates": [_candidate_for_prompt(row) for row in candidates.metric_candidates],
        "dimension_candidates": [_candidate_for_prompt(row) for row in candidates.dimension_candidates],
        "filter_candidates": [_candidate_for_prompt(row) for row in candidates.filter_candidates],
        "time_candidates": [_candidate_for_prompt(row) for row in candidates.time_candidates],
        "lexical_hints": dict(candidates.lexical_hints or {}),
        "planning_rules": list(candidates.planning_rules or []),
        "conversation_context": dict(conversation_context or {}),
    }
    return (
        "Build a compact semantic planning object for this request.\n"
        "Use only provided candidates and lexical hints.\n"
        f"input={json.dumps(payload, ensure_ascii=True)}"
    )


def build_compact_semantic_retry_prompt(
    *,
    previous_output: str,
    candidates: SemanticCandidatePayload,
) -> str:
    payload = {
        "candidate_counts": {
            "metrics": len(candidates.metric_candidates),
            "dimensions": len(candidates.dimension_candidates),
            "filters": len(candidates.filter_candidates),
            "time_fields": len(candidates.time_candidates),
        },
        "base_domain_key": candidates.base_domain_key,
    }
    return (
        "Fix your previous output.\n"
        "Return JSON only with the required schema.\n"
        "Use only candidate semantic concept keys.\n"
        f"context={json.dumps(payload, ensure_ascii=True)}\n"
        f"previous_output={str(previous_output or '')[:16000]}"
    )


def compact_semantic_response_format() -> Dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "base_domain_key",
            "intent",
            "metrics",
            "dimensions",
            "filters",
            "time",
            "needs_clarification",
            "clarification_question",
            "confidence",
        ],
        "properties": {
            "base_domain_key": {"type": ["string", "null"]},
            "intent": {"type": "string", "enum": ["aggregate", "list", "trend"]},
            "metrics": {"type": "array", "items": {"type": "string"}, "minItems": 0},
            "dimensions": {"type": "array", "items": {"type": "string"}, "minItems": 0},
            "filters": {
                "type": "array",
                "minItems": 0,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["field_concept_key", "operator", "value"],
                    "properties": {
                        "field_concept_key": {"type": "string"},
                        "operator": {
                            "type": "string",
                            "enum": ["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "between", "contains"],
                        },
                        "value": {},
                    },
                },
            },
            "time": {
                "type": "object",
                "additionalProperties": False,
                "required": ["time_concept_key", "time_range", "time_grain", "start_date", "end_date"],
                "properties": {
                    "time_concept_key": {"type": ["string", "null"]},
                    "time_range": {"type": ["string", "null"]},
                    "time_grain": {"type": ["string", "null"], "enum": ["day", "week", "month", "quarter", "year", None]},
                    "start_date": {"type": ["string", "null"]},
                    "end_date": {"type": ["string", "null"]},
                },
            },
            "needs_clarification": {"type": "boolean"},
            "clarification_question": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "compact_semantic_plan_v2",
            "strict": True,
            "schema": schema,
        },
    }


def _candidate_for_prompt(row: Any) -> Dict[str, Any]:
    return {
        "concept_key": str(getattr(row, "concept_key", "") or "").strip(),
        "label": str(getattr(row, "label", "") or "").strip(),
        "score": float(getattr(row, "score", 0.0) or 0.0),
    }

