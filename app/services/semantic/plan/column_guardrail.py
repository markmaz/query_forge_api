from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from app.nlp.time_normalizer import CanonicalTime
from app.services.domain.planner_concept_scoring_policy_service import PlannerConceptScoringPolicyService
from app.services.domain.planner_semantic_time_policy_service import PlannerSemanticTimePolicyService
from app.services.semantic.plan.concept_scorer import ConceptScorer
from app.services.semantic.plan.models import SlotDrivenIntent
from app.services.semantic.plan.utils import _to_float, _to_int


class ColumnGuardrail:
    def __init__(
        self,
        *,
        semantic_time_policy_service: Optional[PlannerSemanticTimePolicyService] = None,
        concept_scoring_policy_service: Optional[PlannerConceptScoringPolicyService] = None,
    ) -> None:
        self._semantic_time_policy_service = semantic_time_policy_service or PlannerSemanticTimePolicyService()
        self._concept_scoring_policy_service = concept_scoring_policy_service or PlannerConceptScoringPolicyService()

    def build(
        self,
        *,
        slot_intent: SlotDrivenIntent,
        prompt: str,
        mapped_columns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        rows = [dict(row) for row in mapped_columns if isinstance(row, dict)]
        if not rows:
            return {
                "warnings": [],
                "metric_columns": [],
                "dimension_columns": [],
                "subgroup_columns": [],
                "time_columns": [],
                "allowed_columns": [],
            }
        has_slot_signal = bool(
            slot_intent.metric_terms
            or slot_intent.dimension_terms
            or slot_intent.subgroup_terms
            or slot_intent.normalized_time
        )
        if not has_slot_signal:
            return {
                "warnings": [],
                "metric_columns": [],
                "dimension_columns": [],
                "subgroup_columns": [],
                "time_columns": [],
                "allowed_columns": rows,
            }
        warnings: List[str] = []
        metrics = self._pick_columns_for_terms(
            terms=slot_intent.metric_terms,
            rows=rows,
            default_patterns=("count", "enrollment", "attendance", "rate", "metric"),
        )
        dimensions = self._pick_columns_for_terms(
            terms=slot_intent.dimension_terms,
            rows=rows,
            default_patterns=("grade", "race", "gender", "school", "district", "dimension"),
        )
        subgroups = self._pick_columns_for_terms(
            terms=slot_intent.subgroup_terms,
            rows=rows,
            default_patterns=("el", "ell", "esl", "lep", "mll", "iep", "sped", "subgroup", "flag"),
        )
        if slot_intent.subgroup_terms:
            subgroup_concepts = {"RACE", "ETHNICITY", "RACE_ETHNICITY", "HAS_HISPANIC_LATINO_ETHNICITY"}
            subgroup_seed_rows = [
                dict(row)
                for row in rows
                if str(row.get("concept_key") or "").strip().upper() in subgroup_concepts
            ]
            subgroups = ColumnGuardrail._merge_ranked_rows(primary=subgroups, secondary=subgroup_seed_rows, limit=20)
        time_columns = self._pick_time_columns(
            slot_intent=slot_intent,
            rows=rows,
            prompt=prompt,
        )
        if slot_intent.metric_terms and not metrics:
            warnings.append("metric_concept_unresolved")
        if slot_intent.dimension_terms and not dimensions:
            warnings.append("grade_level_dimension_unresolved")

        allow_identifiers = slot_intent.allows_identifier_projection(prompt)
        allowed: List[Dict[str, Any]] = []
        seen_mid: set[int] = set()
        for bucket in (metrics, dimensions, subgroups, time_columns):
            for row in bucket:
                mid = _to_int(row.get("model_column_id"))
                if mid is None or mid in seen_mid:
                    continue
                seen_mid.add(mid)
                allowed.append(dict(row))

        if not allowed:
            allowed = rows
        if not allow_identifiers:
            non_identifier = [
                row
                for row in allowed
                if not ConceptScorer.is_identifier_like_concept(
                    concept_key=str(row.get("concept_key") or ""),
                    concept_info={
                        "semantic_type": row.get("semantic_type"),
                        "sub_type": row.get("sub_type"),
                        "is_identifier": row.get("is_identifier"),
                    },
                )
            ]
            if non_identifier:
                allowed = non_identifier
            elif allowed:
                warnings.append("only_identifier_candidates_found")
        else:
            for row in rows:
                concept_key = str(row.get("concept_key") or "")
                if not ConceptScorer.is_identifier_like_concept(
                    concept_key=concept_key,
                    concept_info={
                        "semantic_type": row.get("semantic_type"),
                        "sub_type": row.get("sub_type"),
                        "is_identifier": row.get("is_identifier"),
                    },
                ):
                    continue
                mid = _to_int(row.get("model_column_id"))
                if mid is None or mid in seen_mid:
                    continue
                seen_mid.add(mid)
                allowed.append(dict(row))

        return {
            "warnings": warnings,
            "metric_columns": metrics,
            "dimension_columns": dimensions,
            "subgroup_columns": subgroups,
            "time_columns": time_columns,
            "allowed_columns": allowed,
        }

    def _pick_columns_for_terms(
        self,
        *,
        terms: Sequence[str],
        rows: Sequence[Dict[str, Any]],
        default_patterns: Sequence[str],
    ) -> List[Dict[str, Any]]:
        normalized_terms = [str(term or "").strip().lower() for term in terms if str(term or "").strip()]
        out: List[Dict[str, Any]] = []
        for row in rows:
            haystack = " ".join(
                [
                    str(row.get("concept_key") or "").strip().lower(),
                    str(row.get("column_name") or "").strip().lower(),
                    str(row.get("table_name") or "").strip().lower(),
                ]
            )
            haystack = haystack.replace("_", " ")
            term_match = False
            if normalized_terms:
                for term in normalized_terms:
                    if term in haystack:
                        term_match = True
                        break
                    tokens = [tok for tok in term.split() if len(tok) >= 3 and tok not in {"for", "the", "and", "by"}]
                    if tokens and any(tok in haystack for tok in tokens):
                        term_match = True
                        break
            if term_match:
                out.append(dict(row))
                continue
            if not normalized_terms and any(token in haystack for token in default_patterns):
                out.append(dict(row))
        out.sort(
            key=lambda item: (
                -(_to_float(item.get("effective_weight")) or _to_float(item.get("final_score")) or 0.0),
                _to_int(item.get("model_column_id")) or 0,
            )
        )
        return out[:20]

    @staticmethod
    def _merge_ranked_rows(
        *,
        primary: Sequence[Dict[str, Any]],
        secondary: Sequence[Dict[str, Any]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen: set[int] = set()
        for bucket in (primary, secondary):
            for row in bucket:
                if not isinstance(row, dict):
                    continue
                mid = _to_int(row.get("model_column_id"))
                if mid is None or mid in seen:
                    continue
                seen.add(mid)
                out.append(dict(row))
        out.sort(
            key=lambda item: (
                -(_to_float(item.get("effective_weight")) or _to_float(item.get("final_score")) or 0.0),
                _to_int(item.get("model_column_id")) or 0,
            )
        )
        return out[: max(1, int(limit))]

    def _pick_time_columns(
        self,
        *,
        slot_intent: SlotDrivenIntent,
        rows: Sequence[Dict[str, Any]],
        prompt: str,
    ) -> List[Dict[str, Any]]:
        if not slot_intent.normalized_time and re.search(r"\b(school year|this year|current year)\b", str(prompt or "").lower()):
            slot_intent.normalized_time = [CanonicalTime(key="CURRENT_SCHOOL_YEAR", confidence=0.84, raw_text=prompt)]

        time_rows = [dict(row) for row in rows if "year" in str(row.get("column_name") or "").lower() or "year" in str(row.get("concept_key") or "").lower()]
        if not time_rows:
            return []

        best = self._select_preferred_time_column(
            domain_hint=ColumnGuardrail._infer_domain_hint_from_rows(rows),
            mapped_columns_for_time_concept=time_rows,
        )
        if best is None:
            return []
        return [best]

    @staticmethod
    def _infer_domain_hint_from_rows(rows: Sequence[Dict[str, Any]]) -> str:
        text = " ".join(str(row.get("table_name") or "").lower() for row in rows if isinstance(row, dict))
        if "enroll" in text or "student" in text:
            return "enrollment"
        return "generic"

    def _select_preferred_time_column(
        self,
        *,
        domain_hint: str,
        mapped_columns_for_time_concept: Sequence[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        return self._semantic_time_policy_service.select_preferred_time_column(
            domain_hint=domain_hint,
            mapped_columns_for_time_concept=mapped_columns_for_time_concept,
        )
