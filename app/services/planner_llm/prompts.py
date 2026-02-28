from __future__ import annotations

import json
from typing import Any, Dict, Sequence


PLAN_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["intent", "grain", "selects", "filters", "domains", "aggregation", "derived_metrics"],
    "properties": {
        "intent": {"type": "string", "enum": ["aggregate", "list", "trend"]},
        "grain": {
            "type": "object",
            "required": ["entity", "time_grain"],
            "properties": {
                "entity": {"type": "string"},
                "time_grain": {"type": ["string", "null"], "enum": ["day", "week", "month", "quarter", "year", None]},
            },
        },
        "selects": {
            "type": "object",
            "required": ["metrics", "dimensions"],
            "properties": {
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["metric_ref", "kind"],
                        "properties": {
                            "metric_ref": {
                                "type": "string",
                                "description": "column:<column_key> OR derived:<derived_metric_name>",
                            },
                            "column_key": {
                                "type": "string",
                                "description": "deprecated; validator converts to metric_ref=column:<column_key>",
                            },
                            "kind": {"type": "string", "enum": ["count", "numeric", "ratio", "categorical"]},
                            "agg": {
                                "type": ["string", "null"],
                                "enum": ["count", "count_distinct", "sum", "avg", "min", "max", None],
                            },
                            "label": {"type": "string"},
                        },
                    },
                },
                "dimensions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["column_key"],
                        "properties": {
                            "column_key": {"type": "string"},
                            "label": {"type": "string"},
                        },
                    },
                },
            },
        },
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["column_key", "op", "value"],
                "properties": {
                    "column_key": {"type": "string"},
                    "op": {
                        "type": "string",
                        "enum": [
                            "equals",
                            "not_equals",
                            "contains",
                            "starts_with",
                            "in",
                            "not_in",
                            "gt",
                            "gte",
                            "lt",
                            "lte",
                            "between",
                            "is_null",
                            "is_not_null",
                        ],
                    },
                    "value": {},
                },
            },
        },
        "domains": {
            "type": "array",
            "items": {"type": "integer"},
        },
        "aggregation": {
            "type": "object",
            "required": ["group_by", "metrics"],
            "properties": {
                "group_by": {"type": "array", "items": {"type": "string"}},
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["metric_ref", "label"],
                        "properties": {
                            "metric_ref": {
                                "type": "string",
                                "description": "column:<column_key> OR derived:<derived_metric_name>",
                            },
                            "column_key": {
                                "type": "string",
                                "description": "deprecated; validator converts to metric_ref=column:<column_key>",
                            },
                            "agg": {
                                "type": ["string", "null"],
                                "enum": ["count", "count_distinct", "sum", "avg", "min", "max", None],
                            },
                            "label": {"type": "string"},
                        },
                    },
                },
            },
        },
        "derived_metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "kind", "numerator", "denominator"],
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": ["ratio"]},
                    "numerator": {
                        "type": "object",
                        "required": ["column_key", "agg"],
                        "properties": {
                            "column_key": {"type": "string"},
                            "agg": {"type": "string", "enum": ["count", "count_distinct", "sum", "avg", "min", "max"]},
                        },
                    },
                    "denominator": {
                        "type": "object",
                        "required": ["column_key", "agg"],
                        "properties": {
                            "column_key": {"type": "string"},
                            "agg": {"type": "string", "enum": ["count", "count_distinct", "sum", "avg", "min", "max"]},
                        },
                    },
                    "safe_divide": {"type": "boolean"},
                },
            },
        },
    },
}


def build_system_prompt() -> str:
    return (
        "You are a query planner that outputs STRICT JSON only. "
        "Never include prose, markdown, comments, or code fences."
    )


def build_developer_prompt(schema: Dict[str, Any]) -> str:
    return (
        "Follow this JSON schema exactly and only use provided candidate ids/keys.\n"
        "Rules:\n"
        "- intent must be aggregate|list|trend.\n"
        "- Use typed filter operators from the allowed enum.\n"
        "- Metrics must use metric_ref: column:<column_key> or derived:<derived_metric_name>.\n"
        "- For ratio/rate/per prompts, you MUST create derived_metrics and MUST select it via metric_ref=derived:<name>.\n"
        "- Do not use avg/sum/min/max on id/code/string columns.\n"
        "- For derived metrics, agg must be null in selects/aggregation metrics.\n"
        "- For trend intent, include grain.time_grain.\n"
        "- Output JSON object only.\n"
        f"Schema:\n{json.dumps(schema, ensure_ascii=True)}"
    )


def build_user_prompt(
    *,
    normalized_prompt: str,
    candidates: Dict[str, Sequence[Dict[str, Any]]],
    schema: Dict[str, Any],
) -> str:
    return (
        "Build a planner JSON.\n"
        f"normalized_prompt: {normalized_prompt}\n"
        f"domains: {json.dumps(list(candidates.get('domains') or []), ensure_ascii=True)}\n"
        f"concepts: {json.dumps(list(candidates.get('concepts') or []), ensure_ascii=True)}\n"
        f"columns: {json.dumps(list(candidates.get('columns') or []), ensure_ascii=True)}\n"
        f"schema: {json.dumps(schema, ensure_ascii=True)}\n"
        "Output JSON only."
    )


def build_json_repair_prompt(*, schema: Dict[str, Any], broken_json: str) -> str:
    return (
        "Fix the JSON to match the schema exactly. Output JSON only.\n"
        f"Schema: {json.dumps(schema, ensure_ascii=True)}\n"
        f"Broken JSON: {broken_json[:8000]}"
    )


__all__ = [
    "PLAN_JSON_SCHEMA",
    "build_system_prompt",
    "build_developer_prompt",
    "build_user_prompt",
    "build_json_repair_prompt",
]
