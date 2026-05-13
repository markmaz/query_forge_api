"""Domain candidate retrieval helpers for planner-domain selection."""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.exceptions.forge_error import ForgeError
from app.services.domain.planner_retrieval_policy_service import PlannerRetrievalPolicyService
from app.services.planner_domain.capability_compactor import _to_int
from app.services.planner_domain.prompt_intents import _dedupe_text_items

logger = logging.getLogger(__name__)

DOMAIN_VECTOR_SEARCH_ERRORS = (OSError, RuntimeError, ValueError, UnexpectedResponse, ResponseHandlingException)


def _dedupe_constraints(values: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in values:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "unknown").strip().lower() or "unknown"
        text = " ".join(str(item.get("text") or "").strip().split())
        op = str(item.get("op") or "unknown").strip().lower() or "unknown"
        value_hint = " ".join(str(item.get("value_hint") or "").strip().split()) if item.get("value_hint") not in (None, "") else ""
        notes = " ".join(str(item.get("notes") or "").strip().split()) if item.get("notes") not in (None, "") else ""
        if text == "" and value_hint == "":
            continue
        key = (kind, text.lower(), op, value_hint.lower(), notes.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "kind": kind,
                "text": text or value_hint,
                "op": op,
                "value_hint": value_hint or None,
                "notes": notes or None,
            }
        )
    return out


def _semantic_alias_concept_key(constraint: Mapping[str, Any]) -> str:
    notes = str(constraint.get("notes") or "").strip()
    if ":" not in notes:
        return ""
    prefix, concept_key = notes.split(":", 1)
    if prefix.strip().lower() != "semantic_alias":
        return ""
    return str(concept_key or "").strip().upper()


def _replace_prompt_phrase(*, text: str, needle: str, replacement: str) -> str:
    base = str(text or "").strip()
    source = str(needle or "").strip()
    target = str(replacement or "").strip()
    if base == "" or source == "" or target == "":
        return base
    pattern = re.compile(rf"\b{re.escape(source)}\b", flags=re.IGNORECASE)
    rewritten = pattern.sub(target, base, count=1)
    return " ".join(rewritten.split())


def _semantic_constraint_concept_keys(semantic_constraints: Sequence[Mapping[str, Any]]) -> List[str]:
    constraints = _dedupe_constraints(semantic_constraints)
    out: List[str] = []
    for concept_key in (_semantic_alias_concept_key(item) for item in constraints):
        if concept_key and concept_key not in out:
            out.append(concept_key)
    return out


