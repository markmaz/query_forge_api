from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Sequence

from pydantic import ValidationError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import NLP_TIER2_ENABLED, SEMANTIC_PLAN_LLM_MAX_TOKENS, SEMANTIC_PLAN_LLM_TIMEOUT_SECONDS
from app.config.llm_resolver import build_llm_client_for_role
from app.constants.llm_roles import LLMRole
from app.exceptions.forge_error import ForgeError
from app.nlp.normalization import normalize_prompt
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain.planner_concept_scoring_policy_service import PlannerConceptScoringPolicyService
from app.services.domain.planner_projection_policy_service import PlannerProjectionPolicyService
from app.services.domain.planner_semantic_join_policy_service import PlannerSemanticJoinPolicyService
from app.services.domain.planner_semantic_projection_policy_service import PlannerSemanticProjectionPolicyService
from app.services.domain.planner_semantic_time_policy_service import PlannerSemanticTimePolicyService
from app.services.llm.llm_client import LLMClient
from app.services.planner.semantic_extract_service import SemanticExtractService
from app.services.semantic.concept_retrieval_service import ConceptRetrievalService
from app.services.semantic.concept_to_column_service import ConceptToColumnService
from app.services.semantic.constrained_column_vector_service import ConstrainedColumnVectorService
from app.services.semantic.deterministic_matcher import DeterministicMatcher
from app.services.semantic.domain_selection_service import DomainSelectionService
from app.services.semantic.value_alias_resolution_service import ValueAliasResolutionService
from app.nlp.tier2_spacy.pipeline import run_tier2_with_meta

from app.services.semantic.plan.column_guardrail import ColumnGuardrail
from app.services.semantic.plan.concept_scorer import ConceptScorer
from app.services.semantic.plan.filter_builder import ForcedFilterBuilder
from app.services.semantic.plan.models import LLMPlanPayload, PlanningRequest, SlotDrivenIntent
from app.services.semantic.plan.plan_validator import PlanValidator
from app.services.semantic.plan.sql_json_builder import SqlJsonBuilder
from app.services.semantic.plan.utils import (
    _dict_get,
    _elapsed_ms,
    _infer_intent_entity,
    _norm_entity,
    _resolve_school_literal,
    _to_int,
    _trim,
)
from app.services.semantic.plan.value_alias_applier import ValueAliasApplier

SEMANTIC_EXTRACT_FALLBACK_ERRORS = (ForgeError, OSError, RuntimeError, TypeError, ValueError)
TIER2_RUNNER_FALLBACK_ERRORS = (ForgeError, OSError, RuntimeError, TypeError, ValueError)


