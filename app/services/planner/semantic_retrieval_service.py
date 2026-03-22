from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.config import (
    QF_PLAN_DOMAIN_COMPACT_MAX_DIMENSION_CANDIDATES,
    QF_PLAN_DOMAIN_COMPACT_MAX_FILTER_CANDIDATES,
    QF_PLAN_DOMAIN_COMPACT_MAX_METRIC_CANDIDATES,
    QF_PLAN_DOMAIN_COMPACT_MAX_TIME_CANDIDATES,
    QF_PLAN_DOMAIN_COMPACT_MIN_CANDIDATE_SCORE,
)
from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.planner.semantic_candidate_models import (
    SemanticCandidatePayload,
    SemanticConceptCandidate,
    SemanticValueCandidate,
)

logger = logging.getLogger(__name__)

_NON_WORD_RE = re.compile(r"[^a-zA-Z0-9]+")
_WORD_RE = re.compile(r"[a-z0-9]+")

_METRIC_TYPES = {"metric", "measure"}
_DIMENSION_TYPES = {"dimension", "identifier", "attribute"}
_FILTER_TYPES = {"filter", "dimension", "attribute"}
_TIME_TYPES = {"time_field"}
_NAME_HINT_RE = re.compile(r"\b(name|label|title)\b", re.IGNORECASE)
_GROUP_BY_ENTITY_RE = re.compile(r"\bby\s+(?P<entity>[a-z][a-z0-9_\s]{1,40})\b", re.IGNORECASE)


@dataclass(frozen=True)
class _ConceptRow:
    concept_id: int
    concept_key: str
    name: str
    description: str
    semantic_type: str


@dataclass(frozen=True)
class _AliasRule:
    alias: str
    alias_token: str
    weight: float
    match_kind: str


class SemanticCatalogLookupRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._relationship_fk_target_cache: Optional[str] = None

    def load_concepts(self, *, vertical_norm: str) -> List[Dict[str, Any]]:
        return self._sql.execute_query_mappings(
            """
            SELECT
              id,
              concept_key,
              name,
              COALESCE(description, '') AS description,
              LOWER(COALESCE(semantic_type, 'other')) AS semantic_type,
              LOWER(COALESCE(vertical_norm, 'generic')) AS vertical_norm,
              LOWER(COALESCE(`status`, 'active')) AS `status`
            FROM semantic_concept
            WHERE LOWER(COALESCE(vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
            ORDER BY
              CASE WHEN LOWER(COALESCE(vertical_norm, 'generic')) = :vertical_norm THEN 0 ELSE 1 END,
              id ASC
            """,
            {"vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic"},
        )

    def load_aliases(self, *, vertical_norm: str) -> List[Dict[str, Any]]:
        params = {"vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic"}
        try:
            return self._sql.execute_query_mappings(
                """
                SELECT
                  UPPER(TRIM(concept_key)) AS concept_key,
                  alias_key,
                  COALESCE(weight, 1.0) AS weight,
                  LOWER(COALESCE(match_kind, 'contains')) AS match_kind
                FROM semantic_concept_alias
                WHERE LOWER(COALESCE(vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
                ORDER BY id ASC
                """,
                params,
            )
        except Exception:
            # Backward compatible fallback for environments that do not yet have match_kind.
            return self._sql.execute_query_mappings(
                """
                SELECT
                  UPPER(TRIM(concept_key)) AS concept_key,
                  alias_key,
                  COALESCE(weight, 1.0) AS weight,
                  'contains' AS match_kind
                FROM semantic_concept_alias
                WHERE LOWER(COALESCE(vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
                ORDER BY id ASC
                """,
                params,
            )

    def load_relationships(self, *, vertical_norm: str) -> List[Dict[str, Any]]:
        params = {"vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic"}
        fk_target = self._get_relationship_fk_target()
        if fk_target == "semantic_registry":
            return self._sql.execute_query_mappings(
                """
                SELECT
                  UPPER(TRIM(parent.concept_key)) AS parent_key,
                  UPPER(TRIM(child.concept_key)) AS child_key,
                  LOWER(TRIM(sr.relationship_type)) AS relationship_type
                FROM semantic_relationship sr
                JOIN semantic_registry parent ON parent.id = sr.parent_concept_id
                JOIN semantic_registry child ON child.id = sr.child_concept_id
                WHERE LOWER(COALESCE(parent.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
                  AND LOWER(COALESCE(child.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
                ORDER BY sr.id ASC
                """,
                params,
            )
        return self._sql.execute_query_mappings(
            """
            SELECT
              UPPER(TRIM(parent.concept_key)) AS parent_key,
              UPPER(TRIM(child.concept_key)) AS child_key,
              LOWER(TRIM(sr.relationship_type)) AS relationship_type
            FROM semantic_relationship sr
            JOIN semantic_concept parent ON parent.id = sr.parent_concept_id
            JOIN semantic_concept child ON child.id = sr.child_concept_id
            WHERE LOWER(COALESCE(parent.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
              AND LOWER(COALESCE(child.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
            ORDER BY sr.id ASC
            """,
            params,
        )

    def load_concept_column_maps(self, *, vertical_norm: str) -> List[Dict[str, Any]]:
        return self._sql.execute_query_mappings(
            """
            SELECT
              m.semantic_concept_id,
              UPPER(TRIM(sc.concept_key)) AS concept_key,
              m.workspace_column_id,
              LOWER(COALESCE(m.relationship_kind, 'primary')) AS relationship_kind,
              COALESCE(m.weight, 1.0) AS weight
            FROM workspace_column_semantic_concept_map m
            JOIN semantic_concept sc ON sc.id = m.semantic_concept_id
            WHERE LOWER(COALESCE(m.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
            ORDER BY
              CASE WHEN LOWER(COALESCE(m.relationship_kind, 'primary')) = 'primary' THEN 0 ELSE 1 END,
              m.weight DESC,
              m.id ASC
            """,
            {"vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic"},
        )

    def search_value_aliases(
        self,
        *,
        vertical_norm: str,
        ngrams: Sequence[str],
        semantic_concept_ids: Sequence[int],
    ) -> List[Dict[str, Any]]:
        if not ngrams or not semantic_concept_ids:
            return []

        rows: List[Dict[str, Any]] = []
        in_sql, in_params = _build_in_clause("cid_", semantic_concept_ids)
        for ngram in ngrams:
            params = {
                "vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic",
                "ngram": str(ngram or "").strip().lower(),
                **in_params,
            }
            if params["ngram"] == "":
                continue
            rows.extend(
                self._sql.execute_query_mappings(
                    f"""
                    SELECT
                      va.semantic_concept_id,
                      LOWER(TRIM(va.alias_value)) AS alias_value,
                      va.canonical_value,
                      LOWER(COALESCE(va.match_kind, 'contains')) AS match_kind,
                      COALESCE(va.weight, 1.0) AS weight
                    FROM semantic_value_alias va
                    WHERE LOWER(COALESCE(va.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
                      AND va.semantic_concept_id IN ({in_sql})
                      AND (
                        (LOWER(COALESCE(va.match_kind, 'contains')) = 'exact' AND LOWER(va.alias_value) = :ngram)
                        OR
                        (LOWER(COALESCE(va.match_kind, 'contains')) = 'contains' AND :ngram LIKE CONCAT('%', LOWER(va.alias_value), '%'))
                        OR
                        (LOWER(COALESCE(va.match_kind, 'contains')) = 'prefix' AND :ngram LIKE CONCAT(LOWER(va.alias_value), '%'))
                      )
                    ORDER BY
                      CASE WHEN LOWER(COALESCE(va.vertical_norm, 'generic')) = :vertical_norm THEN 0 ELSE 1 END,
                      va.weight DESC,
                      va.id ASC
                    """,
                    params,
                )
            )
        return rows

    def load_suggestion_scores(self) -> Dict[str, int]:
        try:
            rows = self._sql.execute_query_mappings(
                """
                SELECT
                  UPPER(TRIM(proposed_concept_key)) AS concept_key,
                  COUNT(*) AS usage_count
                FROM semantic_suggestion_item
                WHERE proposed_concept_key IS NOT NULL
                  AND proposed_concept_key <> ''
                  AND decision_status IN ('auto_approved', 'approved', 'applied')
                GROUP BY UPPER(TRIM(proposed_concept_key))
                """,
                {},
            )
        except Exception:
            return {}
        out: Dict[str, int] = {}
        for row in rows:
            key = str(row.get("concept_key") or "").strip().upper()
            if key == "":
                continue
            out[key] = int(row.get("usage_count") or 0)
        return out

    def _get_relationship_fk_target(self) -> str:
        if self._relationship_fk_target_cache:
            return self._relationship_fk_target_cache
        try:
            rows = self._sql.execute_query_mappings(
                """
                SELECT LOWER(COALESCE(kcu.REFERENCED_TABLE_NAME, '')) AS referenced_table_name
                FROM information_schema.KEY_COLUMN_USAGE kcu
                WHERE kcu.TABLE_SCHEMA = DATABASE()
                  AND kcu.TABLE_NAME = 'semantic_relationship'
                  AND kcu.COLUMN_NAME = 'parent_concept_id'
                  AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
                LIMIT 1
                """,
                {},
            )
            target = str((rows[0].get("referenced_table_name") if rows else "") or "").strip().lower()
            if target in {"semantic_registry", "semantic_concept"}:
                self._relationship_fk_target_cache = target
                return target
        except Exception:
            pass
        self._relationship_fk_target_cache = "semantic_concept"
        return self._relationship_fk_target_cache


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
        vertical = str(vertical_norm or "generic").strip().lower() or "generic"
        max_items = max(3, min(40, int(max_per_type or 20)))

        capability_index = _build_capability_index(capabilities_compact=capabilities_compact)
        fallback_payload = _fallback_candidates_from_capabilities(
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
        except Exception as exc:
            logger.warning("semantic_retrieval fallback workspace_id=%s reason=%s", workspace_id, exc)
            return fallback_payload

        concept_rows: Dict[str, _ConceptRow] = {}
        concept_id_to_key: Dict[int, str] = {}
        for row in concept_rows_raw:
            concept_id = _to_int(row.get("id"))
            concept_key = _concept_key(row.get("concept_key"))
            if concept_id is None or concept_key == "":
                continue
            status = str(row.get("status") or "").strip().lower()
            if status in {"inactive", "disabled", "deleted"}:
                continue
            concept = _ConceptRow(
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

        alias_rules_by_key: Dict[str, List[_AliasRule]] = defaultdict(list)
        for row in alias_rows:
            key = _concept_key(row.get("concept_key"))
            alias = str(row.get("alias_key") or "").strip()
            if key == "" or alias == "":
                continue
            weight = _to_float(row.get("weight")) or 1.0
            match_kind = _normalize_match_kind(row.get("match_kind"))
            alias_token = _norm_token(alias)
            if alias_token == "":
                continue
            alias_rules_by_key[key].append(
                _AliasRule(
                    alias=alias,
                    alias_token=alias_token,
                    weight=max(0.0, min(weight, 100.0)),
                    match_kind=match_kind,
                )
            )

        relationships = [
            {
                "parent_key": _concept_key(row.get("parent_key")),
                "child_key": _concept_key(row.get("child_key")),
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
            key = _concept_key(row.get("concept_key"))
            workspace_column_id = _to_int(row.get("workspace_column_id"))
            model_column_id = _to_int(row.get("model_column_id"))
            if key == "" or (workspace_column_id is None and model_column_id is None):
                continue
            weight = _to_float(row.get("weight")) or 1.0
            rel_kind = str(row.get("relationship_kind") or "primary").strip().lower() or "primary"
            mappings_by_concept[key].append((workspace_column_id, model_column_id, weight, rel_kind))

        domain_candidates = _build_domain_candidates(
            concept_rows=concept_rows,
            alias_rules_by_key=alias_rules_by_key,
            prompt=normalized_prompt,
            base_domain_name=base_domain_name,
            max_items=max_items,
        )
        selected_domain_key = (
            domain_candidates[0].concept_key if domain_candidates else _domain_key_from_name(base_domain_name, base_domain_id)
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
            lexical = _concept_match_score(
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
            if concept.semantic_type in _METRIC_TYPES:
                metric_ref = _resolve_metric_ref(
                    concept_key=concept_key,
                    concept_name=concept.name,
                    aliases=aliases,
                    capability_index=capability_index,
                )
                if metric_ref:
                    metric_candidates.append(SemanticConceptCandidate(metric_ref=metric_ref, **candidate_kwargs))
                continue
            if concept.semantic_type in _TIME_TYPES:
                column_key = _resolve_source_column_key(
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
            if concept.semantic_type in _DIMENSION_TYPES:
                column_key = _resolve_source_column_key(
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
            if concept.semantic_type in _FILTER_TYPES:
                column_key = _resolve_source_column_key(
                    concept_key=concept_key,
                    concept_name=concept.name,
                    aliases=aliases,
                    mappings=mappings_by_concept.get(concept_key, []),
                    capability_rows=capability_index.filter_rows,
                    capability_index=capability_index,
                )
                if column_key:
                    filter_candidates.append(SemanticConceptCandidate(source_column_key=column_key, **candidate_kwargs))

        metric_candidates = _sort_candidates(metric_candidates)
        dimension_candidates = _sort_candidates(dimension_candidates)
        filter_candidates = _sort_candidates(filter_candidates)
        time_candidates = _sort_candidates(time_candidates)

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

        metric_candidates, dimension_candidates, filter_candidates, time_candidates = _prune_role_clean_candidates(
            prompt=normalized_prompt,
            metric_candidates=metric_candidates,
            dimension_candidates=dimension_candidates,
            filter_candidates=filter_candidates,
            time_candidates=time_candidates,
            essential_dimension_candidates=_backfill_domain_essential_dimensions(
                prompt=normalized_prompt,
                selected_domain_key=selected_domain_key,
                domain_members=domain_members,
                all_dimension_candidates=all_dimension_candidates,
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
        ngrams = _build_ngrams(normalized_prompt)
        value_rows = self._repo.search_value_aliases(
            vertical_norm=vertical,
            ngrams=ngrams,
            semantic_concept_ids=concept_id_allowlist,
        )
        value_candidates = _normalize_value_candidates(
            rows=value_rows,
            concept_id_to_key=concept_id_to_key,
            max_items=max_items,
        )
        lexical_hints = _build_lexical_hints(
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


@dataclass(frozen=True)
class _CapabilityIndex:
    metric_rows: List[Dict[str, Any]]
    dimension_rows: List[Dict[str, Any]]
    filter_rows: List[Dict[str, Any]]
    time_rows: List[Dict[str, Any]]
    metric_alias_to_ref: Dict[str, str]
    column_by_workspace_id: Dict[int, str]
    column_by_model_id: Dict[int, str]
    column_alias_to_key: Dict[str, str]


def _build_capability_index(*, capabilities_compact: Mapping[str, Any]) -> _CapabilityIndex:
    metric_rows: List[Dict[str, Any]] = []
    metric_alias_to_ref: Dict[str, str] = {}

    def _register_metric_row(row: Mapping[str, Any], metric_ref: str, default_label: str) -> None:
        metric_rows.append({"metric_ref": metric_ref, "label": default_label, "raw": dict(row)})
        for alias in {
            metric_ref,
            default_label,
            str(row.get("metric_key") or ""),
            str(row.get("label") or ""),
            str(row.get("metric_id") or ""),
            str(row.get("id") or ""),
            metric_ref.split(":", 1)[-1],
        }:
            token = _norm_token(alias)
            if token:
                metric_alias_to_ref[token] = metric_ref

    for row in list(capabilities_compact.get("domain_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        metric_key = _norm_token(row.get("metric_key"))
        if metric_key == "":
            continue
        metric_ref = f"domain_metric:{metric_key}"
        _register_metric_row(row, metric_ref, str(row.get("label") or metric_key))
    for row in list(capabilities_compact.get("user_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        metric_key = _norm_token(row.get("metric_id") or row.get("id"))
        if metric_key == "":
            continue
        metric_ref = f"user_metric:{metric_key}"
        _register_metric_row(row, metric_ref, str(row.get("label") or metric_key))
    for row in list(capabilities_compact.get("overlay_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        metric_key = _norm_token(row.get("overlay_key") or row.get("id"))
        if metric_key == "":
            continue
        metric_ref = f"overlay:{metric_key}"
        _register_metric_row(row, metric_ref, str(row.get("label") or metric_key))

    dimension_rows = [dict(row) for row in list(capabilities_compact.get("dimensions") or []) if isinstance(row, Mapping)]
    filter_rows = [dict(row) for row in list(capabilities_compact.get("filter_columns") or []) if isinstance(row, Mapping)]
    time_rows = [dict(row) for row in list(capabilities_compact.get("time_columns") or []) if isinstance(row, Mapping)]

    column_by_workspace_id: Dict[int, str] = {}
    column_by_model_id: Dict[int, str] = {}
    column_alias_to_key: Dict[str, str] = {}
    for row in dimension_rows + filter_rows + time_rows:
        key = _column_key(row)
        if key == "":
            continue
        workspace_id = _to_int(row.get("workspace_column_id"))
        if workspace_id is not None and workspace_id not in column_by_workspace_id:
            column_by_workspace_id[workspace_id] = key
        model_id = _to_int(row.get("model_column_id"))
        if model_id is not None and model_id not in column_by_model_id:
            column_by_model_id[model_id] = key
        for alias in {
            key,
            str(row.get("column_name") or ""),
            str(row.get("label") or ""),
            key.split(".", 1)[-1],
        }:
            token = _norm_token(alias)
            if token and token not in column_alias_to_key:
                column_alias_to_key[token] = key

    return _CapabilityIndex(
        metric_rows=metric_rows,
        dimension_rows=dimension_rows,
        filter_rows=filter_rows,
        time_rows=time_rows,
        metric_alias_to_ref=metric_alias_to_ref,
        column_by_workspace_id=column_by_workspace_id,
        column_by_model_id=column_by_model_id,
        column_alias_to_key=column_alias_to_key,
    )


def _fallback_candidates_from_capabilities(
    *,
    prompt: str,
    workspace_id: str,
    base_domain_id: int,
    base_domain_name: Optional[str],
    vertical_norm: str,
    capability_index: _CapabilityIndex,
) -> SemanticCandidatePayload:
    domain_key = _domain_key_from_name(base_domain_name, base_domain_id)
    domain_candidate = SemanticConceptCandidate(
        concept_key=domain_key,
        label=str(base_domain_name or f"domain_{base_domain_id}"),
        score=1.0,
        semantic_type="domain",
    )
    metric_candidates = [
        SemanticConceptCandidate(
            concept_key=_concept_key_from_metric_ref(row["metric_ref"]),
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
            concept_key=_concept_key(str(row.get("column_name") or _column_key(row))),
            label=str(row.get("label") or row.get("column_name") or _column_key(row)),
            source_column_key=_column_key(row),
            semantic_type="dimension",
            score=0.65,
            domain_key=domain_key,
        )
        for row in capability_index.dimension_rows[:30]
        if _column_key(row)
    ]
    filter_candidates = [
        SemanticConceptCandidate(
            concept_key=_concept_key(str(row.get("column_name") or _column_key(row))),
            label=str(row.get("label") or row.get("column_name") or _column_key(row)),
            source_column_key=_column_key(row),
            semantic_type="filter",
            score=0.65,
            domain_key=domain_key,
        )
        for row in capability_index.filter_rows[:30]
        if _column_key(row)
    ]
    time_candidates = [
        SemanticConceptCandidate(
            concept_key=_concept_key(str(row.get("column_name") or _column_key(row))),
            label=str(row.get("label") or row.get("column_name") or _column_key(row)),
            source_column_key=_column_key(row),
            semantic_type="time_field",
            score=0.65,
            domain_key=domain_key,
        )
        for row in capability_index.time_rows[:12]
        if _column_key(row)
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
        metadata={"semantic_source": "capabilities_fallback", "domain_members": [domain_key], "default_time_by_metric": {}},
    )


def _build_domain_candidates(
    *,
    concept_rows: Mapping[str, _ConceptRow],
    alias_rules_by_key: Mapping[str, Sequence[_AliasRule]],
    prompt: str,
    base_domain_name: Optional[str],
    max_items: int,
) -> List[SemanticConceptCandidate]:
    rows: List[SemanticConceptCandidate] = []
    domain_hint = _norm_token(base_domain_name)
    for concept in concept_rows.values():
        if concept.semantic_type != "domain":
            continue
        score = _concept_match_score(
            prompt=prompt,
            concept_key=concept.concept_key,
            concept_name=concept.name,
            aliases=alias_rules_by_key.get(concept.concept_key, []),
        )
        if domain_hint and (
            domain_hint in _norm_token(concept.concept_key) or domain_hint in _norm_token(concept.name)
        ):
            score = min(1.0, score + 0.35)
        rows.append(
            SemanticConceptCandidate(
                concept_key=concept.concept_key,
                label=concept.name,
                score=score,
                description=concept.description or None,
                semantic_type="domain",
                aliases=[item.alias for item in alias_rules_by_key.get(concept.concept_key, [])],
            )
        )
    rows = _sort_candidates(rows)[:max(1, min(5, max_items))]
    return rows


def _normalize_value_candidates(
    *,
    rows: Sequence[Mapping[str, Any]],
    concept_id_to_key: Mapping[int, str],
    max_items: int,
) -> List[SemanticValueCandidate]:
    out: List[SemanticValueCandidate] = []
    seen: set[Tuple[str, str]] = set()
    for row in rows:
        concept_id = _to_int(row.get("semantic_concept_id"))
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


def _concept_match_score(
    *,
    prompt: str,
    concept_key: str,
    concept_name: str,
    aliases: Sequence[_AliasRule],
) -> float:
    score = 0.0
    text = _norm_text(prompt)
    ngrams = set(_build_ngrams(prompt))
    concept_token = _norm_token(concept_key.replace("_", " "))
    name_token = _norm_token(concept_name)
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
            if _regex_matches(alias_rule.alias, prompt):
                score += 0.5 * weight_boost
            continue
        # contains fallback/default
        if alias_token in text:
            score += 0.4 * weight_boost
    concept_terms = set(_WORD_RE.findall(concept_token))
    prompt_terms = set(_WORD_RE.findall(text))
    overlap = len(concept_terms.intersection(prompt_terms))
    if overlap > 0:
        score += min(0.3, overlap * 0.08)
    return max(0.0, min(1.0, score))


def _resolve_metric_ref(
    *,
    concept_key: str,
    concept_name: str,
    aliases: Sequence[str],
    capability_index: _CapabilityIndex,
) -> Optional[str]:
    alias_tokens = [concept_key, concept_name, *list(aliases or [])]
    for alias in alias_tokens:
        token = _norm_token(alias)
        if token and token in capability_index.metric_alias_to_ref:
            return capability_index.metric_alias_to_ref[token]
    return None


def _resolve_source_column_key(
    *,
    concept_key: str,
    concept_name: str,
    aliases: Sequence[str],
    mappings: Sequence[Tuple[Optional[int], Optional[int], float, str]],
    capability_rows: Sequence[Mapping[str, Any]],
    capability_index: _CapabilityIndex,
) -> Optional[str]:
    for workspace_column_id, model_column_id, _weight, _rel_kind in mappings:
        if workspace_column_id is not None and workspace_column_id in capability_index.column_by_workspace_id:
            return capability_index.column_by_workspace_id[workspace_column_id]
        if model_column_id in capability_index.column_by_model_id:
            return capability_index.column_by_model_id[model_column_id]

    candidates = [concept_key, concept_name, *list(aliases or [])]
    for item in candidates:
        token = _norm_token(item)
        if token and token in capability_index.column_alias_to_key:
            key = capability_index.column_alias_to_key[token]
            if any(_column_key(row) == key for row in capability_rows):
                return key
    return None


def _prune_role_clean_candidates(
    *,
    prompt: str,
    metric_candidates: Sequence[SemanticConceptCandidate],
    dimension_candidates: Sequence[SemanticConceptCandidate],
    filter_candidates: Sequence[SemanticConceptCandidate],
    time_candidates: Sequence[SemanticConceptCandidate],
    essential_dimension_candidates: Sequence[SemanticConceptCandidate],
) -> Tuple[
    List[SemanticConceptCandidate],
    List[SemanticConceptCandidate],
    List[SemanticConceptCandidate],
    List[SemanticConceptCandidate],
]:
    min_score = max(0.0, float(QF_PLAN_DOMAIN_COMPACT_MIN_CANDIDATE_SCORE or 0.0))
    max_metrics = max(1, int(QF_PLAN_DOMAIN_COMPACT_MAX_METRIC_CANDIDATES or 5))
    max_dims = max(1, int(QF_PLAN_DOMAIN_COMPACT_MAX_DIMENSION_CANDIDATES or 8))
    max_filters = max(1, int(QF_PLAN_DOMAIN_COMPACT_MAX_FILTER_CANDIDATES or 8))
    max_times = max(1, int(QF_PLAN_DOMAIN_COMPACT_MAX_TIME_CANDIDATES or 3))

    essentials = {str(row.concept_key or "").strip().upper() for row in essential_dimension_candidates}
    metrics = _dedupe_concept_candidates(metric_candidates)
    dims = _dedupe_concept_candidates(dimension_candidates)
    filters = _dedupe_concept_candidates(filter_candidates)
    times = _dedupe_concept_candidates(time_candidates)

    metrics = [
        row
        for row in metrics
        if row.metric_ref and (_is_metric_semantic_type(row.semantic_type) or _looks_metric_like(row)) and (row.score > min_score)
    ]
    dims = [
        row
        for row in dims
        if row.source_column_key and (_is_dimension_semantic_type(row.semantic_type) or _looks_dimension_like(row))
        and (row.score > min_score or row.concept_key in essentials)
    ]
    filters = [
        row
        for row in filters
        if row.source_column_key and (_is_filter_semantic_type(row.semantic_type) or _looks_filter_like(row))
        and (row.score > min_score)
    ]
    times = [
        row
        for row in times
        if row.source_column_key and _is_time_semantic_type(row.semantic_type) and (row.score > min_score)
    ]

    metric_keys = {row.concept_key for row in metrics}
    dim_by_key = {row.concept_key: row for row in dims if row.concept_key not in metric_keys}
    filter_by_key = {row.concept_key: row for row in filters if row.concept_key not in metric_keys}
    overlap = set(dim_by_key.keys()).intersection(filter_by_key.keys())
    prompt_norm = _norm_text(prompt)
    for key in overlap:
        dim_row = dim_by_key.get(key)
        filter_row = filter_by_key.get(key)
        if dim_row is None or filter_row is None:
            continue
        keep_dimension = _prefer_dimension_over_filter(
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

    dims = _sort_candidates(list(dim_by_key.values()))[:max_dims]
    filters = _sort_candidates(list(filter_by_key.values()))[:max_filters]
    metrics = _sort_candidates(metrics)[:max_metrics]
    times = _sort_candidates(times)[:max_times]
    return metrics, dims, filters, times


def _backfill_domain_essential_dimensions(
    *,
    prompt: str,
    selected_domain_key: str,
    domain_members: Sequence[str],
    all_dimension_candidates: Sequence[SemanticConceptCandidate],
) -> List[SemanticConceptCandidate]:
    prompt_text = str(prompt or "").strip().lower()
    if " by " not in f" {prompt_text} ":
        return []
    requested_entities = _extract_group_by_entities(prompt_text)
    if not requested_entities:
        return []
    domain_member_set = {str(item or "").strip().upper() for item in domain_members}
    requested: List[SemanticConceptCandidate] = []
    for entity in requested_entities:
        matches = [
            row
            for row in all_dimension_candidates
            if row.concept_key in domain_member_set and _candidate_matches_entity(row=row, entity=entity)
        ]
        if not matches:
            continue
        matches = sorted(
            matches,
            key=lambda row: (
                0 if _is_name_like(row) else 1,
                0 if not _is_id_like(row) else 1,
                -(float(row.score or 0.0)),
            ),
        )
        requested.append(matches[0])
    out = _dedupe_concept_candidates(requested)
    return _sort_candidates(out)[: max(2, int(QF_PLAN_DOMAIN_COMPACT_MAX_DIMENSION_CANDIDATES or 8))]


def _build_lexical_hints(
    *,
    prompt: str,
    domain_key: str,
    metric_candidates: Sequence[SemanticConceptCandidate],
    dimension_candidates: Sequence[SemanticConceptCandidate],
    filter_candidates: Sequence[SemanticConceptCandidate],
    time_candidates: Sequence[SemanticConceptCandidate],
    alias_rules_by_key: Mapping[str, Sequence[_AliasRule]],
) -> Dict[str, List[str]]:
    prompt_text = _norm_text(prompt)
    prompt_ngrams = set(_build_ngrams(prompt))
    hints: Dict[str, List[str]] = {}
    term_map = {
        "sales": {"sales", "revenue", "net", "gross", "amount"},
        "revenue": {"revenue", "net", "gross", "quota"},
        "account": {"account"},
        "territory": {"territory", "region"},
    }
    bucket = list(metric_candidates) + list(dimension_candidates) + list(filter_candidates) + list(time_candidates)
    for term, signals in term_map.items():
        if term not in prompt_text:
            continue
        scoped_bucket = _scoped_bucket_for_term(
            prompt_text=prompt_text,
            term=term,
            metric_candidates=metric_candidates,
            dimension_candidates=dimension_candidates,
            filter_candidates=filter_candidates,
            time_candidates=time_candidates,
        )
        alias_override = _resolve_lexical_alias_override(
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
            label = _norm_text(row.label)
            concept_token = _norm_text(row.concept_key)
            aliases = " ".join(_norm_text(alias) for alias in list(row.aliases or []))
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


def _scoped_bucket_for_term(
    *,
    prompt_text: str,
    term: str,
    metric_candidates: Sequence[SemanticConceptCandidate],
    dimension_candidates: Sequence[SemanticConceptCandidate],
    filter_candidates: Sequence[SemanticConceptCandidate],
    time_candidates: Sequence[SemanticConceptCandidate],
) -> List[SemanticConceptCandidate]:
    if _is_group_by_term_requested(prompt_text=prompt_text, term=term):
        # For explicit group-by intent, do not allow filter-only substitutions like ACCOUNT_TYPE.
        return list(dimension_candidates)
    if term in {"sales", "revenue"}:
        return list(metric_candidates)
    return list(metric_candidates) + list(dimension_candidates) + list(filter_candidates) + list(time_candidates)


def _is_group_by_term_requested(*, prompt_text: str, term: str) -> bool:
    token = _norm_text(term).strip()
    if token == "":
        return False
    text = f" {str(prompt_text or '').strip().lower()} "
    return f" by {token} " in text


def _resolve_lexical_alias_override(
    *,
    term: str,
    prompt: str,
    prompt_norm: str,
    prompt_ngrams: Sequence[str],
    bucket: Sequence[SemanticConceptCandidate],
    alias_rules_by_key: Mapping[str, Sequence[_AliasRule]],
) -> List[str]:
    term_token = _norm_token(term)
    if term_token == "":
        return []

    hit_rows: List[Tuple[int, float, float, str]] = []
    for row in bucket:
        concept_key = str(row.concept_key or "").strip().upper()
        if concept_key == "":
            continue
        for alias_rule in alias_rules_by_key.get(concept_key, []):
            if not _alias_targets_term(alias_rule=alias_rule, term_token=term_token):
                continue
            match_rank = _alias_match_rank(
                alias_rule=alias_rule,
                prompt=prompt,
                prompt_norm=prompt_norm,
                prompt_ngrams=prompt_ngrams,
            )
            if match_rank <= 0:
                continue
            hit_rows.append((match_rank, float(alias_rule.weight or 1.0), float(row.score or 0.0), concept_key))

    if not hit_rows:
        return []

    hit_rows.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    best_rank = hit_rows[0][0]
    ranked = [item for item in hit_rows if item[0] == best_rank]
    ranked.sort(key=lambda item: (item[1], item[2]), reverse=True)

    # Strong deterministic override: exact/prefix with weight tie-break.
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


def _alias_targets_term(*, alias_rule: _AliasRule, term_token: str) -> bool:
    if term_token == "":
        return False
    alias_token = alias_rule.alias_token
    if alias_token == "":
        return False
    if alias_rule.match_kind == "regex":
        # Lightweight check to keep regex aliases term-scoped.
        regex_token = _norm_token(alias_rule.alias)
        return term_token in regex_token or regex_token in term_token
    return term_token in alias_token or alias_token in term_token


def _alias_match_rank(
    *,
    alias_rule: _AliasRule,
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
        return 1 if _regex_matches(alias_rule.alias, prompt) else 0
    # contains/default
    return 2 if alias_token in prompt_norm else 0


def _normalize_match_kind(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"exact", "normalized", "contains", "prefix", "suffix", "regex"}:
        return token
    return "contains"


def _regex_matches(pattern: str, text: str) -> bool:
    raw = str(pattern or "").strip()
    if raw == "":
        return False
    try:
        return bool(re.search(raw, str(text or ""), re.IGNORECASE))
    except re.error:
        return False


def _extract_group_by_entities(prompt_text: str) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    text = str(prompt_text or "").lower()
    if " by " in f" {text} ":
        segment = text.split(" by ", 1)[1]
        segment = re.split(r"\b(where|for|with|during|in|on|from)\b", segment, maxsplit=1)[0]
        parts = [part.strip() for part in re.split(r"\band\b|,", segment) if part.strip()]
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


def _candidate_matches_entity(*, row: SemanticConceptCandidate, entity: str) -> bool:
    entity_token = _norm_text(entity)
    if entity_token == "":
        return False
    text = " ".join(
        [
            _norm_text(row.concept_key),
            _norm_text(row.label),
            " ".join(_norm_text(alias) for alias in list(row.aliases or [])),
        ]
    ).strip()
    if text == "":
        return False
    return entity_token in text


def _dedupe_concept_candidates(rows: Sequence[SemanticConceptCandidate]) -> List[SemanticConceptCandidate]:
    by_key: Dict[str, SemanticConceptCandidate] = {}
    for row in rows:
        key = str(row.concept_key or "").strip().upper()
        if key == "":
            continue
        existing = by_key.get(key)
        if existing is None or float(row.score or 0.0) > float(existing.score or 0.0):
            by_key[key] = row
    return list(by_key.values())


def _prefer_dimension_over_filter(
    *,
    prompt_norm: str,
    dimension: SemanticConceptCandidate,
    filter_candidate: SemanticConceptCandidate,
) -> bool:
    dim_name = _norm_text(dimension.label or dimension.concept_key)
    filter_name = _norm_text(filter_candidate.label or filter_candidate.concept_key)
    if dim_name and f"by {dim_name}" in prompt_norm:
        return True
    if _is_name_like(dimension) and not _looks_filter_like(filter_candidate):
        return True
    if _looks_filter_like(filter_candidate):
        return False
    return float(dimension.score or 0.0) >= float(filter_candidate.score or 0.0)


def _is_metric_semantic_type(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in _METRIC_TYPES


def _is_dimension_semantic_type(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in _DIMENSION_TYPES


def _is_filter_semantic_type(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in _FILTER_TYPES


def _is_time_semantic_type(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in _TIME_TYPES


def _looks_metric_like(row: SemanticConceptCandidate) -> bool:
    token = _norm_text(f"{row.concept_key} {row.label} {' '.join(row.aliases)}")
    return any(item in token for item in ("amount", "revenue", "sales", "count", "rate", "pct", "percent", "quota"))


def _looks_dimension_like(row: SemanticConceptCandidate) -> bool:
    token = _norm_text(f"{row.concept_key} {row.label} {' '.join(row.aliases)}")
    if _looks_filter_like(row):
        return False
    return not token.endswith(" flag") and not token.endswith(" status")


def _looks_filter_like(row: SemanticConceptCandidate) -> bool:
    token = _norm_text(f"{row.concept_key} {row.label} {' '.join(row.aliases)}")
    return any(item in token for item in ("status", "flag", "active", "inactive", "type", "category"))


def _is_name_like(row: SemanticConceptCandidate) -> bool:
    token = _norm_text(f"{row.concept_key} {row.label}")
    return bool(_NAME_HINT_RE.search(token)) or token.endswith(" name")


def _is_id_like(row: SemanticConceptCandidate) -> bool:
    token = _norm_text(f"{row.concept_key} {row.label}")
    return token.endswith(" id") or token.endswith("_id") or " identifier" in token or " key" in token


def _sort_candidates(rows: Sequence[SemanticConceptCandidate]) -> List[SemanticConceptCandidate]:
    return sorted(rows, key=lambda row: row.score, reverse=True)


def _concept_key(value: Any) -> str:
    token = str(value or "").strip()
    if token == "":
        return ""
    token = _NON_WORD_RE.sub("_", token).strip("_")
    return token.upper()


def _concept_key_from_metric_ref(metric_ref: str) -> str:
    tail = str(metric_ref or "").split(":", 1)[-1]
    return _concept_key(tail)


def _domain_key_from_name(base_domain_name: Optional[str], base_domain_id: int) -> str:
    text = str(base_domain_name or "").strip()
    if text == "":
        return f"DOMAIN_{int(base_domain_id)}"
    return _concept_key(text)


def _column_key(row: Mapping[str, Any]) -> str:
    return str(row.get("column_key") or "").strip().lower()


def _norm_text(value: Any) -> str:
    return _norm_token(value).replace("_", " ")


def _norm_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text == "":
        return ""
    text = _NON_WORD_RE.sub("_", text).strip("_")
    return text


def _build_ngrams(prompt: str) -> List[str]:
    words = [item for item in _WORD_RE.findall(str(prompt or "").lower()) if item]
    out: List[str] = []
    for n in (4, 3, 2, 1):
        for idx in range(0, max(0, len(words) - n + 1)):
            out.append("_".join(words[idx : idx + n]))
    return list(dict.fromkeys(out))


def _build_in_clause(prefix: str, values: Iterable[int]) -> Tuple[str, Dict[str, Any]]:
    params: Dict[str, Any] = {}
    placeholders: List[str] = []
    for idx, value in enumerate(values):
        key = f"{prefix}{idx}"
        params[key] = int(value)
        placeholders.append(f":{key}")
    return (", ".join(placeholders) if placeholders else "NULL"), params


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None