def _build_semantic_alias_domain_query_specs(
    *,
    prompt: str,
    semantic_constraints: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    text = str(prompt or "").strip()
    if text == "":
        return []
    constraints = _dedupe_constraints(semantic_constraints)
    if not constraints:
        return []

    specs: List[Dict[str, Any]] = []
    for constraint in constraints:
        raw_text = str(constraint.get("text") or "").strip()
        canonical = str(constraint.get("value_hint") or "").strip()
        if raw_text == "" or canonical == "" or raw_text.lower() == canonical.lower():
            continue
        rewritten_prompt = _replace_prompt_phrase(text=text, needle=raw_text, replacement=canonical)
        if rewritten_prompt and rewritten_prompt != text:
            concept_key = _semantic_alias_concept_key(constraint)
            reason = f"semantic_alias:{concept_key}" if concept_key else "semantic_alias"
            specs.append(
                {
                    "query": rewritten_prompt,
                    "score_boost": 0.02,
                    "reasons": [reason],
                    "source": "semantic_vector",
                }
            )

    return specs


def _merge_domain_query_specs(
    *,
    specs: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for raw_spec in specs:
        query_text = " ".join(str(raw_spec.get("query") or "").strip().split())
        if query_text == "":
            continue
        key = query_text.lower()
        reasons = _dedupe_text_items(list(raw_spec.get("reasons") or []))
        score_boost = float(raw_spec.get("score_boost") or 0.0)
        source = str(raw_spec.get("source") or "vector")
        existing = merged.get(key)
        if existing is None:
            merged[key] = {
                "query": query_text,
                "score_boost": score_boost,
                "reasons": reasons,
                "source": source,
            }
            continue
        existing["score_boost"] = max(float(existing.get("score_boost") or 0.0), score_boost)
        existing["reasons"] = _dedupe_text_items(list(existing.get("reasons") or []) + reasons)
        if source != "vector":
            existing["source"] = source
    return list(merged.values())


def get_domain_candidates(
    *,
    workspace_id: str,
    prompt: str,
    provided_domain_id: Optional[int],
    search_domains_fn: Callable[..., Mapping[str, Any]],
    semantic_alias_constraints_fn: Callable[..., List[Dict[str, Any]]],
    extract_prompt_signals_fn: Callable[..., List[str]],
    retrieval_policy_service: PlannerRetrievalPolicyService,
) -> List[Dict[str, Any]]:
    provided = _to_int(provided_domain_id)
    if provided is not None and provided > 0:
        return [{"domain_id": provided, "name": f"domain_{provided}", "score": 1.0, "source": "provided"}]

    semantic_constraints = semantic_alias_constraints_fn(prompt=prompt)
    prompt_signals = extract_prompt_signals_fn(prompt=prompt)
    semantic_concept_keys = _semantic_constraint_concept_keys(semantic_constraints)
    query_specs = _merge_domain_query_specs(
        specs=[
            {
                "query": prompt,
                "score_boost": 0.0,
                "reasons": [],
                "source": "vector",
            },
            *retrieval_policy_service.build_query_specs(
                workspace_id=workspace_id,
                prompt_signals=prompt_signals,
                semantic_concept_keys=semantic_concept_keys,
            ),
            *_build_semantic_alias_domain_query_specs(
                prompt=prompt,
                semantic_constraints=semantic_constraints,
            ),
        ],
    )
    rows: List[Dict[str, Any]] = []
    vector_failures: List[str] = []
    for query_spec in query_specs:
        query_text = str(query_spec.get("query") or "").strip()
        if query_text == "":
            continue
        try:
            result = search_domains_fn(
                workspace_id=workspace_id,
                query=query_text,
                limit=6,
                score_threshold=0.0,
                include_payload=False,
            )
        except DOMAIN_VECTOR_SEARCH_ERRORS as exc:
            vector_failures.append(type(exc).__name__)
            logger.warning(
                "domain candidate vector search failed workspace_id=%s query_source=%s error=%s",
                workspace_id,
                str(query_spec.get("source") or "vector"),
                exc,
            )
            continue
        semantic_boost = float(query_spec.get("score_boost") or 0.0)
        semantic_reasons = list(query_spec.get("reasons") or [])
        query_source = str(query_spec.get("source") or "vector")
        for row in list(result.get("results") or []):
            if not isinstance(row, dict):
                continue
            merged_row = dict(row)
            merged_row["_semantic_boost"] = semantic_boost
            merged_row["_semantic_reasons"] = semantic_reasons
            merged_row["_query_source"] = query_source
            rows.append(merged_row)
    out: List[Dict[str, Any]] = []
    by_domain: Dict[int, Dict[str, Any]] = {}
    seen: set[int] = set()
    for row in rows:
        domain_id = _to_int(row.get("domain_id"))
        if domain_id is None:
            continue
        candidate_name = str(row.get("name") or f"domain_{domain_id}")
        name_bias = retrieval_policy_service.score_domain_name_bias(
            workspace_id=workspace_id,
            prompt_signals=prompt_signals,
            candidate_name=candidate_name,
        )
        current_score = float(row.get("score") or 0.0) + float(row.get("_semantic_boost") or 0.0) + float(name_bias or 0.0)
        query_reasons = _dedupe_text_items(
            [
                *list(row.get("reason") or []),
                *list(row.get("_semantic_reasons") or []),
            ]
        )
        query_source = str(row.get("_query_source") or "vector")
        existing = by_domain.get(domain_id)
        if existing is None:
            by_domain[domain_id] = {
                "domain_id": domain_id,
                "name": candidate_name,
                "score": current_score,
                "reason": query_reasons,
                "source": query_source,
            }
            continue
        existing_reasons = list(existing.get("reason") or [])
        new_reasons = query_reasons
        existing["reason"] = _dedupe_text_items(existing_reasons + new_reasons)
        if current_score > float(existing.get("score") or 0.0):
            existing["score"] = current_score
            existing["name"] = candidate_name or str(existing.get("name") or f"domain_{domain_id}")
            existing["source"] = query_source
    for domain_id, row in by_domain.items():
        if domain_id in seen:
            continue
        seen.add(domain_id)
        out.append(dict(row))
    out.sort(key=lambda item: (-float(item.get("score") or 0.0), int(item.get("domain_id") or 0)))
    out = out[:6]
    if not out:
        if vector_failures:
            raise ForgeError(
                "Domain vector search is temporarily unavailable",
                status_code=503,
                details={
                    "reason": "domain_vector_search_failed",
                    "failure_count": len(vector_failures),
                    "failure_types": sorted(set(vector_failures)),
                },
            )
        raise ForgeError("No candidate domain found for prompt", status_code=404)
    return out
