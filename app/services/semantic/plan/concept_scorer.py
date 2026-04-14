from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.nlp.time_normalizer import CanonicalTime, normalize_time_terms
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain.planner_concept_scoring_policy_service import PlannerConceptScoringPolicyService
from app.services.semantic.concept_retrieval_service import ConceptRetrievalService
from app.services.semantic.value_alias_resolution_service import ValueAliasResolutionService
from app.services.semantic.plan.models import SlotDrivenIntent
from app.services.semantic.plan.utils import (
    _build_prompt_ngrams,
    _concept_entity_factor,
    _dedupe_text_values,
    _dict_get,
    _elapsed_ms,
    _in_clause,
    _norm_entity,
    _prompt_has_student_intent,
    _to_float,
    _to_int,
)

GENERIC_VERTICAL_NORM = "generic"


class ConceptScorer:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        concept_retrieval: Optional[ConceptRetrievalService] = None,
        concept_scoring_policy_service: Optional[PlannerConceptScoringPolicyService] = None,
        value_alias_resolver: Optional[ValueAliasResolutionService] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._concept_retrieval = concept_retrieval or ConceptRetrievalService()
        self._concept_scoring_policy_service = concept_scoring_policy_service or PlannerConceptScoringPolicyService(sql=self._sql)
        self._value_alias_resolver = value_alias_resolver or ValueAliasResolutionService(sql=self._sql)

    def build_slot_driven_intent(
        self,
        *,
        prompt: str,
        semantic_extract_payload: Dict[str, Any],
    ) -> SlotDrivenIntent:
        slots = semantic_extract_payload.get("slots") if isinstance(semantic_extract_payload, dict) else {}
        if not isinstance(slots, dict):
            slots = {}
        metric_terms = _dedupe_text_values(list(slots.get("metric") or []))
        dimension_terms = _dedupe_text_values(list(slots.get("dimensions") or []))
        subgroup_terms = _dedupe_text_values(list(slots.get("subgroups") or []))
        time_terms = _dedupe_text_values(list(slots.get("time_ranges") or []))
        org_school_terms = _dedupe_text_values(list(slots.get("org_schools") or []))
        org_district_terms = _dedupe_text_values(list(slots.get("org_districts") or []))

        if not metric_terms and re.search(r"\bhow many\b", str(prompt or "").lower()):
            metric_terms = ["count"]
        if not dimension_terms:
            for match in re.finditer(r"\bby\s+([a-z0-9_ ]{2,40})", str(prompt or "").lower()):
                value = str(match.group(1) or "").strip()
                if value:
                    dimension_terms.append(value)
        time_normalized = normalize_time_terms(time_terms, vertical=GENERIC_VERTICAL_NORM)
        if not time_normalized and re.search(r"\b(this school year|current school year)\b", str(prompt or "").lower()):
            time_normalized = [CanonicalTime(key="CURRENT_SCHOOL_YEAR", confidence=0.9, raw_text=prompt)]
        return SlotDrivenIntent(
            metric_terms=metric_terms,
            dimension_terms=dimension_terms,
            subgroup_terms=subgroup_terms,
            time_terms=time_terms,
            org_school_terms=org_school_terms,
            org_district_terms=org_district_terms,
            normalized_time=time_normalized,
        )

    def search_slot_scoped_concepts(
        self,
        *,
        prompt: str,
        slot_intent: SlotDrivenIntent,
        max_concepts: int,
        deterministic_matches: Optional[Sequence[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        timings: Dict[str, int] = {}
        queries: Dict[str, str] = {}
        metric_hits: List[Dict[str, Any]] = []
        dimension_hits: List[Dict[str, Any]] = []
        subgroup_hits: List[Dict[str, Any]] = []

        if slot_intent.metric_terms:
            metric_query = " ".join(slot_intent.metric_terms)
            queries["metric"] = metric_query
            t_metric = time.perf_counter()
            metric_hits = self.search_concepts_for_query(
                query=metric_query,
                max_concepts=min(10, max_concepts),
                deterministic_matches=deterministic_matches,
            )
            timings["metric"] = _elapsed_ms(t_metric)
        if slot_intent.dimension_terms:
            dim_terms = [re.sub(r"^\s*by\s+", "", term, flags=re.IGNORECASE).strip() for term in slot_intent.dimension_terms]
            dimension_query = " ".join([term for term in dim_terms if term])
            if dimension_query:
                queries["dimension"] = dimension_query
                t_dimension = time.perf_counter()
                dimension_hits = self.search_concepts_for_query(
                    query=dimension_query,
                    max_concepts=min(20, max_concepts),
                    deterministic_matches=deterministic_matches,
                )
                timings["dimension"] = _elapsed_ms(t_dimension)
        if slot_intent.subgroup_terms:
            subgroup_query = " ".join(slot_intent.subgroup_terms)
            queries["subgroup"] = subgroup_query
            t_subgroup = time.perf_counter()
            subgroup_hits = self.search_concepts_for_query(
                query=subgroup_query,
                max_concepts=min(20, max_concepts),
                deterministic_matches=deterministic_matches,
            )
            timings["subgroup"] = _elapsed_ms(t_subgroup)

        has_slot_queries = bool(queries)
        if not has_slot_queries:
            queries["fallback"] = prompt
            t_fallback = time.perf_counter()
            fallback_hits = self.search_concepts_for_query(
                query=prompt,
                max_concepts=max_concepts,
                deterministic_matches=deterministic_matches,
            )
            timings["fallback"] = _elapsed_ms(t_fallback)
            return {
                "queries": queries,
                "metric_hits": [],
                "dimension_hits": [],
                "subgroup_hits": [],
                "hits": fallback_hits,
                "timings_ms": timings,
            }

        role_keys = {
            "metric": {str(row.get("concept_key") or "").strip().upper() for row in metric_hits},
            "dimension": {str(row.get("concept_key") or "").strip().upper() for row in dimension_hits},
            "subgroup": {str(row.get("concept_key") or "").strip().upper() for row in subgroup_hits},
        }
        all_keys = sorted({key for keys in role_keys.values() for key in keys if key})
        concept_info = self.load_concept_details(concept_keys=all_keys)
        metric_filtered = self.filter_hits_for_role(
            hits=metric_hits,
            concept_info=concept_info,
            allowed_semantic_types={"metric", "measure"},
            role="metric",
        )
        dimension_filtered = self.filter_hits_for_role(
            hits=dimension_hits,
            concept_info=concept_info,
            allowed_semantic_types={"dimension", "attribute", "group_by", "geography"},
            role="dimension",
        )
        subgroup_filtered = self.filter_hits_for_role(
            hits=subgroup_hits,
            concept_info=concept_info,
            allowed_semantic_types={"subgroup", "population", "flag", "descriptor", "attribute"},
            role="subgroup",
        )
        subgroup_filtered = ConceptScorer.ensure_subgroup_race_hits(
            subgroup_hits=subgroup_filtered,
            slot_intent=slot_intent,
        )
        merged: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for bucket in (metric_filtered, dimension_filtered, subgroup_filtered):
            for row in bucket:
                key = str(row.get("concept_key") or "").strip().upper()
                if key == "" or key in seen:
                    continue
                seen.add(key)
                merged.append(dict(row))
        merged.sort(key=lambda row: -(_to_float(row.get("score")) or 0.0))
        return {
            "queries": queries,
            "metric_hits": metric_filtered,
            "dimension_hits": dimension_filtered,
            "subgroup_hits": subgroup_filtered,
            "hits": merged[:max_concepts],
            "timings_ms": timings,
        }

    def search_concepts_for_query(
        self,
        *,
        query: str,
        max_concepts: int,
        deterministic_matches: Optional[Sequence[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        out = self._concept_retrieval.search(
            prompt=query,
            max_concepts=max_concepts,
            deterministic_matches=deterministic_matches,
        )
        return [dict(row) for row in list(out.get("hits") or []) if isinstance(row, dict)]

    def filter_hits_for_role(
        self,
        *,
        hits: Sequence[Dict[str, Any]],
        concept_info: Dict[str, Dict[str, Any]],
        allowed_semantic_types: set[str],
        role: str,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for row in hits:
            key = str(row.get("concept_key") or "").strip().upper()
            if key == "":
                continue
            info = concept_info.get(key, {})
            semantic_type = str(info.get("semantic_type") or "").strip().lower()
            is_identifier = ConceptScorer.is_identifier_like_concept(concept_key=key, concept_info=info)
            score = _to_float(row.get("score")) or 0.0
            if role == "metric" and is_identifier:
                score -= 0.35
            if allowed_semantic_types and semantic_type and semantic_type not in allowed_semantic_types and not (
                role == "metric" and is_identifier
            ):
                continue
            out.append({**dict(row), "score": round(score, 4), "semantic_type": semantic_type})
        out.sort(key=lambda item: -(_to_float(item.get("score")) or 0.0))
        return out

    @staticmethod
    def ensure_subgroup_race_hits(
        *,
        subgroup_hits: Sequence[Dict[str, Any]],
        slot_intent: SlotDrivenIntent,
    ) -> List[Dict[str, Any]]:
        rows = [dict(row) for row in subgroup_hits if isinstance(row, dict)]
        if not slot_intent.subgroup_terms:
            return rows
        seen = {str(row.get("concept_key") or "").strip().upper() for row in rows}
        additions = (
            ("RACE", 0.86),
            ("ETHNICITY", 0.84),
        )
        for concept_key, score in additions:
            if concept_key in seen:
                continue
            rows.append(
                {
                    "concept_key": concept_key,
                    "score": score,
                    "source": "subgroup_guardrail",
                    "semantic_type": "subgroup",
                }
            )
            seen.add(concept_key)
        rows.sort(key=lambda item: -(_to_float(item.get("score")) or 0.0))
        return rows

    @staticmethod
    def inject_time_concept_hits(
        *,
        hits: Sequence[Dict[str, Any]],
        slot_intent: SlotDrivenIntent,
        max_concepts: int,
    ) -> List[Dict[str, Any]]:
        if not slot_intent.normalized_time:
            return [dict(row) for row in hits]
        out = [dict(row) for row in hits if isinstance(row, dict)]
        keys = {str(row.get("concept_key") or "").strip().upper() for row in out}
        if "SCHOOL_YEAR" not in keys:
            out.append({"concept_key": "SCHOOL_YEAR", "score": 0.91, "source": "time_normalizer"})
        out.sort(key=lambda row: -(_to_float(row.get("score")) or 0.0))
        return out[:max_concepts]

    def load_concept_details(self, *, concept_keys: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        keys = [str(k or "").strip().upper() for k in concept_keys if str(k or "").strip()]
        if not keys:
            return {}
        in_sql, in_params = _in_clause("ck", keys)
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              concept_key,
              semantic_type,
              sub_type,
              entity,
              description,
              is_identifier
            FROM semantic_concept
            WHERE concept_key IN ({in_sql})
              AND `status` = 'active'
            ORDER BY concept_key
            """,
            in_params,
        )
        out: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            key = str(row.get("concept_key") or "").upper()
            if key and key not in out:
                out[key] = dict(row)
        return out

    def apply_intent_entity_to_concept_hits(
        self,
        *,
        hits: Sequence[Dict[str, Any]],
        concept_info: Dict[str, Dict[str, Any]],
        intent_entity: Optional[str],
        max_concepts: int,
        always_include_keys: Sequence[str] = (),
    ) -> List[Dict[str, Any]]:
        intent = _norm_entity(intent_entity)
        if intent is None:
            return [dict(row) for row in hits]

        required = {str(k or "").strip().upper() for k in always_include_keys if str(k or "").strip()}
        rows: List[Dict[str, Any]] = []
        for raw in hits:
            row = dict(raw)
            concept_key = str(row.get("concept_key") or "").strip().upper()
            entity = _norm_entity((concept_info.get(concept_key) or {}).get("entity"))
            factor = _concept_entity_factor(
                intent_entity=intent,
                concept_key=concept_key,
                concept_entity=entity,
                policy_service=self._concept_scoring_policy_service,
            )
            score = _to_float(row.get("score")) or 0.0
            row["score"] = round(score * factor, 4)
            row["entity_factor"] = factor
            rows.append(row)

        rows.sort(key=lambda item: -(_to_float(item.get("score")) or 0.0))
        return ConceptScorer.ensure_keys_in_hits(hits=rows, required_keys=required, max_concepts=max_concepts)

    def apply_tier2_concept_boosts(
        self,
        *,
        hits: Sequence[Dict[str, Any]],
        plan_ir: Optional[Dict[str, Any]],
        max_concepts: int,
        always_include_keys: Sequence[str] = (),
    ) -> List[Dict[str, Any]]:
        rows = [dict(row) for row in hits if isinstance(row, dict)]
        if not rows:
            return rows

        required = {str(k or "").strip().upper() for k in always_include_keys if str(k or "").strip()}
        subject_entity = _norm_entity(_dict_get(plan_ir, "entities", "subject_entity"))
        slots = dict((plan_ir or {}).get("slots") or {}) if isinstance(plan_ir, dict) else {}
        has_name = bool(slots.get("names"))
        has_school = bool(slots.get("school"))
        has_district = bool(slots.get("district"))
        has_grade = bool(slots.get("grade"))
        has_race = bool(slots.get("race"))

        for row in rows:
            concept_key = str(row.get("concept_key") or "").strip().upper()
            score = _to_float(row.get("score")) or 0.0
            factor = 1.0

            if subject_entity:
                factor *= _concept_entity_factor(
                    intent_entity=subject_entity,
                    concept_key=concept_key,
                    concept_entity=subject_entity if concept_key.startswith(subject_entity.upper() + "_") else None,
                    policy_service=self._concept_scoring_policy_service,
                )
                if subject_entity == "student" and concept_key.startswith(("STAFF_", "PARENT_")) and "NAME" in concept_key:
                    action_key = "student_subject_staff_name_multiplier" if concept_key.startswith("STAFF_") else "student_subject_parent_name_multiplier"
                    context_tokens = ["subject_student", "staff_name_concept" if concept_key.startswith("STAFF_") else "parent_name_concept"]
                    factor *= self._concept_scoring_policy_service.resolve_factor(
                        action_key=action_key,
                        context_tokens=context_tokens,
                        default=0.55,
                    )
                if subject_entity in {"staff", "parent"} and concept_key.startswith("STUDENT_") and "NAME" in concept_key:
                    factor *= self._concept_scoring_policy_service.resolve_factor(
                        action_key="staff_or_parent_subject_student_name_multiplier",
                        context_tokens=[f"subject_{subject_entity}", "student_name_concept"],
                        default=0.6,
                    )

            if has_name and ("NAME" in concept_key or concept_key.endswith("_ID")):
                if subject_entity == "student" and concept_key.startswith("STUDENT_") and "NAME" in concept_key:
                    factor *= self._concept_scoring_policy_service.resolve_factor(
                        action_key="name_slot_student_name_multiplier",
                        context_tokens=["has_name_slot", "subject_student", "student_name_concept"],
                        default=1.3,
                    )
                elif concept_key in {"FIRST_NAME", "LAST_NAME", "MIDDLE_NAME"}:
                    factor *= self._concept_scoring_policy_service.resolve_factor(
                        action_key="name_slot_generic_name_multiplier",
                        context_tokens=["has_name_slot", "generic_name_concept"],
                        default=1.1,
                    )
            if has_school and ("SCHOOL" in concept_key or concept_key in {"DISTRICT_NAME", "LEA_ID"}):
                factor *= self._concept_scoring_policy_service.resolve_factor(
                    action_key="school_slot_multiplier",
                    context_tokens=["has_school_slot", "school_slot_match"],
                    default=1.25,
                )
            if has_district and "DISTRICT" in concept_key:
                factor *= self._concept_scoring_policy_service.resolve_factor(
                    action_key="district_slot_multiplier",
                    context_tokens=["has_district_slot", "district_slot_match"],
                    default=1.2,
                )
            if has_grade and "GRADE" in concept_key:
                factor *= self._concept_scoring_policy_service.resolve_factor(
                    action_key="grade_slot_multiplier",
                    context_tokens=["has_grade_slot", "grade_slot_match"],
                    default=1.18,
                )
            if has_race and ("RACE" in concept_key or "ETHNIC" in concept_key):
                factor *= self._concept_scoring_policy_service.resolve_factor(
                    action_key="race_slot_multiplier",
                    context_tokens=["has_race_slot", "race_slot_match"],
                    default=1.18,
                )

            row["score"] = round(score * factor, 4)
            row["tier2_factor"] = round(factor, 4)

        rows.sort(key=lambda item: -(_to_float(item.get("score")) or 0.0))
        return ConceptScorer.ensure_keys_in_hits(hits=rows, required_keys=required, max_concepts=max_concepts)

    @staticmethod
    def extract_values_from_tier2_plan_ir(plan_ir: Any) -> List[Dict[str, Any]]:
        if not isinstance(plan_ir, dict):
            return []
        slots = plan_ir.get("slots")
        if not isinstance(slots, dict):
            return []

        out: List[Dict[str, Any]] = []
        for name in list(slots.get("names") or []):
            if not isinstance(name, dict):
                continue
            value = str(name.get("value") or "").strip()
            if value:
                out.append({"kind": "name", "value": value, "source": "tier2"})

        for school in list(slots.get("school") or []):
            if not isinstance(school, dict):
                continue
            value = str(school.get("value") or "").strip()
            if value:
                out.append({"kind": "school_name", "value": value, "source": "tier2"})

        for district in list(slots.get("district") or []):
            if not isinstance(district, dict):
                continue
            value = str(district.get("value") or "").strip()
            if value:
                out.append({"kind": "district_name", "value": value, "source": "tier2"})
        return out

    @staticmethod
    def merge_extracted_values(
        existing: Sequence[Dict[str, Any]],
        additional: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        out = [dict(item) for item in existing if isinstance(item, dict)]
        seen = {
            f"{str(item.get('kind') or '').strip().lower()}::{str(item.get('value') or '').strip().lower()}"
            for item in out
        }
        for item in additional:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip().lower()
            value = str(item.get("value") or "").strip()
            if kind == "" or value == "":
                continue
            key = f"{kind}::{value.lower()}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"kind": kind, "value": value, "source": item.get("source") or "tier2"})
        return out

    @staticmethod
    def ensure_keys_in_hits(
        *,
        hits: Sequence[Dict[str, Any]],
        required_keys: Sequence[str] | set[str],
        max_concepts: int,
    ) -> List[Dict[str, Any]]:
        required = {str(k or "").strip().upper() for k in required_keys if str(k or "").strip()}
        rows = [dict(row) for row in hits if isinstance(row, dict)]
        if not required:
            return rows[:max_concepts]

        present = {str(row.get("concept_key") or "").strip().upper() for row in rows}
        missing = required - present
        if missing:
            # required keys are expected to already exist in the input rows when called by this service
            rows.extend({"concept_key": key, "score": 2.0, "source": "lexical_alias"} for key in sorted(missing))

        if len(rows) <= max_concepts:
            return rows

        keep_required = [row for row in rows if str(row.get("concept_key") or "").strip().upper() in required]
        keep_other = [row for row in rows if str(row.get("concept_key") or "").strip().upper() not in required]
        keep_other.sort(key=lambda row: -(_to_float(row.get("score")) or 0.0))
        out = keep_required[:]
        if len(out) < max_concepts:
            out.extend(keep_other[: max_concepts - len(out)])
        return out

    @staticmethod
    def is_identifier_like_concept(*, concept_key: str, concept_info: Dict[str, Any]) -> bool:
        key = str(concept_key or "").strip().upper()
        if key.endswith(("_ID", "_CODE", "_KEY", "_SK")):
            return True

        semantic_type = str(concept_info.get("semantic_type") or "").strip().lower()
        sub_type = str(concept_info.get("sub_type") or "").strip().lower()
        is_identifier = concept_info.get("is_identifier")
        if semantic_type in {"identifier", "id"}:
            return True
        if sub_type in {"identifier", "id", "code", "key", "surrogate_key", "sk"}:
            return True
        if str(is_identifier).strip() in {"1", "true", "True"}:
            return True
        return False

    @staticmethod
    def is_noisy_projection_concept(*, concept_key: str) -> bool:
        key = str(concept_key or "").strip().upper()
        noisy_tokens = (
            "ADDRESS",
            "LATITUDE",
            "LONGITUDE",
            "ZIP",
            "CODE",
            "NCES",
            "STREET",
        )
        return any(token in key for token in noisy_tokens)

    @staticmethod
    def prompt_requests_identifier(prompt: str) -> bool:
        text = str(prompt or "").strip().lower()
        if text == "":
            return False
        return re.search(r"\b(id|ids|identifier|identifiers|code|codes|key|keys|sk)\b", text) is not None

    def rebalance_identifier_heavy_hits(
        self,
        *,
        prompt: str,
        hits: Sequence[Dict[str, Any]],
        concept_info: Dict[str, Dict[str, Any]],
        max_concepts: int,
        always_include_keys: Sequence[str] = (),
        has_subgroup_intent: bool = False,
    ) -> List[Dict[str, Any]]:
        force_keys = {str(key or "").strip().upper() for key in always_include_keys if str(key or "").strip()}
        deduped: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for hit in hits:
            key = str(hit.get("concept_key") or "").strip().upper()
            if key == "" or key in seen:
                continue
            seen.add(key)
            deduped.append(dict(hit))
        deduped = deduped[: max(max_concepts, len(force_keys))]
        if not deduped:
            return []

        if ConceptScorer.prompt_requests_identifier(prompt):
            return ConceptScorer.ensure_keys_in_hits(hits=deduped, required_keys=force_keys, max_concepts=max_concepts)

        non_identifier_hits: List[Dict[str, Any]] = []
        identifier_hits: List[Dict[str, Any]] = []
        for hit in deduped:
            key = str(hit.get("concept_key") or "").strip().upper()
            if key in force_keys:
                non_identifier_hits.append(dict(hit))
                continue
            info = concept_info.get(key, {})
            if ConceptScorer.is_identifier_like_concept(concept_key=key, concept_info=info):
                adjusted = dict(hit)
                score = _to_float(adjusted.get("score")) or 0.0
                action_key = "identifier_penalty_subgroup" if has_subgroup_intent else "identifier_penalty_default"
                penalty_context = ["identifier_rebalance"]
                if has_subgroup_intent:
                    penalty_context.append("subgroup_intent")
                penalty = self._concept_scoring_policy_service.resolve_penalty(
                    action_key=action_key,
                    context_tokens=penalty_context,
                    default=0.35 if has_subgroup_intent else 0.2,
                )
                adjusted["score"] = round(score - penalty, 4)
                identifier_hits.append(adjusted)
            else:
                non_identifier_hits.append(dict(hit))

        non_identifier_hits.sort(key=lambda row: -(_to_float(row.get("score")) or 0.0))
        identifier_hits.sort(key=lambda row: -(_to_float(row.get("score")) or 0.0))

        if not non_identifier_hits:
            return identifier_hits[:max_concepts]

        identifier_limit = self._concept_scoring_policy_service.resolve_integer(
            action_key="identifier_limit",
            context_tokens=["identifier_rebalance"],
            default=1,
        )
        out = list(non_identifier_hits[:max_concepts])
        remaining = max(0, max_concepts - len(out))
        if remaining > 0 and identifier_hits:
            out.extend(identifier_hits[: min(remaining, identifier_limit)])
        out = out[: max(max_concepts, len(force_keys))]
        return ConceptScorer.ensure_keys_in_hits(hits=out, required_keys=force_keys, max_concepts=max_concepts)

    def lexical_alias_concept_hits(self, *, prompt: str) -> List[Dict[str, Any]]:
        ngrams = _build_prompt_ngrams(prompt)
        if not ngrams:
            return []
        matches: Dict[str, Dict[str, Any]] = {}
        for ngram in ngrams:
            rows = self._sql.execute_query_mappings(
                """
                SELECT
                  concept_key,
                  alias_key,
                  match_kind,
                  weight
                FROM semantic_concept_alias
                WHERE (
                    (match_kind = 'exact' AND LOWER(alias_key) = :ngram)
                    OR
                    (match_kind = 'contains' AND :ngram LIKE CONCAT('%', LOWER(alias_key), '%'))
                  )
                ORDER BY
                  weight DESC,
                  id ASC
                """,
                {"ngram": ngram},
            )
            for row in rows:
                concept_key = str(row.get("concept_key") or "").strip().upper()
                if concept_key == "":
                    continue
                weight = _to_float(row.get("weight")) or 1.0
                match_kind = str(row.get("match_kind") or "").strip().lower() or "contains"
                score = round(2.0 + min(1.0, weight), 4)
                candidate = {
                    "concept_key": concept_key,
                    "score": score,
                    "source": "lexical_alias",
                    "alias_key": row.get("alias_key"),
                    "match_kind": match_kind,
                    "matched_ngram": ngram,
                    "weight": weight,
                }
                existing = matches.get(concept_key)
                if existing is None or ConceptScorer._lexical_rank(candidate) > ConceptScorer._lexical_rank(existing):
                    matches[concept_key] = candidate
        return sorted(matches.values(), key=lambda row: -float(row.get("score") or 0.0))

    def merge_concept_hits(
        self,
        *,
        vector_hits: Sequence[Dict[str, Any]],
        lexical_hits: Sequence[Dict[str, Any]],
        max_concepts: int,
        has_org_district_signal: bool,
    ) -> List[Dict[str, Any]]:
        by_key: Dict[str, Dict[str, Any]] = {}
        for row in vector_hits:
            key = str(row.get("concept_key") or "").strip().upper()
            if key == "":
                continue
            by_key[key] = dict(row)

        lexical_keys: List[str] = []
        for row in lexical_hits:
            key = str(row.get("concept_key") or "").strip().upper()
            if key == "":
                continue
            lexical_keys.append(key)
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = dict(row)
                continue
            merged = dict(existing)
            merged["score"] = round(
                max(_to_float(existing.get("score")) or 0.0, _to_float(row.get("score")) or 0.0),
                4,
            )
            merged["source"] = "lexical_alias+vector"
            if row.get("alias_key") is not None:
                merged["alias_key"] = row.get("alias_key")
            by_key[key] = merged

        rows = list(by_key.values())
        if not has_org_district_signal:
            weak_aliases = {"district", "county"}
            for row in rows:
                alias_key = str(row.get("alias_key") or "").strip().lower()
                if alias_key in weak_aliases:
                    score = _to_float(row.get("score")) or 0.0
                    row["score"] = round(score * 0.2, 4)
                    row["source"] = "weak_lexical_alias"
        rows.sort(key=lambda row: -(_to_float(row.get("score")) or 0.0))
        rows = rows[: max(max_concepts, len(set(lexical_keys)))]
        return ConceptScorer.ensure_keys_in_hits(hits=rows, required_keys=set(lexical_keys), max_concepts=max_concepts)

    def resolve_prompt_value_constraints(
        self,
        *,
        prompt: str,
        concept_hits: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        resolved = self._value_alias_resolver.resolve(
            prompt=prompt,
        )
        if not resolved:
            return []

        concept_hit_keys = {
            str(hit.get("concept_key") or "").strip().upper()
            for hit in concept_hits
            if str(hit.get("concept_key") or "").strip()
        }
        filtered = [
            row
            for row in resolved
            if str(row.get("concept_key") or "").strip().upper() in concept_hit_keys
        ]
        if not filtered:
            return []

        locale_explicit = re.search(r"\blocale\b", str(prompt or "").lower()) is not None
        has_district_name = any(str(row.get("concept_key") or "").strip().upper() == "DISTRICT_NAME" for row in filtered)
        if has_district_name and not locale_explicit:
            filtered = [row for row in filtered if str(row.get("concept_key") or "").strip().upper() != "LOCALE"]
        return filtered

    def minimize_selected_columns(
        self,
        *,
        selected_columns: Any,
        prompt: str,
        explicit_concept_keys: Sequence[str],
        forced_filters: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not isinstance(selected_columns, list):
            return []
        student_intent = _prompt_has_student_intent(prompt)
        explicit = {str(k or "").strip().upper() for k in explicit_concept_keys if str(k or "").strip()}
        explicit.update(
            str(item.get("concept_key") or "").strip().upper()
            for item in forced_filters
            if isinstance(item, dict) and str(item.get("concept_key") or "").strip()
        )

        allowed = set(explicit)
        if student_intent:
            allowed.update(
                {
                    "STUDENT_ID",
                    "FIRST_NAME",
                    "LAST_NAME",
                    "STUDENT_FIRST_NAME",
                    "STUDENT_LAST_NAME",
                    "SCHOOL_NAME",
                    "STUDENT_SCHOOL_NAME",
                    "DISTRICT_NAME",
                }
            )

        out: List[Dict[str, Any]] = []
        seen: set[Tuple[str, int]] = set()
        for item in selected_columns:
            if not isinstance(item, dict):
                continue
            concept_key = str(item.get("concept_key") or "").strip().upper()
            model_column_id = _to_int(item.get("model_column_id"))
            if concept_key == "" or model_column_id is None:
                continue
            if concept_key not in allowed:
                continue
            if ConceptScorer.is_noisy_projection_concept(concept_key=concept_key) and concept_key not in explicit:
                continue
            key = (concept_key, model_column_id)
            if key in seen:
                continue
            seen.add(key)
            out.append({"concept_key": concept_key, "model_column_id": model_column_id})
        return out

    @staticmethod
    def apply_constraint_overrides_to_concept_hits(
        *,
        prompt: str,
        concept_hits: Sequence[Dict[str, Any]],
        resolved_constraints: Sequence[Dict[str, Any]],
        max_concepts: int,
    ) -> List[Dict[str, Any]]:
        rows = [dict(row) for row in concept_hits if isinstance(row, dict)]
        if not rows:
            return rows
        locale_explicit = re.search(r"\blocale\b", str(prompt or "").lower()) is not None
        has_district_name = any(
            str(item.get("concept_key") or "").strip().upper() == "DISTRICT_NAME"
            for item in resolved_constraints
        )
        if has_district_name and not locale_explicit:
            rows = [row for row in rows if str(row.get("concept_key") or "").strip().upper() != "LOCALE"]
        return rows[:max_concepts]

    @staticmethod
    def _lexical_rank(row: Dict[str, Any]) -> Tuple[float, int, int]:
        score = float(row.get("score") or 0.0)
        ngram_len = len(str(row.get("matched_ngram") or ""))
        exact = 1 if str(row.get("match_kind") or "").lower() == "exact" else 0
        return score, ngram_len, exact