class PlanService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        deterministic: Optional[DeterministicMatcher] = None,
        concept_retrieval: Optional[ConceptRetrievalService] = None,
        concept_to_column: Optional[ConceptToColumnService] = None,
        column_vector: Optional[ConstrainedColumnVectorService] = None,
        domain_selector: Optional[DomainSelectionService] = None,
        value_alias_resolver: Optional[ValueAliasResolutionService] = None,
        projection_policy_service: Optional[PlannerProjectionPolicyService] = None,
        concept_scoring_policy_service: Optional[PlannerConceptScoringPolicyService] = None,
        semantic_join_policy_service: Optional[PlannerSemanticJoinPolicyService] = None,
        semantic_projection_policy_service: Optional[PlannerSemanticProjectionPolicyService] = None,
        semantic_time_policy_service: Optional[PlannerSemanticTimePolicyService] = None,
        llm_client: Optional[LLMClient] = None,
        tier2_runner: Optional[Any] = None,
        semantic_extractor: Optional[SemanticExtractService] = None,
    ) -> None:
        _sql = sql or ForgeMetaSQL()
        _concept_scoring = concept_scoring_policy_service or PlannerConceptScoringPolicyService(sql=_sql)
        _semantic_join = semantic_join_policy_service or PlannerSemanticJoinPolicyService(sql=_sql)
        _semantic_projection = semantic_projection_policy_service or PlannerSemanticProjectionPolicyService(sql=_sql)
        _semantic_time = semantic_time_policy_service or PlannerSemanticTimePolicyService(sql=_sql)
        _projection = projection_policy_service or PlannerProjectionPolicyService(sql=_sql)
        _value_alias_resolver = value_alias_resolver or ValueAliasResolutionService(sql=_sql)

        self._deterministic = deterministic or DeterministicMatcher()
        self._concept_to_column = concept_to_column or ConceptToColumnService(sql=_sql)
        self._column_vector = column_vector or ConstrainedColumnVectorService(sql=_sql)
        self._domain_selector = domain_selector or DomainSelectionService(sql=_sql)
        self._projection_policy_service = _projection
        self._semantic_extractor = semantic_extractor or SemanticExtractService()
        self._tier2_runner = tier2_runner or run_tier2_with_meta

        self._concept_scorer = ConceptScorer(
            sql=_sql,
            concept_retrieval=concept_retrieval,
            concept_scoring_policy_service=_concept_scoring,
            value_alias_resolver=_value_alias_resolver,
        )
        self._column_guardrail = ColumnGuardrail(
            semantic_time_policy_service=_semantic_time,
            concept_scoring_policy_service=_concept_scoring,
        )
        self._filter_builder = ForcedFilterBuilder(
            semantic_projection_policy_service=_semantic_projection,
        )
        self._sql_json_builder = SqlJsonBuilder(
            semantic_join_policy_service=_semantic_join,
        )
        self._plan_validator = PlanValidator(
            semantic_join_policy_service=_semantic_join,
            semantic_projection_policy_service=_semantic_projection,
            projection_policy_service=_projection,
            filter_builder=self._filter_builder,
        )
        self._value_alias_applier = ValueAliasApplier(sql=_sql)

        self._explicit_llm = llm_client is not None
        self._llm = llm_client or LLMClient(timeout_seconds=SEMANTIC_PLAN_LLM_TIMEOUT_SECONDS)
        self._llm_runtime_meta: Dict[str, Any] = {
            "source": "bootstrap",
            "role": LLMRole.PLANNER,
            "llm_id": None,
            "provider": "generic",
            "model": str(getattr(self._llm, "_model", "") or ""),
            "endpoint": str(getattr(self._llm, "_endpoint", "") or ""),
        }

    def _resolve_runtime_llm(self, *, workspace_id: str, llm_id_override: Optional[int] = None) -> None:
        if self._explicit_llm:
            return
        resolved = build_llm_client_for_role(
            workspace_id=workspace_id,
            role=LLMRole.PLANNER,
            llm_id_override=llm_id_override,
            timeout_seconds=None,
        )
        self._llm = resolved.client
        self._llm_runtime_meta = {
            "source": resolved.source,
            "role": resolved.role,
            "llm_id": resolved.llm_id,
            "provider": resolved.provider,
            "model": resolved.model,
            "endpoint": resolved.endpoint,
        }

    def plan(self, payload: Dict[str, Any], *, include_llm: bool = True) -> Dict[str, Any]:
        try:
            req = PlanningRequest.model_validate(payload or {})
        except ValidationError as exc:
            raise ForgeError("Invalid planning request", status_code=400, details={"errors": exc.errors()}) from exc

        workspace_id = str(req.workspace_id or "").strip()
        vertical_norm = str(req.vertical_norm or "generic").strip().lower() or "generic"
        prompt = str(req.prompt or "").strip()
        if workspace_id == "" or prompt == "":
            raise ForgeError("workspace_id and prompt are required", status_code=400)
        normalized_prompt = normalize_prompt(prompt)
        prompt = normalized_prompt or prompt
        intent_entity = _infer_intent_entity(prompt)

        max_concepts = max(1, min(24, int(req.max_concepts)))
        max_columns = max(1, min(120, int(req.max_columns)))

        timings_ms: Dict[str, int] = {}
        warnings: List[str] = []

        t_extract = time.perf_counter()
        semantic_extract_payload: Dict[str, Any] = {
            "normalized_text": prompt, "slots": {}, "ents": [], "model": {}, "warnings": [],
        }
        try:
            semantic_extract_payload = self._semantic_extractor.extract(prompt)
            normalized = str((semantic_extract_payload.get("normalized_text") or "")).strip()
            if normalized:
                prompt = normalized
                semantic_extract_payload["normalized_text"] = prompt
        except SEMANTIC_EXTRACT_FALLBACK_ERRORS:
            warnings.append("semantic_extract_failed")
            semantic_extract_payload = {
                "normalized_text": prompt, "slots": {}, "ents": [], "model": {},
                "warnings": ["semantic_extract_failed"],
            }
        timings_ms["semantic_extract"] = _elapsed_ms(t_extract)
        warnings.extend([str(w) for w in semantic_extract_payload.get("warnings", []) if str(w).strip()])

        t_slot_intent = time.perf_counter()
        slot_intent = self._concept_scorer.build_slot_driven_intent(
            prompt=prompt,
            vertical_norm=vertical_norm,
            semantic_extract_payload=semantic_extract_payload,
        )
        timings_ms["slot_intent"] = _elapsed_ms(t_slot_intent)

        t0 = time.perf_counter()
        deterministic = self._deterministic.match(prompt)
        deterministic_extracted_values = (
            list(deterministic.get("extracted_values", []))
            if isinstance(deterministic, dict) and isinstance(deterministic.get("extracted_values"), list)
            else []
        )
        timings_ms["deterministic"] = _elapsed_ms(t0)

        tier2_payload: Dict[str, Any] = {"plan_ir": {}, "model": {"enabled": bool(NLP_TIER2_ENABLED)}, "timings_ms": {"tier2": 0}}
        if NLP_TIER2_ENABLED:
            t_tier2 = time.perf_counter()
            try:
                tier2_payload = self._tier2_runner(prompt)
            except TIER2_RUNNER_FALLBACK_ERRORS:
                warnings.append("tier2_runner_failed")
                tier2_payload = {"plan_ir": {}, "model": {"enabled": True, "version": "error"}, "timings_ms": {}}
            timings_ms["tier2"] = int((time.perf_counter() - t_tier2) * 1000)
            tier2_ms = _to_int(((tier2_payload.get("timings_ms") or {}).get("tier2")))
            if tier2_ms is not None:
                timings_ms["tier2"] = tier2_ms
        else:
            timings_ms["tier2"] = 0

        tier2_plan_ir = tier2_payload.get("plan_ir") if isinstance(tier2_payload, dict) else {}
        if isinstance(tier2_plan_ir, dict):
            warnings.extend(str(item) for item in list(tier2_plan_ir.get("warnings") or []) if str(item).strip())
        tier2_entity = _norm_entity(_dict_get(tier2_plan_ir, "entities", "subject_entity"))
        if tier2_entity:
            intent_entity = tier2_entity
        tier2_extracted_values = ConceptScorer.extract_values_from_tier2_plan_ir(tier2_plan_ir)
        if tier2_extracted_values:
            deterministic_extracted_values = ConceptScorer.merge_extracted_values(
                deterministic_extracted_values, tier2_extracted_values,
            )
            if isinstance(deterministic, dict):
                deterministic["extracted_values"] = deterministic_extracted_values

        t0b = time.perf_counter()
        lexical_hits = self._concept_scorer.lexical_alias_concept_hits(prompt=prompt, vertical_norm=vertical_norm)
        lexical_keys = [str(hit.get("concept_key") or "").strip().upper() for hit in lexical_hits if hit.get("concept_key")]
        timings_ms["lexical_alias"] = _elapsed_ms(t0b)

        t1 = time.perf_counter()
        slot_scoped = self._concept_scorer.search_slot_scoped_concepts(
            prompt=prompt,
            slot_intent=slot_intent,
            vertical_norm=vertical_norm,
            max_concepts=max_concepts,
            deterministic_matches=deterministic.get("matched") if isinstance(deterministic, dict) else None,
        )
        concept_vector = {
            "query_text": prompt,
            "slot_queries": slot_scoped.get("queries", {}),
            "metric_hits": slot_scoped.get("metric_hits", []),
            "dimension_hits": slot_scoped.get("dimension_hits", []),
            "subgroup_hits": slot_scoped.get("subgroup_hits", []),
            "time_keys": [item.key for item in slot_intent.normalized_time],
            "hits": slot_scoped.get("hits", []),
        }
        for key, value in dict(slot_scoped.get("timings_ms", {})).items():
            timings_ms[f"concept_vector_{key}"] = int(value)
        concept_vector["hits"] = self._concept_scorer.merge_concept_hits(
            vector_hits=concept_vector.get("hits", [])[:max_concepts],
            lexical_hits=lexical_hits,
            max_concepts=max_concepts,
            has_org_district_signal=bool(slot_intent.org_district_terms),
        )
        concept_keys = [str(hit.get("concept_key") or "").upper() for hit in concept_vector.get("hits", [])]
        concept_info = self._concept_scorer.load_concept_details(vertical_norm=vertical_norm, concept_keys=concept_keys)
        concept_vector["hits"] = self._concept_scorer.apply_intent_entity_to_concept_hits(
            hits=concept_vector.get("hits", []),
            concept_info=concept_info,
            intent_entity=intent_entity,
            max_concepts=max_concepts,
            always_include_keys=lexical_keys,
        )
        concept_vector["hits"] = self._concept_scorer.apply_tier2_concept_boosts(
            hits=concept_vector.get("hits", []),
            plan_ir=tier2_plan_ir,
            max_concepts=max_concepts,
            always_include_keys=lexical_keys,
        )
        original_hit_count = len(concept_vector.get("hits", []))
        concept_vector["hits"] = self._concept_scorer.rebalance_identifier_heavy_hits(
            prompt=prompt,
            hits=concept_vector.get("hits", []),
            concept_info=concept_info,
            max_concepts=max_concepts,
            always_include_keys=lexical_keys,
            has_subgroup_intent=bool(slot_intent.subgroup_terms),
        )
        concept_vector["hits"] = ConceptScorer.inject_time_concept_hits(
            hits=concept_vector.get("hits", []),
            slot_intent=slot_intent,
            max_concepts=max_concepts,
        )
        if len(concept_vector.get("hits", [])) < original_hit_count:
            warnings.append("identifier_concepts_downranked")
        if slot_intent.metric_terms and not concept_vector.get("metric_hits"):
            warnings.append("metric_concept_unresolved")
        timings_ms["concept_vector"] = _elapsed_ms(t1)

        t1b = time.perf_counter()
        resolved_constraints = self._concept_scorer.resolve_prompt_value_constraints(
            prompt=prompt,
            vertical_norm=vertical_norm,
            concept_hits=concept_vector.get("hits", []),
        )
        concept_vector["hits"] = ConceptScorer.apply_constraint_overrides_to_concept_hits(
            prompt=prompt,
            concept_hits=concept_vector.get("hits", []),
            resolved_constraints=resolved_constraints,
            max_concepts=max_concepts,
        )
        timings_ms["value_alias_resolution"] = _elapsed_ms(t1b)

        selected_domain_id: Optional[int] = req.domain_id
        t2 = time.perf_counter()
        concept_mapping = self._concept_to_column.map_concepts_to_columns(
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            concept_hits=concept_vector.get("hits", []),
            max_columns=max_columns,
            domain_id=selected_domain_id,
            intent_entity=intent_entity,
        )
        concept_mapping["mapped_columns"] = concept_mapping.get("mapped_columns", [])[:max_columns]
        warnings.extend([str(w) for w in concept_mapping.get("warnings", []) if str(w).strip()])
        timings_ms["concept_mapping"] = _elapsed_ms(t2)

        t2b = time.perf_counter()
        domain_selection = self._domain_selector.choose_domain_id(
            workspace_id=workspace_id,
            mapped_columns=concept_mapping.get("mapped_columns", []),
            required_concept_keys=concept_mapping.get("concepts", []),
            prompt=prompt,
            preselected_domain_id=req.domain_id,
        )
        if req.domain_id is None and domain_selection.get("domain_id") is not None:
            selected_domain_id = _to_int(domain_selection.get("domain_id"))
            concept_mapping = self._concept_to_column.map_concepts_to_columns(
                workspace_id=workspace_id,
                vertical_norm=vertical_norm,
                concept_hits=concept_vector.get("hits", []),
                max_columns=max_columns,
                domain_id=selected_domain_id,
                intent_entity=intent_entity,
            )
            concept_mapping["mapped_columns"] = concept_mapping.get("mapped_columns", [])[:max_columns]
            warnings.extend([str(w) for w in concept_mapping.get("warnings", []) if str(w).strip()])
        else:
            selected_domain_id = (
                _to_int(domain_selection.get("domain_id"))
                if domain_selection.get("domain_id") is not None
                else selected_domain_id
            )
        timings_ms["domain_selection"] = _elapsed_ms(t2b)

        role_guardrails = self._column_guardrail.build(
            slot_intent=slot_intent,
            prompt=prompt,
            mapped_columns=concept_mapping.get("mapped_columns", []),
        )
        warnings.extend(role_guardrails.get("warnings", []))
        allowed_candidate_columns = role_guardrails.get("allowed_columns") or concept_mapping.get("mapped_columns", [])
        allowed_model_column_ids = {
            _to_int(row.get("model_column_id"))
            for row in allowed_candidate_columns
            if isinstance(row, dict) and _to_int(row.get("model_column_id")) is not None
        }
        allowed_model_column_ids = {int(mid) for mid in allowed_model_column_ids if mid is not None}

        t3 = time.perf_counter()
        column_vector = self._column_vector.search(
            prompt=prompt,
            workspace_id=workspace_id,
            candidate_columns=allowed_candidate_columns,
            concept_hits=concept_vector.get("hits", []),
            max_columns=max_columns,
            domain_id=selected_domain_id,
        )
        raw_column_hits = [dict(row) for row in column_vector.get("hits", []) if isinstance(row, dict)]
        if allowed_model_column_ids:
            raw_column_hits = [
                row for row in raw_column_hits
                if (_to_int(row.get("model_column_id")) or -1) in allowed_model_column_ids
            ]
        column_vector["hits"] = raw_column_hits[:max_columns]
        timings_ms["column_vector"] = _elapsed_ms(t3)
        if len([tok for tok in re.findall(r"[a-z0-9]+", str(prompt or "").lower()) if tok]) >= 5 and len(column_vector["hits"]) < 10:
            warnings.append("candidate_columns_collapsed_below_10")

        concept_mapping_payload: Dict[str, Any] = {
            "concepts": concept_mapping.get("concepts", []),
            "mapped_columns": concept_mapping.get("mapped_columns", []),
        }
        if concept_mapping.get("warnings"):
            concept_mapping_payload["warnings"] = concept_mapping.get("warnings", [])
        if bool(req.debug):
            concept_mapping_payload["ranked_candidates_by_concept"] = concept_mapping.get(
                "ranked_candidates_by_concept", {}
            )

        response: Dict[str, Any] = {
            "prompt": prompt,
            "deterministic": deterministic,
            "concept_vector": concept_vector,
            "concept_mapping": concept_mapping_payload,
            "column_vector": column_vector,
            "spacy": {
                "normalized_text": semantic_extract_payload.get("normalized_text"),
                "ents": semantic_extract_payload.get("ents") or [],
                "by_label": semantic_extract_payload.get("by_label") or {},
                "slots": semantic_extract_payload.get("slots") or {},
                "intent": {
                    "metric_terms": slot_intent.metric_terms,
                    "dimension_terms": slot_intent.dimension_terms,
                    "subgroup_terms": slot_intent.subgroup_terms,
                    "time_terms": slot_intent.time_terms,
                    "org_school_terms": slot_intent.org_school_terms,
                    "org_district_terms": slot_intent.org_district_terms,
                    "normalized_time": [item.__dict__ for item in slot_intent.normalized_time],
                },
                "model": semantic_extract_payload.get("model") or {},
                "warnings": semantic_extract_payload.get("warnings") or [],
            },
        }

        if include_llm:
            self._resolve_runtime_llm(workspace_id=workspace_id, llm_id_override=req.llm_id)
            t4 = time.perf_counter()
            llm_plan = self._plan_with_llm(
                workspace_id=workspace_id,
                prompt=prompt,
                vertical_norm=vertical_norm,
                domain_id=selected_domain_id,
                concept_hits=concept_vector.get("hits", []),
                concept_info=concept_info,
                mapped_columns=concept_mapping.get("mapped_columns", []),
                column_hits=column_vector.get("hits", []),
                max_concepts=max_concepts,
                max_columns=max_columns,
                resolved_constraints=resolved_constraints,
                explicit_concept_keys=lexical_keys,
                intent_entity=intent_entity,
                extracted_values=deterministic_extracted_values,
                tier2_plan_ir=tier2_plan_ir,
                semantic_extract_payload=semantic_extract_payload,
                slot_intent=slot_intent,
                allowed_model_column_ids=allowed_model_column_ids,
                role_guardrails=role_guardrails,
            )
            timings_ms["llm"] = _elapsed_ms(t4)
            llm_warnings = [str(w) for w in llm_plan.pop("_warnings", []) if str(w).strip()]
            if llm_warnings:
                warnings.extend(llm_warnings)
            response["llm_plan"] = {
                "model": str(self._llm_runtime_meta.get("model") or ""),
                "llm_resolution": dict(self._llm_runtime_meta),
                **llm_plan,
            }
        else:
            timings_ms["llm"] = 0

        response["debug"] = {
            "timings_ms": timings_ms,
            "warnings": warnings,
            "slot_retrieval_counts": {
                "metric_hits": len(concept_vector.get("metric_hits") or []),
                "dimension_hits": len(concept_vector.get("dimension_hits") or []),
                "subgroup_hits": len(concept_vector.get("subgroup_hits") or []),
                "time_keys": len(concept_vector.get("time_keys") or []),
            },
            "semantic_extract": {
                "normalized_text": semantic_extract_payload.get("normalized_text"),
                "by_label": semantic_extract_payload.get("by_label") or {},
                "slots": semantic_extract_payload.get("slots") or {},
                "intent": {
                    "metric_terms": slot_intent.metric_terms,
                    "dimension_terms": slot_intent.dimension_terms,
                    "subgroup_terms": slot_intent.subgroup_terms,
                    "time_terms": slot_intent.time_terms,
                    "org_school_terms": slot_intent.org_school_terms,
                    "org_district_terms": slot_intent.org_district_terms,
                    "normalized_time": [item.__dict__ for item in slot_intent.normalized_time],
                },
                "ents": semantic_extract_payload.get("ents") or [],
                "model": semantic_extract_payload.get("model") or {},
                "warnings": semantic_extract_payload.get("warnings") or [],
            },
        }
        if NLP_TIER2_ENABLED or bool(req.debug):
            response["debug"]["tier2"] = {
                "plan_ir": tier2_plan_ir if isinstance(tier2_plan_ir, dict) else {},
                "model": (tier2_payload or {}).get("model") if isinstance(tier2_payload, dict) else {},
            }
        if bool(req.debug):
            response["debug"]["resolved_constraints"] = resolved_constraints
            response["debug"]["domain_selection"] = domain_selection
        return response

    def _plan_with_llm(
        self,
        *,
        workspace_id: str,
        prompt: str,
        vertical_norm: str,
        domain_id: Optional[int],
        concept_hits: Sequence[Dict[str, Any]],
        concept_info: Dict[str, Dict[str, Any]],
        mapped_columns: Sequence[Dict[str, Any]],
        column_hits: Sequence[Dict[str, Any]],
        max_concepts: int,
        max_columns: int,
        resolved_constraints: Sequence[Dict[str, Any]],
        explicit_concept_keys: Sequence[str],
        intent_entity: Optional[str],
        extracted_values: Sequence[Dict[str, Any]],
        tier2_plan_ir: Optional[Dict[str, Any]],
        semantic_extract_payload: Optional[Dict[str, Any]],
        slot_intent: SlotDrivenIntent,
        allowed_model_column_ids: set[int],
        role_guardrails: Dict[str, Any],
    ) -> Dict[str, Any]:
        concepts_for_llm: List[Dict[str, Any]] = []
        for hit in concept_hits[:max_concepts]:
            key = str(hit.get("concept_key") or "").upper()
            info = concept_info.get(key, {})
            concepts_for_llm.append({
                "concept_key": key,
                "semantic_type": info.get("semantic_type"),
                "sub_type": info.get("sub_type"),
                "entity": info.get("entity"),
                "description": _trim(str(info.get("description") or ""), 180),
                "score": hit.get("score"),
                "source": hit.get("source"),
            })

        by_mid: Dict[int, Dict[str, Any]] = {}
        for row in list(column_hits) + list(mapped_columns):
            try:
                mid = int(row.get("model_column_id"))
            except (TypeError, ValueError):
                continue
            if allowed_model_column_ids and mid not in allowed_model_column_ids:
                continue
            existing = by_mid.get(mid)
            if existing is None:
                by_mid[mid] = {
                    "model_column_id": mid,
                    "workspace_table_id": _to_int(row.get("workspace_table_id")),
                    "table_name": row.get("table_name"),
                    "column_name": row.get("column_name"),
                    "concept_key": row.get("concept_key"),
                    "weight": row.get("weight"),
                    "score": row.get("score"),
                }
            else:
                if existing.get("score") is None and row.get("score") is not None:
                    existing["score"] = row.get("score")
                if not existing.get("concept_key") and row.get("concept_key"):
                    existing["concept_key"] = row.get("concept_key")
        columns_for_llm = list(by_mid.values())[:max_columns]

        skeleton = self._sql_json_builder.build_plan_skeleton(
            prompt=prompt,
            domain_id=domain_id,
            slot_intent=slot_intent,
            role_guardrails=role_guardrails,
            candidate_columns=columns_for_llm,
        )
        forced_filters = ForcedFilterBuilder.build_from_constraints(
            resolved_constraints=resolved_constraints,
            prompt=prompt,
        )
        name_forced_filters = self._filter_builder.build_name_filters(
            prompt=prompt,
            intent_entity=intent_entity,
            extracted_values=extracted_values,
            mapped_columns=columns_for_llm,
        )
        school_literal = _resolve_school_literal(extracted_values)
        policy_signals = self._plan_validator.projection_prompt_signals(
            prompt=prompt,
            school_literal_present=bool(school_literal),
        )
        policy_result = self._projection_policy_service.get_projection_requirements(
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            base_domain_id=domain_id,
            prompt_signals=policy_signals,
        )
        school_forced_filters = self._filter_builder.build_required_literal_filters(
            extracted_values=extracted_values,
            mapped_columns=columns_for_llm,
            required_filter_concept_keys=policy_result.get("required_filter_concept_keys") or [],
        )
        forced_filters = ForcedFilterBuilder.merge(
            existing_filters=forced_filters, forced_filters=name_forced_filters, prompt=prompt,
        )
        forced_filters = ForcedFilterBuilder.merge(
            existing_filters=forced_filters, forced_filters=school_forced_filters, prompt=prompt,
        )
        tier2_forced_filters = ForcedFilterBuilder.build_tier2_filters(
            plan_ir=tier2_plan_ir if isinstance(tier2_plan_ir, dict) else {},
            mapped_columns=columns_for_llm,
        )
        forced_filters = ForcedFilterBuilder.merge(
            existing_filters=forced_filters, forced_filters=tier2_forced_filters, prompt=prompt,
        )
        semantic_forced_filters = ForcedFilterBuilder.build_semantic_extract_filters(
            semantic_extract=semantic_extract_payload if isinstance(semantic_extract_payload, dict) else {},
            mapped_columns=columns_for_llm,
            vertical_norm=vertical_norm,
        )
        forced_filters = ForcedFilterBuilder.merge(
            existing_filters=forced_filters, forced_filters=semantic_forced_filters, prompt=prompt,
        )
        forced_filters = ForcedFilterBuilder.merge(
            existing_filters=forced_filters,
            forced_filters=list(skeleton.get("filters") or []),
            prompt=prompt,
        )

        system_prompt = (
            "You are a query planner. Return JSON only with keys: sql_json, selected_columns, filters, join_plan, confidence, notes. "
            "Do not include markdown or extra keys. "
            "selected_columns must be an array of objects: {concept_key, model_column_id}. "
            "filters must be an array of objects: {concept_key, op, value}. "
            "join_plan must be an object. notes must be an array of strings. "
            "Do not invent filter values; use resolved_constraints when present. "
            "Use only candidate columns and concept keys that are provided."
        )
        user_prompt = (
            "Build a query plan from this input.\n"
            f"User prompt: {prompt}\n"
            f"Concepts: {json.dumps(concepts_for_llm, ensure_ascii=True)}\n"
            f"Candidate columns: {json.dumps(columns_for_llm, ensure_ascii=True)}\n"
            f"Allowed model column ids: {json.dumps(sorted(list(allowed_model_column_ids)), ensure_ascii=True)}\n"
            f"Planner constraints: {json.dumps(role_guardrails, ensure_ascii=True)}\n"
            f"Skeleton plan draft: {json.dumps(skeleton, ensure_ascii=True)}\n"
            f"Tier2 Plan IR: {json.dumps(tier2_plan_ir or {}, ensure_ascii=True)}\n"
            f"Resolved constraints: {json.dumps(list(resolved_constraints), ensure_ascii=True)}\n"
            f"Required filters: {json.dumps(forced_filters, ensure_ascii=True)}\n"
            "Return strict JSON only."
        )

        payload = self._llm.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=True,
            retry_invalid_schema=True,
            validator=lambda body: (
                isinstance(body.get("sql_json"), dict)
                and isinstance(body.get("selected_columns"), list)
                and isinstance(body.get("filters"), list)
            ),
            max_tokens=SEMANTIC_PLAN_LLM_MAX_TOKENS,
        )
        payload = SqlJsonBuilder.normalize_llm_payload(payload, candidate_columns=columns_for_llm)
        payload["filters"] = ForcedFilterBuilder.merge(
            existing_filters=payload.get("filters"), forced_filters=forced_filters, prompt=prompt,
        )
        payload["selected_columns"] = self._concept_scorer.minimize_selected_columns(
            selected_columns=payload.get("selected_columns"),
            prompt=prompt,
            explicit_concept_keys=explicit_concept_keys,
            forced_filters=forced_filters,
        )
        payload = SqlJsonBuilder.apply_skeleton_constraints(
            payload=payload, skeleton=skeleton, slot_intent=slot_intent, prompt=prompt,
        )

        try:
            parsed = LLMPlanPayload.model_validate(payload)
        except ValidationError as exc:
            raise ForgeError(
                "Invalid LLM planning response",
                status_code=502,
                details={"errors": exc.errors(), "payload": payload},
            ) from exc

        grounded = SqlJsonBuilder.ground_plan(
            parsed, columns_for_llm, concepts_for_llm, prompt=prompt, domain_id=domain_id,
        )
        grounded = self._value_alias_applier.apply(vertical_norm=vertical_norm, llm_plan=grounded)
        grounded, grounded_filter_warnings = self._plan_validator.enforce_grounded_org_filters(
            llm_plan=grounded,
            prompt=prompt,
            domain_id=domain_id,
            mapped_columns=columns_for_llm,
            semantic_extract=semantic_extract_payload if isinstance(semantic_extract_payload, dict) else {},
        )
        grounded, gate_warnings = self._plan_validator.apply_validity_gate(
            llm_plan=grounded,
            prompt=prompt,
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            intent_entity=intent_entity,
            extracted_values=extracted_values,
            mapped_columns=columns_for_llm,
            domain_id=domain_id,
        )
        if slot_intent.implies_count_metric(prompt):
            grounded = SqlJsonBuilder.enforce_count_commercial_rule(
                llm_plan=grounded, role_guardrails=role_guardrails,
            )
        try:
            self._sql_json_builder.validate(
                sql_json=grounded.get("sql_json"),
                allowed_model_column_ids=allowed_model_column_ids,
            )
        except ForgeError:
            fallback = self._sql_json_builder.fallback_skeleton_plan(
                prompt=prompt,
                domain_id=domain_id,
                skeleton=skeleton,
                candidate_columns=columns_for_llm,
            )
            fallback.setdefault("notes", []).append("fallback:skeleton_due_to_illegal_columns")
            return fallback
        total_warnings = [*grounded_filter_warnings, *gate_warnings]
        if total_warnings:
            grounded["_warnings"] = total_warnings
        return grounded


__all__ = ["PlanService"]
