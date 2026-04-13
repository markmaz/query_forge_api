from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Mapping, Optional, Tuple

from sqlalchemy.exc import SQLAlchemyError

from app.config import (
    QF_PLAN_DOMAIN_COMPACT_MAX_DIMENSION_CANDIDATES,
    QF_PLAN_DOMAIN_COMPACT_MAX_FILTER_CANDIDATES,
    QF_PLAN_DOMAIN_COMPACT_MAX_METRIC_CANDIDATES,
    QF_PLAN_DOMAIN_COMPACT_MAX_TIME_CANDIDATES,
    QF_PLAN_DOMAIN_COMPACT_MIN_CANDIDATE_SCORE,
)
from app.services.planner.semantic_candidate_models import (
    SemanticCandidatePayload,
    SemanticConceptCandidate,
)
from app.services.planner.semantic_catalog_lookup_repository import (
    SemanticCatalogLookupRepository,
)
from app.services.semantic.vertical_norm import normalize_semantic_vertical
from app.services.planner.semantic_retrieval_helpers import (
    AliasRule,
    ConceptRow,
    backfill_domain_essential_dimensions,
    build_capability_index,
    build_domain_candidates,
    build_ngrams,
    build_lexical_hints,
    concept_key as normalize_concept_key,
    concept_match_score,
    domain_key_from_name,
    fallback_candidates_from_capabilities,
    is_dimension_semantic_type,
    is_filter_semantic_type,
    is_metric_semantic_type,
    is_time_semantic_type,
    norm_token,
    normalize_match_kind,
    normalize_value_candidates,
    prune_role_clean_candidates,
    resolve_metric_ref,
    resolve_source_column_key,
    sort_candidates,
    to_float,
    to_int,
)

logger = logging.getLogger(__name__)


