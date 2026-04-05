from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.services.planner.semantic_candidate_models import (
    SemanticCandidatePayload,
    SemanticConceptCandidate,
    SemanticValueCandidate,
)

_NON_WORD_RE = re.compile(r"[^a-zA-Z0-9]+")
_WORD_RE = re.compile(r"[a-z0-9]+")

_METRIC_TYPES = {"metric", "measure"}
_DIMENSION_TYPES = {"dimension", "identifier", "attribute"}
_FILTER_TYPES = {"filter", "dimension", "attribute"}
_TIME_TYPES = {"time_field"}
_NAME_HINT_RE = re.compile(r"\b(name|label|title)\b", re.IGNORECASE)
_GROUP_BY_ENTITY_RE = re.compile(
    r"\bby\s+(?P<entity>[a-z][a-z0-9_\s]{1,40})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConceptRow:
    concept_id: int
    concept_key: str
    name: str
    description: str
    semantic_type: str


@dataclass(frozen=True)
class AliasRule:
    alias: str
    alias_token: str
    weight: float
    match_kind: str


@dataclass(frozen=True)
class CapabilityIndex:
    metric_rows: List[Dict[str, Any]]
    dimension_rows: List[Dict[str, Any]]
    filter_rows: List[Dict[str, Any]]
    time_rows: List[Dict[str, Any]]
    metric_alias_to_ref: Dict[str, str]
    column_by_workspace_id: Dict[int, str]
    column_by_model_id: Dict[int, str]
    column_alias_to_key: Dict[str, str]


def build_capability_index(
    *,
    capabilities_compact: Mapping[str, Any],
) -> CapabilityIndex:
    metric_rows: List[Dict[str, Any]] = []
    metric_alias_to_ref: Dict[str, str] = {}

    def _register_metric_row(
        row: Mapping[str, Any],
        metric_ref: str,
        default_label: str,
    ) -> None:
        metric_rows.append(
            {"metric_ref": metric_ref, "label": default_label, "raw": dict(row)}
        )
        for alias in {
            metric_ref,
            default_label,
            str(row.get("metric_key") or ""),
            str(row.get("label") or ""),
            str(row.get("metric_id") or ""),
            str(row.get("id") or ""),
            metric_ref.split(":", 1)[-1],
        }:
            token = norm_token(alias)
            if token:
                metric_alias_to_ref[token] = metric_ref

    for row in list(capabilities_compact.get("domain_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        metric_key = norm_token(row.get("metric_key"))
        if metric_key == "":
            continue
        metric_ref = f"domain_metric:{metric_key}"
        _register_metric_row(row, metric_ref, str(row.get("label") or metric_key))
    for row in list(capabilities_compact.get("user_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        metric_key = norm_token(row.get("metric_id") or row.get("id"))
        if metric_key == "":
            continue
        metric_ref = f"user_metric:{metric_key}"
        _register_metric_row(row, metric_ref, str(row.get("label") or metric_key))
    for row in list(capabilities_compact.get("overlay_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        metric_key = norm_token(row.get("overlay_key") or row.get("id"))
        if metric_key == "":
            continue
        metric_ref = f"overlay:{metric_key}"
        _register_metric_row(row, metric_ref, str(row.get("label") or metric_key))

    dimension_rows = [
        dict(row)
        for row in list(capabilities_compact.get("dimensions") or [])
        if isinstance(row, Mapping)
    ]
    filter_rows = [
        dict(row)
        for row in list(capabilities_compact.get("filter_columns") or [])
        if isinstance(row, Mapping)
    ]
    time_rows = [
        dict(row)
        for row in list(capabilities_compact.get("time_columns") or [])
        if isinstance(row, Mapping)
    ]

    column_by_workspace_id: Dict[int, str] = {}
    column_by_model_id: Dict[int, str] = {}
    column_alias_to_key: Dict[str, str] = {}
    for row in dimension_rows + filter_rows + time_rows:
        key = column_key(row)
        if key == "":
            continue
        workspace_id = to_int(row.get("workspace_column_id"))
        if workspace_id is not None and workspace_id not in column_by_workspace_id:
            column_by_workspace_id[workspace_id] = key
        model_id = to_int(row.get("model_column_id"))
        if model_id is not None and model_id not in column_by_model_id:
            column_by_model_id[model_id] = key
        for alias in {
            key,
            str(row.get("column_name") or ""),
            str(row.get("label") or ""),
            key.split(".", 1)[-1],
        }:
            token = norm_token(alias)
            if token and token not in column_alias_to_key:
                column_alias_to_key[token] = key

    return CapabilityIndex(
        metric_rows=metric_rows,
        dimension_rows=dimension_rows,
        filter_rows=filter_rows,
        time_rows=time_rows,
        metric_alias_to_ref=metric_alias_to_ref,
        column_by_workspace_id=column_by_workspace_id,
        column_by_model_id=column_by_model_id,
        column_alias_to_key=column_alias_to_key,
    )


def fallback_candidates_from_capabilities(
    *,
    prompt: str,
    workspace_id: str,
    base_domain_id: int,
    base_domain_name: Optional[str],
    vertical_norm: str,
    capability_index: CapabilityIndex,
) -> SemanticCandidatePayload:
    domain_key = domain_key_from_name(base_domain_name, base_domain_id)
    domain_candidate = SemanticConceptCandidate(
        concept_key=domain_key,
        label=str(base_domain_name or f"domain_{base_domain_id}"),
        score=1.0,
        semantic_type="domain",
    )
    metric_candidates = [
        SemanticConceptCandidate(
            concept_key=concept_key_from_metric_ref(row["metric_ref"]),
            label=str(row.get("label") or row["metric_ref"]),
            metric_ref=str(row["metric_ref"]),
            semantic_type="metric",
            score=0.7,
            aliases=[str(row["metric_ref"])],
            domain_key=domain_key,
        )
        for row in capability_index.metric_rows[:30]
    ]
    dimension_candidates = [
        SemanticConceptCandidate(
            concept_key=concept_key(str(row.get("column_name") or column_key(row))),
            label=str(row.get("label") or row.get("column_name") or column_key(row)),
            source_column_key=column_key(row),
            semantic_type="dimension",
            score=0.65,
            domain_key=domain_key,
        )
        for row in capability_index.dimension_rows[:30]
        if column_key(row)
    ]
    filter_candidates = [
        SemanticConceptCandidate(
            concept_key=concept_key(str(row.get("column_name") or column_key(row))),
            label=str(row.get("label") or row.get("column_name") or column_key(row)),
            source_column_key=column_key(row),
            semantic_type="filter",
            score=0.65,
            domain_key=domain_key,
        )
        for row in capability_index.filter_rows[:30]
        if column_key(row)
    ]
    time_candidates = [
        SemanticConceptCandidate(
            concept_key=concept_key(str(row.get("column_name") or column_key(row))),
            label=str(row.get("label") or row.get("column_name") or column_key(row)),
            source_column_key=column_key(row),
            semantic_type="time_field",
            score=0.65,
            domain_key=domain_key,
        )
        for row in capability_index.time_rows[:12]
        if column_key(row)
    ]
    return SemanticCandidatePayload(
        prompt=prompt,
        normalized_prompt=prompt,
        workspace_id=workspace_id,
        vertical_norm=str(vertical_norm or "generic").strip().lower() or "generic",
        base_domain_id=int(base_domain_id),
        base_domain_key=domain_key,
        domain=domain_candidate,
        domain_candidates=[domain_candidate],
        metric_candidates=metric_candidates,
        dimension_candidates=dimension_candidates,
        filter_candidates=filter_candidates,
        time_candidates=time_candidates,
        value_candidates=[],
        lexical_hints={},
        planning_rules=[
            "Use only candidate semantic concept keys.",
            "Do not invent fields or metrics.",
            "If ambiguous, request clarification.",
        ],
        metadata={
            "semantic_source": "capabilities_fallback",
            "domain_members": [domain_key],
            "default_time_by_metric": {},
        },
    )


def build_domain_candidates(
    *,
    concept_rows: Mapping[str, ConceptRow],
    alias_rules_by_key: Mapping[str, Sequence[AliasRule]],
    prompt: str,
    base_domain_name: Optional[str],
    max_items: int,
) -> List[SemanticConceptCandidate]:
    rows: List[SemanticConceptCandidate] = []
    domain_hint = norm_token(base_domain_name)
    for concept in concept_rows.values():
        if concept.semantic_type != "domain":
            continue
        score = concept_match_score(
            prompt=prompt,
            concept_key=concept.concept_key,
            concept_name=concept.name,
            aliases=alias_rules_by_key.get(concept.concept_key, []),
        )
        if domain_hint and (
            domain_hint in norm_token(concept.concept_key)
            or domain_hint in norm_token(concept.name)
        ):
            score = min(1.0, score + 0.35)
        rows.append(
            SemanticConceptCandidate(
                concept_key=concept.concept_key,
                label=concept.name,
                score=score,
                description=concept.description or None,
                semantic_type="domain",
                aliases=[
                    item.alias for item in alias_rules_by_key.get(concept.concept_key, [])
                ],
            )
        )
    return sort_candidates(rows)[: max(1, min(5, max_items))]


def normalize_value_candidates(
    *,
    rows: Sequence[Mapping[str, Any]],
    concept_id_to_key: Mapping[int, str],
    max_items: int,
) -> List[SemanticValueCandidate]:
    out: List[SemanticValueCandidate] = []
    seen: set[Tuple[str, str]] = set()
    for row in rows:
        concept_id = to_int(row.get("semantic_concept_id"))
        if concept_id is None:
            continue
        concept_key = concept_id_to_key.get(concept_id)
        if not concept_key:
            continue
        alias_value = str(row.get("alias_value") or "").strip()
        if alias_value == "":
            continue
        key = (concept_key, alias_value.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            SemanticValueCandidate(
                field_concept_key=concept_key,
                alias_value=alias_value,
                canonical_value=row.get("canonical_value"),
                score=min(1.0, max(0.0, float(row.get("weight") or 0.0))),
            )
        )
    out.sort(key=lambda item: item.score, reverse=True)
    return out[:max_items]


def concept_match_score(
    *,
    prompt: str,
    concept_key: str,
    concept_name: str,
    aliases: Sequence[AliasRule],
) -> float:
    score = 0.0
    text = norm_text(prompt)
    ngrams = set(build_ngrams(prompt))
    concept_token = norm_token(concept_key.replace("_", " "))
    name_token = norm_token(concept_name)
    if concept_token and concept_token in text:
        score += 0.55
    if name_token and name_token in text:
        score += 0.5
    for alias_rule in aliases:
        alias_token = alias_rule.alias_token
        if alias_token == "":
            continue
        weight_boost = max(0.5, min(float(alias_rule.weight or 1.0), 3.0))
        if alias_rule.match_kind == "exact":
            if alias_token in ngrams:
                score += 0.8 * weight_boost
            continue
        if alias_rule.match_kind == "normalized":
            if alias_token in ngrams:
                score += 0.75 * weight_boost
            continue
        if alias_rule.match_kind == "prefix":
            if any(token.startswith(alias_token) for token in ngrams):
                score += 0.6 * weight_boost
            continue
        if alias_rule.match_kind == "suffix":
            if any(token.endswith(alias_token) for token in ngrams):
                score += 0.45 * weight_boost
            continue
        if alias_rule.match_kind == "regex":
            if regex_matches(alias_rule.alias, prompt):
                score += 0.5 * weight_boost
            continue
        if alias_token in text:
            score += 0.4 * weight_boost
    concept_terms = set(_WORD_RE.findall(concept_token))
    prompt_terms = set(_WORD_RE.findall(text))
    overlap = len(concept_terms.intersection(prompt_terms))
    if overlap > 0:
        score += min(0.3, overlap * 0.08)
    return max(0.0, min(1.0, score))


def resolve_metric_ref(
    *,
    concept_key: str,
    concept_name: str,
    aliases: Sequence[str],
    capability_index: CapabilityIndex,
) -> Optional[str]:
    alias_tokens = [concept_key, concept_name, *list(aliases or [])]
    for alias in alias_tokens:
        token = norm_token(alias)
        if token and token in capability_index.metric_alias_to_ref:
            return capability_index.metric_alias_to_ref[token]
    return None


def resolve_source_column_key(
    *,
    concept_key: str,
    concept_name: str,
    aliases: Sequence[str],
    mappings: Sequence[Tuple[Optional[int], Optional[int], float, str]],
    capability_rows: Sequence[Mapping[str, Any]],
    capability_index: CapabilityIndex,
) -> Optional[str]:
    for workspace_column_id, model_column_id, _weight, _rel_kind in mappings:
        if (
            workspace_column_id is not None
            and workspace_column_id in capability_index.column_by_workspace_id
        ):
            return capability_index.column_by_workspace_id[workspace_column_id]
        if (
            model_column_id is not None
            and model_column_id in capability_index.column_by_model_id
        ):
            return capability_index.column_by_model_id[model_column_id]

    candidates = [concept_key, concept_name, *list(aliases or [])]
    for item in candidates:
        token = norm_token(item)
        if token and token in capability_index.column_alias_to_key:
            key = capability_index.column_alias_to_key[token]
            if any(column_key(row) == key for row in capability_rows):
                return key
    return None


def prune_role_clean_candidates(
    *,
    prompt: str,
    metric_candidates: Sequence[SemanticConceptCandidate],
    dimension_candidates: Sequence[SemanticConceptCandidate],
    filter_candidates: Sequence[SemanticConceptCandidate],
    time_candidates: Sequence[SemanticConceptCandidate],
    essential_dimension_candidates: Sequence[SemanticConceptCandidate],
    min_score: float,
    max_metrics: int,
    max_dims: int,
    max_filters: int,
    max_times: int,
) -> Tuple[
    List[SemanticConceptCandidate],
    List[SemanticConceptCandidate],
    List[SemanticConceptCandidate],
    List[SemanticConceptCandidate],
]:
    essentials = {
        str(row.concept_key or "").strip().upper()
        for row in essential_dimension_candidates
    }
    metrics = dedupe_concept_candidates(metric_candidates)
    dims = dedupe_concept_candidates(dimension_candidates)
    filters = dedupe_concept_candidates(filter_candidates)
    times = dedupe_concept_candidates(time_candidates)

    metrics = [
        row
        for row in metrics
        if row.metric_ref
        and (is_metric_semantic_type(row.semantic_type) or looks_metric_like(row))
        and (row.score > min_score)
    ]
    dims = [
        row
        for row in dims
        if row.source_column_key
        and (
            is_dimension_semantic_type(row.semantic_type)
            or looks_dimension_like(row)
        )
        and (row.score > min_score or row.concept_key in essentials)
    ]
    filters = [
        row
        for row in filters
        if row.source_column_key
        and (is_filter_semantic_type(row.semantic_type) or looks_filter_like(row))
        and (row.score > min_score)
    ]
    times = [
        row
        for row in times
        if row.source_column_key
        and is_time_semantic_type(row.semantic_type)
        and (row.score > min_score)
    ]

    metric_keys = {row.concept_key for row in metrics}
    dim_by_key = {row.concept_key: row for row in dims if row.concept_key not in metric_keys}
    filter_by_key = {
        row.concept_key: row for row in filters if row.concept_key not in metric_keys
    }
    overlap = set(dim_by_key.keys()).intersection(filter_by_key.keys())
    prompt_norm = norm_text(prompt)
    for key in overlap:
        dim_row = dim_by_key.get(key)
        filter_row = filter_by_key.get(key)
        if dim_row is None or filter_row is None:
            continue
        keep_dimension = prefer_dimension_over_filter(
            prompt_norm=prompt_norm,
            dimension=dim_row,
            filter_candidate=filter_row,
        )
        if keep_dimension:
            filter_by_key.pop(key, None)
        else:
            dim_by_key.pop(key, None)

    for row in essential_dimension_candidates:
        key = str(row.concept_key or "").strip().upper()
        if key and key not in dim_by_key and key not in metric_keys:
            dim_by_key[key] = row

    dims = sort_candidates(list(dim_by_key.values()))[:max_dims]
    filters = sort_candidates(list(filter_by_key.values()))[:max_filters]
    metrics = sort_candidates(metrics)[:max_metrics]
    times = sort_candidates(times)[:max_times]
    return metrics, dims, filters, times


def backfill_domain_essential_dimensions(
    *,
    prompt: str,
    domain_members: Sequence[str],
    all_dimension_candidates: Sequence[SemanticConceptCandidate],
    max_dimension_candidates: int,
) -> List[SemanticConceptCandidate]:
    prompt_text = str(prompt or "").strip().lower()
    if " by " not in f" {prompt_text} ":
        return []
    requested_entities = extract_group_by_entities(prompt_text)
    if not requested_entities:
        return []
    domain_member_set = {str(item or "").strip().upper() for item in domain_members}
    requested: List[SemanticConceptCandidate] = []
    for entity in requested_entities:
        matches = [
            row
            for row in all_dimension_candidates
            if row.concept_key in domain_member_set
            and candidate_matches_entity(row=row, entity=entity)
        ]
        if not matches:
            continue
        matches = sorted(
            matches,
            key=lambda row: (
                0 if is_name_like(row) else 1,
                0 if not is_id_like(row) else 1,
                -(float(row.score or 0.0)),
            ),
        )
        requested.append(matches[0])
    out = dedupe_concept_candidates(requested)
    return sort_candidates(out)[: max(2, int(max_dimension_candidates or 8))]


def build_lexical_hints(
    *,
    prompt: str,
    domain_key: str,
    metric_candidates: Sequence[SemanticConceptCandidate],
    dimension_candidates: Sequence[SemanticConceptCandidate],
    filter_candidates: Sequence[SemanticConceptCandidate],
    time_candidates: Sequence[SemanticConceptCandidate],
    alias_rules_by_key: Mapping[str, Sequence[AliasRule]],
) -> Dict[str, List[str]]:
    prompt_text = norm_text(prompt)
    prompt_ngrams = set(build_ngrams(prompt))
    hints: Dict[str, List[str]] = {}
    term_map = {
        "sales": {"sales", "revenue", "net", "gross", "amount"},
        "revenue": {"revenue", "net", "gross", "quota"},
        "account": {"account"},
        "territory": {"territory", "region"},
    }
    for term, signals in term_map.items():
        if term not in prompt_text:
            continue
        scoped_bucket = scoped_bucket_for_term(
            prompt_text=prompt_text,
            term=term,
            metric_candidates=metric_candidates,
            dimension_candidates=dimension_candidates,
            filter_candidates=filter_candidates,
            time_candidates=time_candidates,
        )
        alias_override = resolve_lexical_alias_override(
            term=term,
            prompt=prompt,
            prompt_norm=prompt_text,
            prompt_ngrams=prompt_ngrams,
            bucket=scoped_bucket,
            alias_rules_by_key=alias_rules_by_key,
        )
        if alias_override:
            hints[term] = alias_override[:4]
            continue
        matches: List[str] = []
        for row in scoped_bucket:
            key = str(row.concept_key or "").strip().upper()
            if key == "":
                continue
            label = norm_text(row.label)
            concept_token = norm_text(row.concept_key)
            aliases = " ".join(norm_text(alias) for alias in list(row.aliases or []))
            haystack = " ".join([label, concept_token, aliases]).strip()
            if haystack == "":
                continue
            if any(sig in haystack for sig in signals):
                if key not in matches:
                    matches.append(key)
        if matches:
            hints[term] = matches[:4]
    if domain_key:
        hints.setdefault("domain", [str(domain_key or "").strip().upper()])
    return hints


def scoped_bucket_for_term(
    *,
    prompt_text: str,
    term: str,
    metric_candidates: Sequence[SemanticConceptCandidate],
    dimension_candidates: Sequence[SemanticConceptCandidate],
    filter_candidates: Sequence[SemanticConceptCandidate],
    time_candidates: Sequence[SemanticConceptCandidate],
) -> List[SemanticConceptCandidate]:
    if is_group_by_term_requested(prompt_text=prompt_text, term=term):
        return list(dimension_candidates)
    if term in {"sales", "revenue"}:
        return list(metric_candidates)
    return (
        list(metric_candidates)
        + list(dimension_candidates)
        + list(filter_candidates)
        + list(time_candidates)
    )


def is_group_by_term_requested(*, prompt_text: str, term: str) -> bool:
    token = norm_text(term).strip()
    if token == "":
        return False
    text = f" {str(prompt_text or '').strip().lower()} "
    return f" by {token} " in text


def resolve_lexical_alias_override(
    *,
    term: str,
    prompt: str,
    prompt_norm: str,
    prompt_ngrams: Sequence[str],
    bucket: Sequence[SemanticConceptCandidate],
    alias_rules_by_key: Mapping[str, Sequence[AliasRule]],
) -> List[str]:
    term_token = norm_token(term)
    if term_token == "":
        return []

    hit_rows: List[Tuple[int, float, float, str]] = []
    for row in bucket:
        concept_key = str(row.concept_key or "").strip().upper()
        if concept_key == "":
            continue
        for alias_rule in alias_rules_by_key.get(concept_key, []):
            if not alias_targets_term(alias_rule=alias_rule, term_token=term_token):
                continue
            match_rank = alias_match_rank(
                alias_rule=alias_rule,
                prompt=prompt,
                prompt_norm=prompt_norm,
                prompt_ngrams=prompt_ngrams,
            )
            if match_rank <= 0:
                continue
            hit_rows.append(
                (
                    match_rank,
                    float(alias_rule.weight or 1.0),
                    float(row.score or 0.0),
                    concept_key,
                )
            )

    if not hit_rows:
        return []

    hit_rows.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    best_rank = hit_rows[0][0]
    ranked = [item for item in hit_rows if item[0] == best_rank]
    ranked.sort(key=lambda item: (item[1], item[2]), reverse=True)

    if len(ranked) == 1:
        return [ranked[0][3]]
    if best_rank >= 3:
        top_weight = ranked[0][1]
        second_weight = ranked[1][1] if len(ranked) > 1 else -1.0
        if top_weight >= second_weight + 0.05:
            return [ranked[0][3]]

    out: List[str] = []
    for _rank, _weight, _score, key in ranked:
        if key not in out:
            out.append(key)
    return out


def alias_targets_term(*, alias_rule: AliasRule, term_token: str) -> bool:
    if term_token == "":
        return False
    alias_token = alias_rule.alias_token
    if alias_token == "":
        return False
    if alias_rule.match_kind == "regex":
        regex_token = norm_token(alias_rule.alias)
        return term_token in regex_token or regex_token in term_token
    return term_token in alias_token or alias_token in term_token


def alias_match_rank(
    *,
    alias_rule: AliasRule,
    prompt: str,
    prompt_norm: str,
    prompt_ngrams: Sequence[str],
) -> int:
    alias_token = alias_rule.alias_token
    if alias_token == "":
        return 0
    ngrams = set(prompt_ngrams)
    if alias_rule.match_kind == "exact":
        return 4 if alias_token in ngrams else 0
    if alias_rule.match_kind == "normalized":
        return 4 if alias_token in ngrams else 0
    if alias_rule.match_kind == "prefix":
        return 3 if any(token.startswith(alias_token) for token in ngrams) else 0
    if alias_rule.match_kind == "suffix":
        return 2 if any(token.endswith(alias_token) for token in ngrams) else 0
    if alias_rule.match_kind == "regex":
        return 1 if regex_matches(alias_rule.alias, prompt) else 0
    return 2 if alias_token in prompt_norm else 0


def normalize_match_kind(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"exact", "normalized", "contains", "prefix", "suffix", "regex"}:
        return token
    return "contains"


def regex_matches(pattern: str, text: str) -> bool:
    raw = str(pattern or "").strip()
    if raw == "":
        return False
    try:
        return bool(re.search(raw, str(text or ""), re.IGNORECASE))
    except re.error:
        return False


def extract_group_by_entities(prompt_text: str) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    text = str(prompt_text or "").lower()
    if " by " in f" {text} ":
        segment = text.split(" by ", 1)[1]
        segment = re.split(
            r"\b(where|for|with|during|in|on|from)\b",
            segment,
            maxsplit=1,
        )[0]
        parts = [
            part.strip()
            for part in re.split(r"\band\b|,", segment)
            if part.strip()
        ]
        for part in parts:
            token = re.sub(r"\s+", " ", part).strip().lower()
            if token == "" or token in seen:
                continue
            seen.add(token)
            out.append(token)
    for match in _GROUP_BY_ENTITY_RE.finditer(text):
        raw = str(match.group("entity") or "").strip().lower()
        token = re.sub(r"\s+", " ", raw).strip()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    for alias in ("account", "territory", "region", "sales rep", "representative"):
        if f"by {alias}" in prompt_text and alias not in seen:
            out.append(alias)
            seen.add(alias)
    return out


def candidate_matches_entity(*, row: SemanticConceptCandidate, entity: str) -> bool:
    entity_token = norm_text(entity)
    if entity_token == "":
        return False
    text = " ".join(
        [
            norm_text(row.concept_key),
            norm_text(row.label),
            " ".join(norm_text(alias) for alias in list(row.aliases or [])),
        ]
    ).strip()
    if text == "":
        return False
    return entity_token in text


def dedupe_concept_candidates(
    rows: Sequence[SemanticConceptCandidate],
) -> List[SemanticConceptCandidate]:
    by_key: Dict[str, SemanticConceptCandidate] = {}
    for row in rows:
        key = str(row.concept_key or "").strip().upper()
        if key == "":
            continue
        existing = by_key.get(key)
        if existing is None or float(row.score or 0.0) > float(existing.score or 0.0):
            by_key[key] = row
    return list(by_key.values())


def prefer_dimension_over_filter(
    *,
    prompt_norm: str,
    dimension: SemanticConceptCandidate,
    filter_candidate: SemanticConceptCandidate,
) -> bool:
    dim_name = norm_text(dimension.label or dimension.concept_key)
    if dim_name and f"by {dim_name}" in prompt_norm:
        return True
    if is_name_like(dimension) and not looks_filter_like(filter_candidate):
        return True
    if looks_filter_like(filter_candidate):
        return False
    return float(dimension.score or 0.0) >= float(filter_candidate.score or 0.0)


def is_metric_semantic_type(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in _METRIC_TYPES


def is_dimension_semantic_type(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in _DIMENSION_TYPES


def is_filter_semantic_type(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in _FILTER_TYPES


def is_time_semantic_type(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in _TIME_TYPES


def looks_metric_like(row: SemanticConceptCandidate) -> bool:
    token = norm_text(f"{row.concept_key} {row.label} {' '.join(row.aliases)}")
    return any(
        item in token
        for item in (
            "amount",
            "revenue",
            "sales",
            "count",
            "rate",
            "pct",
            "percent",
            "quota",
        )
    )


def looks_dimension_like(row: SemanticConceptCandidate) -> bool:
    token = norm_text(f"{row.concept_key} {row.label} {' '.join(row.aliases)}")
    if looks_filter_like(row):
        return False
    return not token.endswith(" flag") and not token.endswith(" status")


def looks_filter_like(row: SemanticConceptCandidate) -> bool:
    token = norm_text(f"{row.concept_key} {row.label} {' '.join(row.aliases)}")
    return any(
        item in token
        for item in ("status", "flag", "active", "inactive", "type", "category")
    )


def is_name_like(row: SemanticConceptCandidate) -> bool:
    token = norm_text(f"{row.concept_key} {row.label}")
    return bool(_NAME_HINT_RE.search(token)) or token.endswith(" name")


def is_id_like(row: SemanticConceptCandidate) -> bool:
    token = norm_text(f"{row.concept_key} {row.label}")
    return (
        token.endswith(" id")
        or token.endswith("_id")
        or " identifier" in token
        or " key" in token
    )


def sort_candidates(
    rows: Sequence[SemanticConceptCandidate],
) -> List[SemanticConceptCandidate]:
    return sorted(rows, key=lambda row: row.score, reverse=True)


def concept_key(value: Any) -> str:
    token = str(value or "").strip()
    if token == "":
        return ""
    token = _NON_WORD_RE.sub("_", token).strip("_")
    return token.upper()


def concept_key_from_metric_ref(metric_ref: str) -> str:
    tail = str(metric_ref or "").split(":", 1)[-1]
    return concept_key(tail)


def domain_key_from_name(base_domain_name: Optional[str], base_domain_id: int) -> str:
    text = str(base_domain_name or "").strip()
    if text == "":
        return f"DOMAIN_{int(base_domain_id)}"
    return concept_key(text)


def column_key(row: Mapping[str, Any]) -> str:
    return str(row.get("column_key") or "").strip().lower()


def norm_text(value: Any) -> str:
    return norm_token(value).replace("_", " ")


def norm_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text == "":
        return ""
    text = _NON_WORD_RE.sub("_", text).strip("_")
    return text


def build_ngrams(prompt: str) -> List[str]:
    words = [item for item in _WORD_RE.findall(str(prompt or "").lower()) if item]
    out: List[str] = []
    for n in (4, 3, 2, 1):
        for idx in range(0, max(0, len(words) - n + 1)):
            out.append("_".join(words[idx : idx + n]))
    return list(dict.fromkeys(out))


def build_in_clause(prefix: str, values: Iterable[int]) -> Tuple[str, Dict[str, Any]]:
    params: Dict[str, Any] = {}
    placeholders: List[str] = []
    for idx, value in enumerate(values):
        key = f"{prefix}{idx}"
        params[key] = int(value)
        placeholders.append(f":{key}")
    return (", ".join(placeholders) if placeholders else "NULL"), params


def to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None
