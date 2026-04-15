from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict


class SoftConstraint(BaseModel):
    type: Optional[str] = None
    text: Optional[str] = None
    hints: List[str] = []

    model_config = ConfigDict(extra="allow")


class HardFilter(BaseModel):
    column_key: Optional[str] = None
    op: Optional[str] = None
    value: Any = None
    value_type: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class QueryIntent(BaseModel):
    subject: Optional[str] = None
    action: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class NlpResponse(BaseModel):
    workspace_id: Optional[str] = None
    text: Optional[str] = None
    normalized_text: Optional[str] = None
    domain_hints: List[Any] = []
    hard_filters: List[HardFilter] = []
    filters: List[HardFilter] = []
    soft_constraints: List[SoftConstraint] = []
    query_intent: Optional[QueryIntent] = None
    intent: Optional[str] = None
    entities: List[Any] = []

    model_config = ConfigDict(extra="allow")


def build_vector_search_request(
    nlp: dict,
    *,
    limit: int = 20,
    min_score: float = 0.2,
    max_domains: int = 1,
) -> Dict[str, Any]:
    parsed = NlpResponse.model_validate(nlp or {})
    workspace_id = parsed.workspace_id

    domain_ids = _select_domain_ids(parsed.domain_hints, max_domains=max_domains)

    query_text = _select_query_text(parsed)
    expanded_text = _select_expanded_text(parsed)

    hard_filters = _normalize_filters(parsed.hard_filters or parsed.filters)
    exclude_column_keys = [f["column_key"] for f in hard_filters if f.get("column_key")]

    action = _infer_action(parsed)
    prefer_column_kinds = _prefer_column_kinds(action)

    return {
        "workspace_id": workspace_id,
        "domain_ids": domain_ids,
        "query": {
            "text": query_text,
            "expanded_text": expanded_text,
        },
        "targets": ["COLUMN", "TABLE"],
        "hard_filters": hard_filters,
        "constraints": {
            "exclude_column_keys": exclude_column_keys,
            "prefer_column_kinds": prefer_column_kinds,
        },
        "limit": limit,
        "min_score": min_score,
        "include_payload": True,
        "include_vectors": False,
        "trace": {"caller": "nlp.extract"},
    }


def _select_domain_ids(domain_hints: Sequence[Any], *, max_domains: int) -> List[int]:
    if not domain_hints or max_domains <= 0:
        return []

    scored: List[Tuple[int, float, int]] = []
    for idx, item in enumerate(domain_hints):
        if isinstance(item, dict):
            raw_id = item.get("domain_id") or item.get("domainId") or item.get("id")
            confidence = item.get("confidence")
        else:
            raw_id = item
            confidence = None

        try:
            domain_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        score = float(confidence) if confidence is not None else 0.0
        scored.append((domain_id, score, idx))

    if not scored:
        return []

    scored.sort(key=lambda item: (-item[1], item[2]))
    return [domain_id for domain_id, _score, _idx in scored[:max_domains]]


def _select_query_text(nlp: NlpResponse) -> str:
    preference = _first_output_preference(nlp.soft_constraints)
    if preference and preference.text:
        return preference.text
    return nlp.normalized_text or nlp.text or ""


def _select_expanded_text(nlp: NlpResponse) -> List[str]:
    preference = _first_output_preference(nlp.soft_constraints)
    if preference and preference.hints:
        return _dedupe(preference.hints)

    subject = _infer_subject(nlp)
    action = _infer_action(nlp)

    expansions: List[str] = []
    if subject == "course":
        expansions.extend(["course name", "course code", "course title"])
    elif subject == "student":
        expansions.extend(["student name", "student id", "grade level", "school"])

    if action == "COUNT":
        expansions.extend(["count", "number of"])

    return _dedupe(expansions)


def _first_output_preference(constraints: Sequence[SoftConstraint]) -> Optional[SoftConstraint]:
    for constraint in constraints:
        if (constraint.type or "").upper() == "OUTPUT_PREFERENCE":
            return constraint
    return None


def _normalize_filters(filters: Sequence[HardFilter]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for filt in filters:
        if not filt.column_key:
            continue
        cleaned.append(
            {
                "column_key": filt.column_key,
                "op": filt.op,
                "value": filt.value,
                "value_type": filt.value_type,
            }
        )
    return cleaned


def _infer_action(nlp: NlpResponse) -> Optional[str]:
    if nlp.query_intent and nlp.query_intent.action:
        return nlp.query_intent.action
    if nlp.intent:
        return nlp.intent
    return None


def _infer_subject(nlp: NlpResponse) -> Optional[str]:
    if nlp.query_intent and nlp.query_intent.subject:
        return nlp.query_intent.subject
    for entity in nlp.entities:
        value = str(entity).lower()
        if value in {"course", "student"}:
            return value
    return None


def _prefer_column_kinds(action: Optional[str]) -> List[str]:
    if action == "LIST":
        return ["NAME", "TITLE", "CODE", "DIMENSION"]
    if action == "COUNT":
        return ["MEASURE", "DIMENSION"]
    return []


def _dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in values:
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
