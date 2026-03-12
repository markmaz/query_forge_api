from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.services.planner.semantic_candidate_models import (
    CompactSemanticPlan,
    SemanticCandidatePayload,
)


@dataclass(frozen=True)
class SemanticCompileResult:
    plan_json_v2: Dict[str, Any]
    warnings: List[Dict[str, Any]] = field(default_factory=list)


class SemanticPlanCompiler:
    def compile(
        self,
        *,
        plan: CompactSemanticPlan,
        candidates: SemanticCandidatePayload,
        trace_id: str,
        workspace_id: str,
        vertical_norm: str,
        base_domain_id: int,
        base_domain_name: Optional[str],
    ) -> SemanticCompileResult:
        warnings: List[Dict[str, Any]] = []
        metric_by_key = {row.concept_key: row for row in candidates.metric_candidates}
        dim_by_key = {row.concept_key: row for row in candidates.dimension_candidates}
        filter_by_key = {row.concept_key: row for row in candidates.filter_candidates}
        time_by_key = {row.concept_key: row for row in candidates.time_candidates}

        metric_refs: List[str] = []
        for key in plan.metrics:
            metric_candidate = metric_by_key.get(key)
            ref = str(getattr(metric_candidate, "metric_ref", "") or "").strip()
            if ref and ref not in metric_refs:
                metric_refs.append(ref)
            elif not ref:
                warnings.append(
                    {
                        "code": "metric_ref_unresolved",
                        "message": f"No metric_ref mapping for concept '{key}'",
                    }
                )

        dimension_keys: List[str] = []
        for key in plan.dimensions:
            dimension_candidate = dim_by_key.get(key)
            col_key = str(getattr(dimension_candidate, "source_column_key", "") or "").strip().lower()
            if col_key and col_key not in dimension_keys:
                dimension_keys.append(col_key)
            elif not col_key:
                warnings.append(
                    {
                        "code": "dimension_column_unresolved",
                        "message": f"No source column mapping for dimension '{key}'",
                    }
                )

        filter_rows: List[Dict[str, Any]] = []
        for item in plan.filters:
            filter_candidate = filter_by_key.get(item.field_concept_key)
            col_key = str(getattr(filter_candidate, "source_column_key", "") or "").strip().lower()
            if col_key == "":
                warnings.append(
                    {
                        "code": "filter_column_unresolved",
                        "message": f"No source column mapping for filter '{item.field_concept_key}'",
                    }
                )
                continue
            filter_rows.append(
                {
                    "column_key": col_key,
                    "op": str(item.operator or "").strip().lower(),
                    "value": item.value,
                }
            )

        resolved_time_concept = str(plan.time.time_concept_key or "").strip().upper()
        if resolved_time_concept == "" and _plan_requests_time(plan):
            resolved_time_concept = _default_time_concept_for_plan(plan=plan, candidates=candidates)
        time_candidate = time_by_key.get(resolved_time_concept)
        time_column_key = str(getattr(time_candidate, "source_column_key", "") or "").strip().lower()

        time_block: Dict[str, Any] = {}
        if plan.time.time_range:
            time_block["time_range"] = str(plan.time.time_range).strip()
        if plan.time.time_grain:
            time_block["time_grain"] = str(plan.time.time_grain).strip()
        if plan.time.start_date:
            time_block["start_date"] = str(plan.time.start_date).strip()
        if plan.time.end_date:
            time_block["end_date"] = str(plan.time.end_date).strip()
        if time_column_key:
            time_block["time_column_key"] = time_column_key

        intent = str(plan.intent or "").strip().lower()
        if intent not in {"aggregate", "list", "trend"}:
            intent = "aggregate" if metric_refs else "list"

        grouping_order_by: List[Dict[str, Any]] = []
        if intent == "trend" and time_column_key:
            grouping_order_by.append({"by": time_column_key, "dir": "asc"})

        plan_json_v2 = {
            "schema_version": 2,
            "trace_id": str(trace_id or "").strip(),
            "workspace_id": str(workspace_id or "").strip(),
            "vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic",
            "base_domain_id": int(base_domain_id),
            "domain_name": str(base_domain_name or f"domain_{int(base_domain_id)}").strip() or f"domain_{int(base_domain_id)}",
            "intent": "aggregate" if intent == "trend" and metric_refs else intent,
            "selects": {
                "dimensions": [{"column_key": key} for key in dimension_keys],
                "metrics": [{"metric_ref": ref} for ref in metric_refs],
            },
            "filters": filter_rows,
            "time": time_block,
            "grouping": {
                "group_by": list(dimension_keys),
                "order_by": grouping_order_by,
                "limit": None,
            },
            "debug": None,
        }
        return SemanticCompileResult(plan_json_v2=plan_json_v2, warnings=warnings)


def _default_time_concept_for_plan(
    *,
    plan: CompactSemanticPlan,
    candidates: SemanticCandidatePayload,
) -> str:
    defaults = dict((candidates.metadata or {}).get("default_time_by_metric") or {})
    normalized_defaults = {
        str(k or "").strip().upper(): str(v or "").strip().upper()
        for k, v in defaults.items()
        if str(k or "").strip() and str(v or "").strip()
    }
    metric_keys = {str(item or "").strip().upper() for item in plan.metrics if str(item or "").strip()}
    for metric_key in metric_keys:
        target = normalized_defaults.get(metric_key)
        if target:
            return target
    if candidates.time_candidates:
        return str(candidates.time_candidates[0].concept_key or "").strip().upper()
    return ""


def _plan_requests_time(plan: CompactSemanticPlan) -> bool:
    return bool(
        plan.intent == "trend"
        or plan.time.time_concept_key
        or plan.time.time_range
        or plan.time.time_grain
        or plan.time.start_date
        or plan.time.end_date
    )