class SemanticRetrievalService:
    def __init__(
        self,
        *,
        repository: Optional[SemanticCatalogLookupRepository] = None,
    ) -> None:
        self._repo = repository or SemanticCatalogLookupRepository()

    def retrieve(
        self,
        *,
        prompt: str,
        workspace_id: str,
        base_domain_id: int,
        base_domain_name: Optional[str],
        vertical_norm: str,
        capabilities_compact: Mapping[str, Any],
        max_per_type: int = 20,
    ) -> SemanticCandidatePayload:
        normalized_prompt = str(prompt or "").strip()
        vertical = normalize_semantic_vertical(vertical_norm)
        max_items = max(3, min(40, int(max_per_type or 20)))

        capability_index = build_capability_index(capabilities_compact=capabilities_compact)
        fallback_payload = fallback_candidates_from_capabilities(
            prompt=normalized_prompt,
            workspace_id=workspace_id,
            base_domain_id=base_domain_id,
            base_domain_name=base_domain_name,
            vertical_norm=vertical,
            capability_index=capability_index,
        )
        try:
            concept_rows_raw = self._repo.load_concepts(vertical_norm=vertical)
            alias_rows = self._repo.load_aliases(vertical_norm=vertical)
            relationship_rows = self._repo.load_relationships(vertical_norm=vertical)
            column_map_rows = self._repo.load_concept_column_maps(vertical_norm=vertical)
            suggestion_scores = self._repo.load_suggestion_scores()
        except (OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError) as exc:
            logger.warning("semantic_retrieval fallback workspace_id=%s reason=%s", workspace_id, exc)
            return fallback_payload

        concept_rows: Dict[str, ConceptRow] = {}
        concept_id_to_key: Dict[int, str] = {}
        for row in concept_rows_raw:
            concept_id = to_int(row.get("id"))
            concept_key = normalize_concept_key(row.get("concept_key"))
            if concept_id is None or concept_key == "":
                continue
            status = str(row.get("status") or "").strip().lower()
            if status in {"inactive", "disabled", "deleted"}:
                continue
            concept = ConceptRow(
                concept_id=concept_id,
                concept_key=concept_key,
                name=str(row.get("name") or concept_key).strip() or concept_key,
                description=str(row.get("description") or "").strip(),
                semantic_type=str(row.get("semantic_type") or "other").strip().lower() or "other",
            )
            concept_rows[concept_key] = concept
            concept_id_to_key[concept_id] = concept_key

        if not concept_rows:
            return fallback_payload

        alias_rules_by_key: Dict[str, List[AliasRule]] = defaultdict(list)
        for row in alias_rows:
            key = normalize_concept_key(row.get("concept_key"))
            alias = str(row.get("alias_key") or "").strip()
            if key == "" or alias == "":
                continue
            weight = to_float(row.get("weight")) or 1.0
            match_kind = normalize_match_kind(row.get("match_kind"))
            alias_token = norm_token(alias)
            if alias_token == "":
                continue
            alias_rules_by_key[key].append(
                AliasRule(
                    alias=alias,
                    alias_token=alias_token,
                    weight=max(0.0, min(weight, 100.0)),
                    match_kind=match_kind,
                )
            )

        relationships = [
            {
                "parent_key": normalize_concept_key(row.get("parent_key")),
                "child_key": normalize_concept_key(row.get("child_key")),
                "relationship_type": str(row.get("relationship_type") or "").strip().lower(),
            }
            for row in relationship_rows
        ]
        relationships = [
            row
            for row in relationships
            if row["parent_key"] and row["child_key"] and row["relationship_type"]
        ]

        mappings_by_concept: Dict[str, List[Tuple[Optional[int], Optional[int], float, str]]] = defaultdict(list)
        for row in column_map_rows:
            key = normalize_concept_key(row.get("concept_key"))
            workspace_column_id = to_int(row.get("workspace_column_id"))
            model_column_id = to_int(row.get("model_column_id"))
            if key == "" or (workspace_column_id is None and model_column_id is None):
                continue
            weight = to_float(row.get("weight")) or 1.0
            rel_kind = str(row.get("relationship_kind") or "primary").strip().lower() or "primary"
            mappings_by_concept[key].append((workspace_column_id, model_column_id, weight, rel_kind))

        domain_candidates = build_domain_candidates(
            concept_rows=concept_rows,
            alias_rules_by_key=alias_rules_by_key,
            prompt=normalized_prompt,
            base_domain_name=base_domain_name,
            max_items=max_items,
        )
        selected_domain_key = (
            domain_candidates[0].concept_key
            if domain_candidates
            else domain_key_from_name(base_domain_name, base_domain_id)
        )

        domain_members = {
            row["child_key"]
            for row in relationships
            if row["relationship_type"] == "belongs_to_domain" and row["parent_key"] == selected_domain_key
        }
        restrict_to_domain = bool(domain_members)
        if selected_domain_key:
            domain_members.add(selected_domain_key)
        default_time_by_metric = {
            row["parent_key"]: row["child_key"]
            for row in relationships
            if row["relationship_type"] == "default_time_field_for"
        }

        metric_candidates: List[SemanticConceptCandidate] = []
        dimension_candidates: List[SemanticConceptCandidate] = []
        filter_candidates: List[SemanticConceptCandidate] = []
        time_candidates: List[SemanticConceptCandidate] = []
        all_dimension_candidates: List[SemanticConceptCandidate] = []

        for concept_key, concept in concept_rows.items():
            if restrict_to_domain and concept_key not in domain_members:
                continue
            lexical = concept_match_score(
                prompt=normalized_prompt,
                concept_key=concept_key,
                concept_name=concept.name,
                aliases=alias_rules_by_key.get(concept_key, []),
            )
            suggestion_boost = min(0.2, (float(suggestion_scores.get(concept_key, 0)) / 250.0))
            score = max(0.0, min(1.0, lexical + suggestion_boost))
            aliases = [item.alias for item in alias_rules_by_key.get(concept_key, [])]
            candidate_kwargs = {
                "concept_key": concept_key,
                "label": concept.name,
                "score": score,
                "description": concept.description or None,
                "semantic_type": concept.semantic_type,
                "aliases": aliases,
                "domain_key": selected_domain_key or None,
            }
            if is_metric_semantic_type(concept.semantic_type):
                metric_ref = resolve_metric_ref(
                    concept_key=concept_key,
                    concept_name=concept.name,
                    aliases=aliases,
                    capability_index=capability_index,
                )
                if metric_ref:
                    metric_candidates.append(SemanticConceptCandidate(metric_ref=metric_ref, **candidate_kwargs))
                continue
            if is_time_semantic_type(concept.semantic_type):
                column_key = resolve_source_column_key(
                    concept_key=concept_key,
                    concept_name=concept.name,
                    aliases=aliases,
                    mappings=mappings_by_concept.get(concept_key, []),
                    capability_rows=capability_index.time_rows,
                    capability_index=capability_index,
                )
                if column_key:
                    time_candidates.append(SemanticConceptCandidate(source_column_key=column_key, **candidate_kwargs))
                continue
            if is_dimension_semantic_type(concept.semantic_type):
                column_key = resolve_source_column_key(
                    concept_key=concept_key,
                    concept_name=concept.name,
                    aliases=aliases,
                    mappings=mappings_by_concept.get(concept_key, []),
                    capability_rows=capability_index.dimension_rows,
                    capability_index=capability_index,
                )
                if column_key:
                    candidate = SemanticConceptCandidate(source_column_key=column_key, **candidate_kwargs)
                    dimension_candidates.append(candidate)
                    all_dimension_candidates.append(candidate)
            if is_filter_semantic_type(concept.semantic_type):
                column_key = resolve_source_column_key(
                    concept_key=concept_key,
                    concept_name=concept.name,
                    aliases=aliases,
                    mappings=mappings_by_concept.get(concept_key, []),
                    capability_rows=capability_index.filter_rows,
                    capability_index=capability_index,
                )
                if column_key:
                    filter_candidates.append(SemanticConceptCandidate(source_column_key=column_key, **candidate_kwargs))

        metric_candidates = sort_candidates(metric_candidates)
        dimension_candidates = sort_candidates(dimension_candidates)
        filter_candidates = sort_candidates(filter_candidates)
        time_candidates = sort_candidates(time_candidates)

        semantic_source = "semantic_catalog"
        if not metric_candidates and fallback_payload.metric_candidates:
            metric_candidates = list(fallback_payload.metric_candidates)[: max(3, min(12, max_items))]
            semantic_source = "semantic_catalog+metric_capability_fallback"
        if not dimension_candidates and fallback_payload.dimension_candidates:
            dimension_candidates = list(fallback_payload.dimension_candidates)[: max(6, min(20, max_items))]
            semantic_source = "semantic_catalog+dimension_capability_fallback"
        if not filter_candidates and fallback_payload.filter_candidates:
            filter_candidates = list(fallback_payload.filter_candidates)[: max(6, min(20, max_items))]
            semantic_source = "semantic_catalog+filter_capability_fallback"
        if not time_candidates and fallback_payload.time_candidates:
            time_candidates = list(fallback_payload.time_candidates)[: max(2, min(8, max_items))]
            semantic_source = "semantic_catalog+time_capability_fallback"

        if not metric_candidates and not dimension_candidates and not filter_candidates and not time_candidates:
            return fallback_payload

        metric_candidates, dimension_candidates, filter_candidates, time_candidates = prune_role_clean_candidates(
            prompt=normalized_prompt,
            metric_candidates=metric_candidates,
            dimension_candidates=dimension_candidates,
            filter_candidates=filter_candidates,
            time_candidates=time_candidates,
            essential_dimension_candidates=backfill_domain_essential_dimensions(
                prompt=normalized_prompt,
                domain_members=domain_members,
                all_dimension_candidates=all_dimension_candidates,
                max_dimension_candidates=max(
                    1,
                    int(QF_PLAN_DOMAIN_COMPACT_MAX_DIMENSION_CANDIDATES or 8),
                ),
            ),
            min_score=max(
                0.0,
                float(QF_PLAN_DOMAIN_COMPACT_MIN_CANDIDATE_SCORE or 0.0),
            ),
            max_metrics=max(
                1,
                int(QF_PLAN_DOMAIN_COMPACT_MAX_METRIC_CANDIDATES or 5),
            ),
            max_dims=max(
                1,
                int(QF_PLAN_DOMAIN_COMPACT_MAX_DIMENSION_CANDIDATES or 8),
            ),
            max_filters=max(
                1,
                int(QF_PLAN_DOMAIN_COMPACT_MAX_FILTER_CANDIDATES or 8),
            ),
            max_times=max(
                1,
                int(QF_PLAN_DOMAIN_COMPACT_MAX_TIME_CANDIDATES or 3),
            ),
        )

        concept_id_allowlist = [
            concept_rows[key].concept_id
            for key in {
                *[row.concept_key for row in filter_candidates],
                *[row.concept_key for row in time_candidates],
            }
            if key in concept_rows
        ]
        ngrams = build_ngrams(normalized_prompt)
        value_rows = self._repo.search_value_aliases(
            vertical_norm=vertical,
            ngrams=ngrams,
            semantic_concept_ids=concept_id_allowlist,
        )
        value_candidates = normalize_value_candidates(
            rows=value_rows,
            concept_id_to_key=concept_id_to_key,
            max_items=max_items,
        )
        lexical_hints = build_lexical_hints(
            prompt=normalized_prompt,
            domain_key=selected_domain_key,
            metric_candidates=metric_candidates,
            dimension_candidates=dimension_candidates,
            filter_candidates=filter_candidates,
            time_candidates=time_candidates,
            alias_rules_by_key=alias_rules_by_key,
        )

        domain_candidates = domain_candidates[:5] or fallback_payload.domain_candidates
        domain_obj = domain_candidates[0] if domain_candidates else None
        return SemanticCandidatePayload(
            prompt=normalized_prompt,
            normalized_prompt=normalized_prompt,
            workspace_id=workspace_id,
            vertical_norm=vertical,
            base_domain_id=int(base_domain_id),
            base_domain_key=selected_domain_key,
            domain=domain_obj,
            domain_candidates=domain_candidates,
            metric_candidates=metric_candidates,
            dimension_candidates=dimension_candidates,
            filter_candidates=filter_candidates,
            time_candidates=time_candidates,
            value_candidates=value_candidates,
            lexical_hints=lexical_hints,
            planning_rules=[
                "Use only candidate semantic concept keys.",
                "Do not invent domains, metrics, dimensions, filters, or values.",
                "Ask for clarification when business terms map to multiple metrics.",
                "Prefer NAME concepts for grouping fields.",
            ],
            metadata={
                "semantic_source": semantic_source,
                "restrict_to_domain": restrict_to_domain,
                "concept_count": len(concept_rows),
                "domain_members": sorted(domain_members)[:400],
                "default_time_by_metric": {
                    str(k or "").strip().upper(): str(v or "").strip().upper()
                    for k, v in default_time_by_metric.items()
                    if str(k or "").strip() and str(v or "").strip()
                },
            },
        )
