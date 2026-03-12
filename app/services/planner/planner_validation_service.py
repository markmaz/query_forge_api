from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.services.planner.semantic_candidate_models import (
    CompactSemanticFilter,
    CompactSemanticPlan,
    CompactSemanticTime,
    SemanticCandidatePayload,
)

_ALLOWED_FILTER_OPERATORS = {"eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "between", "contains"}
_RELAXED_STOP_TOKENS = {"id", "name", "key", "code", "number", "num", "identifier", "total"}


@dataclass(frozen=True)
class PlannerValidationResult:
    normalized_plan: CompactSemanticPlan
    warnings: List[Dict[str, Any]]
    errors: List[Dict[str, Any]]
    needs_clarification: bool
    clarification_question: Optional[str]


class PlannerValidationService:
    def validate(
        self,
        *,
        plan: CompactSemanticPlan,
        candidates: SemanticCandidatePayload,
    ) -> PlannerValidationResult:
        warnings: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        metric_map = _candidate_map(candidates.metric_candidates)
        dimension_map = _candidate_map(candidates.dimension_candidates)
        filter_map = _candidate_map(candidates.filter_candidates)
        time_map = _candidate_map(candidates.time_candidates)
        domain_map = _candidate_map(candidates.domain_candidates)
        value_map = _value_alias_map(candidates.value_candidates)
        allowed_domain_members = _allowed_domain_members(candidates.metadata)

        resolved_domain_key = _resolve_concept(
            value=plan.base_domain_key,
            candidate_map=domain_map,
            default=str(candidates.base_domain_key or ""),
        )
        if resolved_domain_key == "":
            errors.append(
                {
                    "code": "unknown_domain",
                    "path": "base_domain_key",
                    "message": f"Unknown domain key '{plan.base_domain_key}'",
                }
            )
            resolved_domain_key = str(candidates.base_domain_key or "").strip().upper()

        resolved_metrics: List[str] = []
        for idx, token in enumerate(plan.metrics):
            key = _resolve_concept(value=token, candidate_map=metric_map)
            if key == "":
                errors.append(
                    {
                        "code": "unknown_metric",
                        "path": f"metrics[{idx}]",
                        "message": f"Metric '{token}' is not in semantic candidates",
                    }
                )
                continue
            if _is_restricted_domain_member(allowed_domain_members, key):
                errors.append(
                    {
                        "code": "metric_not_in_domain",
                        "path": f"metrics[{idx}]",
                        "message": f"Metric '{key}' is not allowed in domain '{resolved_domain_key}'",
                    }
                )
                continue
            if key not in resolved_metrics:
                resolved_metrics.append(key)

        resolved_dimensions: List[str] = []
        for idx, token in enumerate(plan.dimensions):
            key = _resolve_concept(value=token, candidate_map=dimension_map)
            if key == "":
                errors.append(
                    {
                        "code": "unknown_dimension",
                        "path": f"dimensions[{idx}]",
                        "message": f"Dimension '{token}' is not in semantic candidates",
                    }
                )
                continue
            if _is_restricted_domain_member(allowed_domain_members, key):
                errors.append(
                    {
                        "code": "dimension_not_in_domain",
                        "path": f"dimensions[{idx}]",
                        "message": f"Dimension '{key}' is not allowed in domain '{resolved_domain_key}'",
                    }
                )
                continue
            if key not in resolved_dimensions:
                resolved_dimensions.append(key)

        resolved_filters: List[CompactSemanticFilter] = []
        for idx, item in enumerate(plan.filters):
            key = _resolve_concept(value=item.field_concept_key, candidate_map=filter_map)
            if key == "":
                errors.append(
                    {
                        "code": "unknown_filter_field",
                        "path": f"filters[{idx}].field_concept_key",
                        "message": f"Filter field '{item.field_concept_key}' is not in semantic candidates",
                    }
                )
                continue
            if _is_restricted_domain_member(allowed_domain_members, key):
                errors.append(
                    {
                        "code": "filter_not_in_domain",
                        "path": f"filters[{idx}].field_concept_key",
                        "message": f"Filter field '{key}' is not allowed in domain '{resolved_domain_key}'",
                    }
                )
                continue
            op = str(item.operator or "").strip().lower()
            if op not in _ALLOWED_FILTER_OPERATORS:
                errors.append(
                    {
                        "code": "invalid_filter_operator",
                        "path": f"filters[{idx}].operator",
                        "message": f"Operator '{item.operator}' is not allowed",
                    }
                )
                continue
            value = _normalize_filter_value(
                concept_key=key,
                value=item.value,
                alias_map=value_map,
            )
            resolved_filters.append(
                CompactSemanticFilter(
                    field_concept_key=key,
                    operator=op,
                    value=value,
                )
            )

        time_block = CompactSemanticTime.model_validate(plan.time.model_dump(mode="json"))
        if time_block.time_concept_key:
            resolved_time_key = _resolve_concept(value=time_block.time_concept_key, candidate_map=time_map)
            if resolved_time_key == "":
                errors.append(
                    {
                        "code": "unknown_time_field",
                        "path": "time.time_concept_key",
                        "message": f"Time field '{time_block.time_concept_key}' is not in semantic candidates",
                    }
                )
            elif _is_restricted_domain_member(allowed_domain_members, resolved_time_key):
                errors.append(
                    {
                        "code": "time_not_in_domain",
                        "path": "time.time_concept_key",
                        "message": f"Time field '{resolved_time_key}' is not allowed in domain '{resolved_domain_key}'",
                    }
                )
            else:
                time_block.time_concept_key = resolved_time_key

        confidence = float(plan.confidence)
        clamped_confidence = max(0.0, min(1.0, confidence))
        if clamped_confidence != confidence:
            warnings.append({"code": "confidence_clamped", "from": confidence, "to": clamped_confidence})

        needs_clarification = bool(plan.needs_clarification) or bool(errors)
        clarification_question = plan.clarification_question
        if needs_clarification and not clarification_question:
            clarification_question = _default_clarification_question(errors, candidates)

        normalized_plan = CompactSemanticPlan(
            base_domain_key=resolved_domain_key or None,
            intent=plan.intent,
            metrics=resolved_metrics,
            dimensions=resolved_dimensions,
            filters=resolved_filters,
            time=time_block,
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            confidence=clamped_confidence,
        )
        return PlannerValidationResult(
            normalized_plan=normalized_plan,
            warnings=warnings,
            errors=errors,
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
        )


def _candidate_map(rows: Sequence[Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    token_to_keys: Dict[str, set[str]] = {}
    relaxed_keys: Dict[str, set[str]] = {}
    for row in rows:
        concept_key = str(getattr(row, "concept_key", "") or "").strip().upper()
        if concept_key == "":
            continue
        _collect_candidate_token(token_to_keys=token_to_keys, token=concept_key, concept_key=concept_key)
        label = str(getattr(row, "label", "") or "").strip()
        if label:
            _collect_candidate_token(token_to_keys=token_to_keys, token=label, concept_key=concept_key)
        for alias in list(getattr(row, "aliases", []) or []):
            token = str(alias or "").strip()
            if token:
                _collect_candidate_token(token_to_keys=token_to_keys, token=token, concept_key=concept_key)
    for token, keys in token_to_keys.items():
        if len(keys) == 1:
            out[token] = next(iter(keys))
            relaxed = _relaxed_key(token)
            if relaxed:
                relaxed_keys.setdefault(relaxed, set()).add(next(iter(keys)))
    for relaxed_token, keys in relaxed_keys.items():
        if len(keys) == 1:
            out.setdefault(relaxed_token, next(iter(keys)))
    return out


def _value_alias_map(rows: Sequence[Any]) -> Dict[Tuple[str, str], Any]:
    out: Dict[Tuple[str, str], Any] = {}
    for row in rows:
        concept_key = str(getattr(row, "field_concept_key", "") or "").strip().upper()
        alias_value = str(getattr(row, "alias_value", "") or "").strip().lower()
        if concept_key == "" or alias_value == "":
            continue
        out[(concept_key, alias_value)] = getattr(row, "canonical_value", None)
    return out


def _resolve_concept(*, value: Optional[str], candidate_map: Mapping[str, str], default: str = "") -> str:
    token = _norm_key(value)
    if token == "":
        return str(default or "").strip().upper()
    matched = str(candidate_map.get(token) or "").strip().upper()
    if matched:
        return matched
    relaxed_token = _relaxed_key(token)
    if relaxed_token:
        matched = str(candidate_map.get(relaxed_token) or "").strip().upper()
        if matched:
            return matched
    return str(default or "").strip().upper()


def _allowed_domain_members(metadata: Mapping[str, Any]) -> set[str]:
    rows = metadata.get("domain_members")
    if not isinstance(rows, list):
        return set()
    out: set[str] = set()
    for item in rows:
        token = str(item or "").strip().upper()
        if token:
            out.add(token)
    return out


def _is_restricted_domain_member(allowed_members: Sequence[str], concept_key: str) -> bool:
    allowed = {str(item or "").strip().upper() for item in allowed_members if str(item or "").strip()}
    if not allowed:
        return False
    return str(concept_key or "").strip().upper() not in allowed


def _normalize_filter_value(*, concept_key: str, value: Any, alias_map: Mapping[Tuple[str, str], Any]) -> Any:
    if isinstance(value, str):
        token = value.strip().lower()
        if token == "":
            return value
        canonical = alias_map.get((str(concept_key or "").strip().upper(), token))
        if canonical is not None:
            return canonical
    if isinstance(value, list):
        return [_normalize_filter_value(concept_key=concept_key, value=item, alias_map=alias_map) for item in value]
    return value


def _default_clarification_question(
    errors: Sequence[Mapping[str, Any]],
    candidates: SemanticCandidatePayload,
) -> str:
    metric_issue = any(str(row.get("code") or "").strip().startswith("unknown_metric") for row in errors)
    dimension_issue = any(str(row.get("code") or "").strip().startswith("unknown_dimension") for row in errors)
    if metric_issue:
        sales_options = list((candidates.lexical_hints or {}).get("sales") or [])
        if len(sales_options) >= 2:
            labels: List[str] = []
            for key in sales_options[:2]:
                label = next(
                    (
                        str(item.label or "").strip()
                        for item in list(candidates.metric_candidates or [])
                        if str(item.concept_key or "").strip().upper() == str(key or "").strip().upper()
                    ),
                    str(key or "").strip(),
                )
                if label:
                    labels.append(label)
            if len(labels) >= 2:
                return f"Did you mean {labels[0]} or {labels[1]}?"
    if metric_issue and dimension_issue:
        return "Can you clarify the metric and grouping fields you want?"
    if metric_issue:
        return "Can you clarify which metric you want?"
    if dimension_issue:
        return "Can you clarify which grouping fields you want?"
    return "Can you clarify your request?"


def _norm_key(value: Any) -> str:
    token = str(value or "").strip().lower()
    token = re.sub(r"[^a-z0-9]+", " ", token).strip()
    return token


def _relaxed_key(value: Any) -> str:
    normalized = _norm_key(value)
    if normalized == "":
        return ""
    parts = [part for part in normalized.split(" ") if part and part not in _RELAXED_STOP_TOKENS]
    if not parts:
        return ""
    return " ".join(parts)


def _collect_candidate_token(
    *,
    token_to_keys: Dict[str, set[str]],
    token: Any,
    concept_key: str,
) -> None:
    normalized = _norm_key(token)
    if normalized:
        token_to_keys.setdefault(normalized, set()).add(concept_key)
