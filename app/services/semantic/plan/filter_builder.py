from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.domain.planner_semantic_projection_policy_service import PlannerSemanticProjectionPolicyService
from app.services.semantic.value_alias_service import canonicalize_value
from app.services.semantic.plan.utils import (
    _to_float,
    _to_int,
    _resolve_name_literal,
    _resolve_school_literal,
    _norm_entity,
    _prompt_has_student_intent,
    _dedupe_text_values,
)


class ForcedFilterBuilder:
    def __init__(
        self,
        *,
        semantic_projection_policy_service: Optional[PlannerSemanticProjectionPolicyService] = None,
    ) -> None:
        self._semantic_projection_policy_service = semantic_projection_policy_service or PlannerSemanticProjectionPolicyService()

    def build_name_filters(
        self,
        *,
        prompt: str,
        intent_entity: Optional[str],
        extracted_values: Sequence[Dict[str, Any]],
        mapped_columns: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        name_literal = _resolve_name_literal(prompt=prompt, extracted_values=extracted_values)
        if name_literal is None:
            return []
        entity = _norm_entity(intent_entity) or ("student" if _prompt_has_student_intent(prompt) else None)
        if entity is None:
            return []

        preferred_concepts = self._semantic_projection_policy_service.name_filter_concepts(entity=entity)
        available_concepts = {
            str(row.get("concept_key") or "").strip().upper()
            for row in mapped_columns
            if str(row.get("concept_key") or "").strip()
        }
        selected_concept = next(
            (concept for concept in preferred_concepts if concept in available_concepts),
            preferred_concepts[0] if preferred_concepts else None,
        )
        if selected_concept is None:
            return []

        value = name_literal
        parts = [p for p in re.split(r"\s+", value) if p]
        if len(parts) > 1:
            if "LAST_NAME" in selected_concept:
                value = parts[-1]
            elif "FIRST_NAME" in selected_concept:
                value = parts[0]

        return [{"concept_key": selected_concept, "op": "=", "value": value}]

    def build_required_literal_filters(
        self,
        *,
        extracted_values: Sequence[Dict[str, Any]],
        mapped_columns: Sequence[Dict[str, Any]],
        required_filter_concept_keys: Sequence[str],
    ) -> List[Dict[str, Any]]:
        school_value = _resolve_school_literal(extracted_values)
        if school_value is None or not required_filter_concept_keys:
            return []
        available_concepts = {
            str(row.get("concept_key") or "").strip().upper()
            for row in mapped_columns
            if isinstance(row, dict) and str(row.get("concept_key") or "").strip()
        }
        for required_concept in required_filter_concept_keys:
            for concept_key in self._semantic_projection_policy_service.concept_family(concept_key=required_concept):
                if concept_key in available_concepts:
                    return [{"concept_key": concept_key, "op": "contains", "value": school_value}]
        return []

    @staticmethod
    def build_from_constraints(
        *,
        resolved_constraints: Sequence[Dict[str, Any]],
        prompt: str,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        locale_explicit = re.search(r"\blocale\b", str(prompt or "").lower()) is not None
        has_district_name = any(
            str(item.get("concept_key") or "").strip().upper() == "DISTRICT_NAME"
            for item in resolved_constraints
        )
        for item in resolved_constraints:
            concept_key = str(item.get("concept_key") or "").strip().upper()
            canonical = item.get("canonical_value")
            if concept_key == "" or canonical is None:
                continue
            if has_district_name and not locale_explicit and concept_key == "LOCALE":
                continue
            out.append({"concept_key": concept_key, "op": "=", "value": canonical})
        return out

    @staticmethod
    def build_tier2_filters(
        *,
        plan_ir: Dict[str, Any],
        mapped_columns: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not isinstance(plan_ir, dict):
            return []
        slots = plan_ir.get("slots")
        if not isinstance(slots, dict):
            return []
        available_concepts = {
            str(row.get("concept_key") or "").strip().upper()
            for row in mapped_columns
            if isinstance(row, dict) and str(row.get("concept_key") or "").strip()
        }

        out: List[Dict[str, Any]] = []
        for school in list(slots.get("school") or []):
            if not isinstance(school, dict):
                continue
            value = str(school.get("value") or "").strip()
            if value == "":
                continue
            for concept_key in ("SCHOOL_NAME", "STUDENT_SCHOOL_NAME"):
                if concept_key in available_concepts:
                    out.append({"concept_key": concept_key, "op": "contains", "value": value})
                    break

        for district in list(slots.get("district") or []):
            if not isinstance(district, dict):
                continue
            value = str(district.get("value") or "").strip()
            if value == "":
                continue
            if "DISTRICT_NAME" in available_concepts:
                out.append({"concept_key": "DISTRICT_NAME", "op": "=", "value": value})

        for grade in list(slots.get("grade") or []):
            if not isinstance(grade, dict):
                continue
            value = str(grade.get("value") or "").strip()
            if value == "":
                continue
            for concept_key in ("GRADE_LEVEL", "STUDENT_GRADE_LEVEL"):
                if concept_key in available_concepts:
                    out.append({"concept_key": concept_key, "op": "=", "value": value})
                    break

        for race in list(slots.get("race") or []):
            if not isinstance(race, dict):
                continue
            value = str(race.get("value") or "").strip()
            if value == "":
                continue
            for concept_key in ("RACE", "RACE_ETHNICITY", "ETHNICITY"):
                if concept_key in available_concepts:
                    out.append({"concept_key": concept_key, "op": "=", "value": value})
                    break
        return out

    @staticmethod
    def build_semantic_extract_filters(
        *,
        semantic_extract: Dict[str, Any],
        mapped_columns: Sequence[Dict[str, Any]],
        vertical_norm: str,
    ) -> List[Dict[str, Any]]:
        if not isinstance(semantic_extract, dict):
            return []
        by_label = semantic_extract.get("by_label") if isinstance(semantic_extract.get("by_label"), dict) else {}
        slots = semantic_extract.get("slots") if isinstance(semantic_extract.get("slots"), dict) else {}

        available_concepts = {
            str(row.get("concept_key") or "").strip().upper()
            for row in mapped_columns
            if isinstance(row, dict) and str(row.get("concept_key") or "").strip()
        }

        out: List[Dict[str, Any]] = []
        org_district_values = _dedupe_text_values(
            list(slots.get("org_districts") or []) + list(by_label.get("ORG_DISTRICT") or [])
        )
        if org_district_values:
            district_value = org_district_values[0]
            district_concept = None
            for concept_key in ("DISTRICT_NAME", "COUNTY_NAME"):
                if concept_key in available_concepts:
                    district_concept = concept_key
                    break
            if district_concept:
                out.append({"concept_key": district_concept, "op": "=", "value": district_value})

        subgroup_values = _dedupe_text_values(
            list(slots.get("subgroups") or []) + list(by_label.get("SUBGROUP") or [])
        )
        for subgroup in subgroup_values:
            race_value = canonicalize_value("RACE", subgroup, vertical=vertical_norm)
            if race_value and "RACE" in available_concepts:
                out.append({"concept_key": "RACE", "op": "=", "value": race_value})
                continue
            if race_value and "RACE_ETHNICITY" in available_concepts:
                out.append({"concept_key": "RACE_ETHNICITY", "op": "=", "value": race_value})
                continue
            ethnicity_value = canonicalize_value("ETHNICITY", subgroup, vertical=vertical_norm)
            if ethnicity_value and "ETHNICITY" in available_concepts:
                out.append({"concept_key": "ETHNICITY", "op": "=", "value": ethnicity_value})
                continue

            lowered = subgroup.lower()
            if not any(token in lowered for token in (" english learner", "english learner", "english learners", " el ", "ell", "esl", "lep", "mll")):
                if lowered not in {"el", "ell", "esl", "lep", "mll", "el students"}:
                    continue
            row = ForcedFilterBuilder._pick_best_el_subgroup_row(mapped_columns=mapped_columns)
            if not isinstance(row, dict):
                continue
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if concept_key == "":
                continue
            column_name = str(row.get("column_name") or "").strip().lower()
            value: Any = True if concept_key.startswith("IS_") or column_name.startswith("is_") else "EL"
            out.append({"concept_key": concept_key, "op": "=", "value": value})
        return out

    @staticmethod
    def merge(
        *,
        existing_filters: Any,
        forced_filters: Sequence[Dict[str, Any]],
        prompt: str,
    ) -> List[Dict[str, Any]]:
        base: List[Dict[str, Any]] = []
        if isinstance(existing_filters, list):
            for item in existing_filters:
                if isinstance(item, dict):
                    base.append(dict(item))

        locale_explicit = re.search(r"\blocale\b", str(prompt or "").lower()) is not None
        forced_keys = {str(item.get("concept_key") or "").strip().upper() for item in forced_filters}
        if "DISTRICT_NAME" in forced_keys and not locale_explicit:
            base = [item for item in base if str(item.get("concept_key") or "").strip().upper() != "LOCALE"]

        index_by_key: Dict[str, int] = {}
        for idx, item in enumerate(base):
            key = str(item.get("concept_key") or "").strip().upper()
            if key and key not in index_by_key:
                index_by_key[key] = idx

        for forced in forced_filters:
            key = str(forced.get("concept_key") or "").strip().upper()
            if key == "":
                continue
            payload = {
                "concept_key": key,
                "op": str(forced.get("op") or "="),
                "value": forced.get("value"),
            }
            if key in index_by_key:
                base[index_by_key[key]] = payload
            else:
                index_by_key[key] = len(base)
                base.append(payload)
        return base

    @staticmethod
    def _pick_best_el_subgroup_row(*, mapped_columns: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        candidates: List[Tuple[Tuple[int, float, int], Dict[str, Any]]] = []
        for row in mapped_columns:
            if not isinstance(row, dict):
                continue
            concept_key = str(row.get("concept_key") or "").strip().upper()
            column_name = str(row.get("column_name") or "").strip().lower()
            if concept_key == "" and column_name == "":
                continue

            key_for_match = concept_key.lower()
            col_for_match = column_name.lower()
            match_score = 9
            if concept_key in {"IS_EL", "IS_ELL", "IS_ESL", "IS_LEP"} or column_name in {"is_el", "is_ell", "is_esl", "is_lep"}:
                match_score = 0
            elif "english_learner" in key_for_match or "english_language_learner" in key_for_match:
                match_score = 1
            elif "english_learner" in col_for_match or "english_language_learner" in col_for_match:
                match_score = 1
            elif re.search(r"(^|_)(el|ell|esl|lep|mll)(_|$)", key_for_match):
                match_score = 2
            elif re.search(r"(^|_)(el|ell|esl|lep|mll)(_|$)", col_for_match):
                match_score = 2
            elif "language" in key_for_match and "learner" in key_for_match:
                match_score = 3
            elif "language" in col_for_match and "learner" in col_for_match:
                match_score = 3
            else:
                continue

            weight = _to_float(row.get("effective_weight")) or _to_float(row.get("final_score")) or _to_float(row.get("weight")) or 0.0
            mid = _to_int(row.get("model_column_id")) or 0
            candidates.append(((match_score, -weight, mid), dict(row)))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]
