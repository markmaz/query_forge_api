from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.domain.planner_projection_policy_service import PlannerProjectionPolicyService
from app.services.domain.planner_semantic_join_policy_service import PlannerSemanticJoinPolicyService
from app.services.domain.planner_semantic_projection_policy_service import PlannerSemanticProjectionPolicyService
from app.services.semantic.plan.filter_builder import ForcedFilterBuilder
from app.services.semantic.plan.sql_json_builder import SqlJsonBuilder
from app.services.semantic.plan.utils import (
    _candidate_by_concept,
    _candidate_by_mid,
    _filters_contain_literal,
    _has_school_name_filter,
    _has_student_first_last_projection,
    _norm_entity,
    _prompt_has_student_intent,
    _requires_student_name_projection_with_school,
    _resolve_required_literal,
    _resolve_school_literal,
    _to_float,
    _to_int,
    is_grounded_value,
    _first_nonempty,
)


class PlanValidator:
    def __init__(
        self,
        *,
        semantic_join_policy_service: Optional[PlannerSemanticJoinPolicyService] = None,
        semantic_projection_policy_service: Optional[PlannerSemanticProjectionPolicyService] = None,
        projection_policy_service: Optional[PlannerProjectionPolicyService] = None,
        filter_builder: Optional[ForcedFilterBuilder] = None,
    ) -> None:
        self._semantic_join_policy_service = semantic_join_policy_service or PlannerSemanticJoinPolicyService()
        self._semantic_projection_policy_service = semantic_projection_policy_service or PlannerSemanticProjectionPolicyService()
        self._projection_policy_service = projection_policy_service or PlannerProjectionPolicyService()
        self._filter_builder = filter_builder or ForcedFilterBuilder(
            semantic_projection_policy_service=self._semantic_projection_policy_service
        )

    def enforce_grounded_org_filters(
        self,
        *,
        llm_plan: Dict[str, Any],
        prompt: str,
        domain_id: Optional[int],
        mapped_columns: Sequence[Dict[str, Any]],
        semantic_extract: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], List[str]]:
        if not isinstance(llm_plan, dict):
            return llm_plan, []

        warnings: List[str] = []
        out = dict(llm_plan)
        filters = [dict(item) for item in list(out.get("filters") or []) if isinstance(item, dict)]
        if not filters:
            return out, warnings

        slots = semantic_extract.get("slots") if isinstance(semantic_extract.get("slots"), dict) else {}
        by_label = semantic_extract.get("by_label") if isinstance(semantic_extract.get("by_label"), dict) else {}
        gazetteer_matches = [
            str(item or "").strip()
            for item in list(semantic_extract.get("gazetteer_matches") or [])
            if str(item or "").strip()
        ]
        spacy_grounding = {
            "slots": slots,
            "by_label": by_label,
            "ents": list(semantic_extract.get("ents") or []),
        }

        district_grounded = _first_nonempty(
            list(slots.get("org_districts") or [])
            + list(by_label.get("ORG_DISTRICT") or [])
            + gazetteer_matches
        )
        school_grounded = _first_nonempty(
            list(slots.get("org_schools") or [])
            + list(by_label.get("ORG_SCHOOL") or [])
            + gazetteer_matches
        )
        if district_grounded is None and school_grounded is None:
            return out, warnings

        org_concepts = {"DISTRICT_NAME", "COUNTY_NAME", "SCHOOL_NAME", "STUDENT_SCHOOL_NAME"}
        changed = False
        saw_ungrounded = False
        repaired_filters: List[Dict[str, Any]] = []
        for item in filters:
            concept_key = str(item.get("concept_key") or "").strip().upper()
            if concept_key not in org_concepts:
                repaired_filters.append(item)
                continue
            value = str(item.get("value") or "").strip()
            if value and is_grounded_value(value=value, spacy=spacy_grounding, gazetteer_matches=gazetteer_matches):
                repaired_filters.append(item)
                continue

            saw_ungrounded = True
            replacement: Optional[str] = None
            if concept_key in {"DISTRICT_NAME", "COUNTY_NAME"} and district_grounded:
                replacement = district_grounded
            elif concept_key in {"SCHOOL_NAME", "STUDENT_SCHOOL_NAME"} and school_grounded:
                replacement = school_grounded
            elif district_grounded:
                replacement = district_grounded
            elif school_grounded:
                replacement = school_grounded

            if replacement:
                next_item = dict(item)
                next_item["value"] = replacement
                repaired_filters.append(next_item)
                warnings.append("ungrounded_filter_value_replaced")
            else:
                warnings.append("ungrounded_filter_value_dropped")
            changed = True

        if saw_ungrounded:
            warnings.append("filter_value_not_grounded")
        if not changed:
            return out, list(dict.fromkeys(warnings))

        out["filters"] = repaired_filters
        sql_json, _ = SqlJsonBuilder.build_grounded_sql_json(
            prompt=prompt,
            domain_id=domain_id,
            selected_columns=[dict(item) for item in list(out.get("selected_columns") or []) if isinstance(item, dict)],
            filters=repaired_filters,
            candidate_by_mid=_candidate_by_mid(mapped_columns),
            candidate_by_concept=_candidate_by_concept(mapped_columns),
            llm_sql_json=out.get("sql_json") if isinstance(out.get("sql_json"), dict) else {},
            policy_service=self._semantic_join_policy_service,
        )
        out["sql_json"] = sql_json
        return out, list(dict.fromkeys(warnings))

    def apply_validity_gate(
        self,
        *,
        llm_plan: Dict[str, Any],
        prompt: str,
        workspace_id: str,
        vertical_norm: str,
        intent_entity: Optional[str],
        extracted_values: Sequence[Dict[str, Any]],
        mapped_columns: Sequence[Dict[str, Any]],
        domain_id: Optional[int],
    ) -> Tuple[Dict[str, Any], List[str]]:
        if not isinstance(llm_plan, dict):
            return llm_plan, []

        warnings: List[str] = []
        intent = _norm_entity(intent_entity)
        if intent is None:
            return llm_plan, warnings

        out = dict(llm_plan)
        selected_columns = [dict(item) for item in out.get("selected_columns", []) if isinstance(item, dict)]
        filters = [dict(item) for item in out.get("filters", []) if isinstance(item, dict)]
        school_literal = _resolve_school_literal(extracted_values)
        projection_with_school = _requires_student_name_projection_with_school(
            prompt=prompt,
            intent_entity=intent,
            school_literal=school_literal,
        )

        if projection_with_school:
            policy_signals = self.projection_prompt_signals(
                prompt=prompt,
                school_literal_present=bool(school_literal),
            )
            policy_result = self._projection_policy_service.get_projection_requirements(
                workspace_id=workspace_id,
                vertical_norm=vertical_norm,
                base_domain_id=domain_id,
                prompt_signals=policy_signals,
            )
            selected_columns = self._ensure_projection_policy_concepts(
                selected_columns=selected_columns,
                mapped_columns=mapped_columns,
                required_concept_keys=policy_result.get("required_concept_keys") or [],
            )
            filters = self._ensure_required_literal_filters(
                filters=filters,
                extracted_values=extracted_values,
                mapped_columns=mapped_columns,
                prompt=prompt,
                required_filter_concept_keys=policy_result.get("required_filter_concept_keys") or [],
            )
            out["selected_columns"] = selected_columns
            out["filters"] = filters

            has_first_last = _has_student_first_last_projection(selected_columns)
            has_school_filter = _has_school_name_filter(filters=filters, school_literal=school_literal)
            if not has_first_last or not has_school_filter:
                out["sql_json"] = {}
                notes_raw = out.get("notes")
                notes = list(notes_raw) if isinstance(notes_raw, list) else []
                notes.append("plan_invalid_missing_columns_or_filters")
                out["notes"] = notes
                warnings.append("plan_invalid_missing_columns_or_filters")
                return out, warnings

            out["join_plan"] = self.ensure_required_join_plan(
                join_plan=out.get("join_plan"),
                selected_columns=selected_columns,
                filters=filters,
                mapped_columns=mapped_columns,
                required_filter_concept_keys=policy_result.get("required_filter_concept_keys") or [],
                required_join_tables=policy_result.get("required_join_tables") or [],
            )

            sql_json, _ = SqlJsonBuilder.build_grounded_sql_json(
                prompt=prompt,
                domain_id=domain_id,
                selected_columns=selected_columns,
                filters=filters,
                candidate_by_mid=_candidate_by_mid(mapped_columns),
                candidate_by_concept=_candidate_by_concept(mapped_columns),
                llm_sql_json=out.get("sql_json") if isinstance(out.get("sql_json"), dict) else {},
                policy_service=self._semantic_join_policy_service,
            )
            out["sql_json"] = sql_json
            return out, warnings

        literal = _resolve_required_literal(prompt=prompt, extracted_values=extracted_values)
        if literal is None:
            return llm_plan, warnings

        if not selected_columns:
            selected_columns = self._build_default_projection(
                intent_entity=intent,
                mapped_columns=mapped_columns,
            )
            if selected_columns:
                out["selected_columns"] = selected_columns

        if not _filters_contain_literal(filters=filters, literal=literal):
            injected_filters = self._filter_builder.build_name_filters(
                prompt=prompt,
                intent_entity=intent,
                extracted_values=extracted_values,
                mapped_columns=mapped_columns,
            )
            if injected_filters:
                filters = ForcedFilterBuilder.merge(
                    existing_filters=filters,
                    forced_filters=injected_filters,
                    prompt=prompt,
                )
                out["filters"] = filters

        has_columns = bool(out.get("selected_columns"))
        has_literal_filter = _filters_contain_literal(
            filters=[dict(item) for item in out.get("filters", []) if isinstance(item, dict)],
            literal=literal,
        )

        if not has_columns or not has_literal_filter:
            out["sql_json"] = {}
            notes_raw = out.get("notes")
            notes = list(notes_raw) if isinstance(notes_raw, list) else []
            notes.append("plan_invalid_empty_or_unfiltered: missing required projection or literal filter")
            out["notes"] = notes
            warnings.append("plan_invalid_empty_or_unfiltered")
            return out, warnings

        sql_json, _ = SqlJsonBuilder.build_grounded_sql_json(
            prompt=prompt,
            domain_id=domain_id,
            selected_columns=[dict(item) for item in out.get("selected_columns", []) if isinstance(item, dict)],
            filters=[dict(item) for item in out.get("filters", []) if isinstance(item, dict)],
            candidate_by_mid=_candidate_by_mid(mapped_columns),
            candidate_by_concept=_candidate_by_concept(mapped_columns),
            llm_sql_json=out.get("sql_json") if isinstance(out.get("sql_json"), dict) else {},
            policy_service=self._semantic_join_policy_service,
        )
        out["sql_json"] = sql_json
        return out, warnings

    def projection_prompt_signals(self, *, prompt: str, school_literal_present: bool = False) -> List[str]:
        signals: set[str] = set()
        if _prompt_has_student_intent(prompt):
            signals.update({"student_listing", "listing_intent", "needs_student_identity"})
        if school_literal_present:
            signals.update({"school_literal_present", "needs_school_filter"})
        return sorted(signals)

    def ensure_required_join_plan(
        self,
        *,
        join_plan: Any,
        selected_columns: Sequence[Dict[str, Any]],
        filters: Sequence[Dict[str, Any]],
        mapped_columns: Sequence[Dict[str, Any]],
        required_filter_concept_keys: Sequence[str],
        required_join_tables: Sequence[str],
    ) -> Dict[str, Any]:
        mid_to_row = _candidate_by_mid(mapped_columns)
        selected_tables = {
            str((mid_to_row.get(_to_int(col.get("model_column_id")) or -1) or {}).get("table_name") or "").strip().lower()
            for col in selected_columns
            if isinstance(col, dict)
        }
        required_filter_keys = {
            str(item or "").strip().upper() for item in required_filter_concept_keys if str(item or "").strip()
        }
        present_filter_concepts = {
            str(item.get("concept_key") or "").strip().upper()
            for item in filters
            if isinstance(item, dict) and str(item.get("concept_key") or "").strip().upper() in required_filter_keys
        }
        return self._semantic_join_policy_service.ensure_required_join_plan(
            join_plan=join_plan,
            selected_tables=sorted(selected_tables),
            present_filter_concept_keys=sorted(present_filter_concepts),
            required_join_tables=required_join_tables,
        )

    def _ensure_projection_policy_concepts(
        self,
        *,
        selected_columns: Sequence[Dict[str, Any]],
        mapped_columns: Sequence[Dict[str, Any]],
        required_concept_keys: Sequence[str],
    ) -> List[Dict[str, Any]]:
        out = [dict(item) for item in selected_columns if isinstance(item, dict)]
        if not required_concept_keys:
            return out

        seen = {
            (_to_int(item.get("model_column_id")), str(item.get("concept_key") or "").strip().upper())
            for item in out
        }
        for item in self._build_projection_policy_columns(
            mapped_columns=mapped_columns,
            required_concept_keys=required_concept_keys,
        ):
            key = (_to_int(item.get("model_column_id")), str(item.get("concept_key") or "").strip().upper())
            if key in seen:
                continue
            out.append(item)
            seen.add(key)
        return out

    def _build_projection_policy_columns(
        self,
        *,
        mapped_columns: Sequence[Dict[str, Any]],
        required_concept_keys: Sequence[str],
    ) -> List[Dict[str, Any]]:
        by_concept: Dict[str, List[Dict[str, Any]]] = {}
        for row in mapped_columns:
            if not isinstance(row, dict):
                continue
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if concept_key:
                by_concept.setdefault(concept_key, []).append(dict(row))

        selected: List[Dict[str, Any]] = []
        seen_mid: set[int] = set()
        for required_concept in required_concept_keys:
            chosen: Optional[Dict[str, Any]] = None
            for concept_key in self._semantic_projection_policy_service.concept_family(concept_key=required_concept):
                rows = list(by_concept.get(concept_key) or [])
                if not rows:
                    continue
                rows.sort(
                    key=lambda row: (
                        0 if str(row.get("table_name") or "").strip().lower() == "dim_student" else 1,
                        -(_to_float(row.get("effective_weight")) or _to_float(row.get("final_score")) or 0.0),
                        int(row.get("model_column_id") or 0),
                    )
                )
                chosen = rows[0]
                break
            if not chosen:
                continue
            mid = _to_int(chosen.get("model_column_id"))
            concept_key = str(chosen.get("concept_key") or "").strip().upper()
            if mid is None or concept_key == "" or mid in seen_mid:
                continue
            seen_mid.add(mid)
            selected.append({"concept_key": concept_key, "model_column_id": mid})
        return selected

    def _build_default_projection(
        self,
        *,
        intent_entity: str,
        mapped_columns: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        keys = self._semantic_projection_policy_service.default_projection_concepts(entity=intent_entity)
        if not keys:
            return []
        preferred_tables = set(self._semantic_projection_policy_service.preferred_projection_tables(entity=intent_entity))

        rows_by_concept: Dict[str, List[Dict[str, Any]]] = {}
        for row in mapped_columns:
            if not isinstance(row, dict):
                continue
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if concept_key == "":
                continue
            rows_by_concept.setdefault(concept_key, []).append(dict(row))

        selected: List[Dict[str, Any]] = []
        seen_mid: set[int] = set()
        for concept_key in keys:
            best: Optional[Dict[str, Any]] = None
            for family_key in self._semantic_projection_policy_service.concept_family(concept_key=concept_key):
                rows = list(rows_by_concept.get(family_key) or [])
                if not rows:
                    continue
                rows.sort(
                    key=lambda item: (
                        0 if str(item.get("table_name") or "").strip().lower() in preferred_tables else 1,
                        -(_to_float(item.get("effective_weight")) or _to_float(item.get("final_score")) or 0.0),
                        int(item.get("model_column_id") or 0),
                    )
                )
                best = rows[0]
                break
            if not best:
                continue
            mid = _to_int(best.get("model_column_id"))
            if mid is None or mid in seen_mid:
                continue
            seen_mid.add(mid)
            selected.append({"concept_key": str(best.get("concept_key") or concept_key).strip().upper(), "model_column_id": mid})
        if not selected and intent_entity == "student":
            for concept_key in ("STUDENT_ID", "ID"):
                rows = list(rows_by_concept.get(concept_key) or [])
                if not rows:
                    continue
                rows.sort(
                    key=lambda item: (
                        0 if str(item.get("table_name") or "").strip().lower() in preferred_tables else 1,
                        -(_to_float(item.get("effective_weight")) or _to_float(item.get("final_score")) or 0.0),
                        int(item.get("model_column_id") or 0),
                    )
                )
                best = rows[0]
                mid = _to_int(best.get("model_column_id"))
                if mid is not None:
                    selected.append({"concept_key": concept_key, "model_column_id": mid})
                    break
        return selected

    def _ensure_required_literal_filters(
        self,
        *,
        filters: Sequence[Dict[str, Any]],
        extracted_values: Sequence[Dict[str, Any]],
        mapped_columns: Sequence[Dict[str, Any]],
        prompt: str,
        required_filter_concept_keys: Sequence[str],
    ) -> List[Dict[str, Any]]:
        base = [dict(item) for item in filters if isinstance(item, dict)]
        forced = self._filter_builder.build_required_literal_filters(
            extracted_values=extracted_values,
            mapped_columns=mapped_columns,
            required_filter_concept_keys=required_filter_concept_keys,
        )
        return ForcedFilterBuilder.merge(
            existing_filters=base,
            forced_filters=forced,
            prompt=prompt,
        )
