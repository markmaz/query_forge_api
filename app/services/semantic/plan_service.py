from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import (
    NLP_TIER2_ENABLED,
    SEMANTIC_PLAN_LLM_MAX_TOKENS,
    SEMANTIC_PLAN_LLM_TIMEOUT_SECONDS,
)
from app.config.llm_resolver import build_llm_client_for_role
from app.constants.llm_roles import LLMRole
from app.exceptions.forge_error import ForgeError
from app.models.ai_suggest import AddSelectEdit, SetDomainEdit, SqlColumnKey
from app.nlp.normalization import normalize_prompt
from app.nlp.time_normalizer import CanonicalTime, normalize_time_terms
from app.ports.sql_executor import ForgeQueryPort
from app.services.llm.llm_client import LLMClient
from app.services.planner.semantic_extract_service import SemanticExtractService
from app.services.sqljson_apply_service import apply_edits
from app.services.semantic.concept_retrieval_service import ConceptRetrievalService
from app.services.semantic.concept_to_column_service import ConceptToColumnService
from app.services.semantic.constrained_column_vector_service import ConstrainedColumnVectorService
from app.services.semantic.deterministic_matcher import DeterministicMatcher
from app.services.semantic.domain_selection_service import DomainSelectionService
from app.services.semantic.value_alias_service import canonicalize_value
from app.services.semantic.value_alias_resolution_service import ValueAliasResolutionService
from app.nlp.tier2_spacy.pipeline import run_tier2_with_meta


class PlanningRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    vertical_norm: str = "generic"
    prompt: str
    domain_id: Optional[int] = None
    max_concepts: int = 12
    max_columns: int = 60
    debug: bool = False
    llm_id: Optional[int] = None


class LLMSelectedColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_key: str
    model_column_id: int


class LLMFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_key: str
    op: str
    value: Any


class LLMPlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql_json: Dict[str, Any]
    selected_columns: List[LLMSelectedColumn] = Field(default_factory=list)
    filters: List[LLMFilter] = Field(default_factory=list)
    join_plan: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    notes: List[str] = Field(default_factory=list)


@dataclass
class SlotDrivenIntent:
    metric_terms: List[str] = field(default_factory=list)
    dimension_terms: List[str] = field(default_factory=list)
    subgroup_terms: List[str] = field(default_factory=list)
    time_terms: List[str] = field(default_factory=list)
    org_school_terms: List[str] = field(default_factory=list)
    org_district_terms: List[str] = field(default_factory=list)
    normalized_time: List[CanonicalTime] = field(default_factory=list)

    def implies_count_metric(self, prompt: str) -> bool:
        text = str(prompt or "").strip().lower()
        explicit_count_patterns = (
            r"\bhow many\b",
            r"\bcount\b",
            r"\bnumber of\b",
            r"\btotal\b",
            r"\bdistinct\b",
            r"\bunique\b",
        )
        has_explicit_count_intent = any(re.search(pattern, text) is not None for pattern in explicit_count_patterns)
        # Row-listing prompts should not be forced into aggregation.
        is_row_listing_prompt = (
            re.search(r"\b(show|list|give|display|return)\b", text) is not None
            and re.search(r"\ball\b", text) is not None
            and re.search(r"\bby\b", text) is None
            and not has_explicit_count_intent
        )
        if is_row_listing_prompt:
            return False

        metric_blob = " ".join(self.metric_terms).lower()
        return (
            has_explicit_count_intent
            or "enrollment" in metric_blob
            or "student enrollment" in metric_blob
        )

    def allows_identifier_projection(self, prompt: str) -> bool:
        text = str(prompt or "").strip().lower()
        if re.search(r"\blist\b", text) is None:
            return False
        return re.search(r"\b(ids?|identifiers?|k_student|student id|student ids)\b", text) is not None


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
        llm_client: Optional[LLMClient] = None,
        tier2_runner: Optional[Any] = None,
        semantic_extractor: Optional[SemanticExtractService] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._deterministic = deterministic or DeterministicMatcher()
        self._concept_retrieval = concept_retrieval or ConceptRetrievalService()
        self._concept_to_column = concept_to_column or ConceptToColumnService(sql=self._sql)
        self._column_vector = column_vector or ConstrainedColumnVectorService(sql=self._sql)
        self._domain_selector = domain_selector or DomainSelectionService(sql=self._sql)
        self._value_alias_resolver = value_alias_resolver or ValueAliasResolutionService(sql=self._sql)
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
        self._tier2_runner = tier2_runner or run_tier2_with_meta
        self._semantic_extractor = semantic_extractor or SemanticExtractService()

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
            "normalized_text": prompt,
            "slots": {},
            "ents": [],
            "model": {},
            "warnings": [],
        }
        try:
            semantic_extract_payload = self._semantic_extractor.extract(prompt)
            normalized = str((semantic_extract_payload.get("normalized_text") or "")).strip()
            if normalized:
                prompt = normalized
                semantic_extract_payload["normalized_text"] = prompt
        except Exception:
            warnings.append("semantic_extract_failed")
            semantic_extract_payload = {
                "normalized_text": prompt,
                "slots": {},
                "ents": [],
                "model": {},
                "warnings": ["semantic_extract_failed"],
            }
        timings_ms["semantic_extract"] = _elapsed_ms(t_extract)
        warnings.extend([str(w) for w in semantic_extract_payload.get("warnings", []) if str(w).strip()])
        t_slot_intent = time.perf_counter()
        slot_intent = self._build_slot_driven_intent(
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
            except Exception:
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
            warnings.extend(
                str(item) for item in list(tier2_plan_ir.get("warnings") or []) if str(item).strip()
            )
        tier2_entity = _norm_entity(_dict_get(tier2_plan_ir, "entities", "subject_entity"))
        if tier2_entity:
            intent_entity = tier2_entity
        tier2_extracted_values = self._extract_values_from_tier2_plan_ir(tier2_plan_ir)
        if tier2_extracted_values:
            deterministic_extracted_values = self._merge_extracted_values(
                deterministic_extracted_values,
                tier2_extracted_values,
            )
            if isinstance(deterministic, dict):
                deterministic["extracted_values"] = deterministic_extracted_values

        t0b = time.perf_counter()
        lexical_hits = self._lexical_alias_concept_hits(prompt=prompt, vertical_norm=vertical_norm)
        lexical_keys = [str(hit.get("concept_key") or "").strip().upper() for hit in lexical_hits if hit.get("concept_key")]
        timings_ms["lexical_alias"] = _elapsed_ms(t0b)

        t1 = time.perf_counter()
        slot_scoped = self._search_slot_scoped_concepts(
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
        concept_vector["hits"] = self._merge_concept_hits(
            vector_hits=concept_vector.get("hits", [])[:max_concepts],
            lexical_hits=lexical_hits,
            max_concepts=max_concepts,
            has_org_district_signal=bool(slot_intent.org_district_terms),
        )
        concept_keys = [str(hit.get("concept_key") or "").upper() for hit in concept_vector.get("hits", [])]
        concept_info = self._load_concept_details(vertical_norm=vertical_norm, concept_keys=concept_keys)
        concept_vector["hits"] = self._apply_intent_entity_to_concept_hits(
            hits=concept_vector.get("hits", []),
            concept_info=concept_info,
            intent_entity=intent_entity,
            max_concepts=max_concepts,
            always_include_keys=lexical_keys,
        )
        concept_vector["hits"] = self._apply_tier2_concept_boosts(
            hits=concept_vector.get("hits", []),
            plan_ir=tier2_plan_ir,
            max_concepts=max_concepts,
            always_include_keys=lexical_keys,
        )
        original_hit_count = len(concept_vector.get("hits", []))
        concept_vector["hits"] = self._rebalance_identifier_heavy_hits(
            prompt=prompt,
            hits=concept_vector.get("hits", []),
            concept_info=concept_info,
            max_concepts=max_concepts,
            always_include_keys=lexical_keys,
            has_subgroup_intent=bool(slot_intent.subgroup_terms),
        )
        concept_vector["hits"] = self._inject_time_concept_hits(
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
        resolved_constraints = self._resolve_prompt_value_constraints(
            prompt=prompt,
            vertical_norm=vertical_norm,
            concept_hits=concept_vector.get("hits", []),
        )
        concept_vector["hits"] = self._apply_constraint_overrides_to_concept_hits(
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
            selected_domain_id = _to_int(domain_selection.get("domain_id")) if domain_selection.get("domain_id") is not None else selected_domain_id
        timings_ms["domain_selection"] = _elapsed_ms(t2b)

        role_guardrails = self._build_role_column_guardrails(
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
                row
                for row in raw_column_hits
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
            concepts_for_llm.append(
                {
                    "concept_key": key,
                    "semantic_type": info.get("semantic_type"),
                    "sub_type": info.get("sub_type"),
                    "entity": info.get("entity"),
                    "description": _trim(str(info.get("description") or ""), 180),
                    "score": hit.get("score"),
                    "source": hit.get("source"),
                }
            )

        by_mid: Dict[int, Dict[str, Any]] = {}
        for row in list(column_hits) + list(mapped_columns):
            try:
                mid = int(row.get("model_column_id"))
            except Exception:
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
        skeleton = self._build_plan_skeleton(
            prompt=prompt,
            domain_id=domain_id,
            slot_intent=slot_intent,
            role_guardrails=role_guardrails,
            candidate_columns=columns_for_llm,
        )
        forced_filters = self._build_forced_filters(
            resolved_constraints=resolved_constraints,
            prompt=prompt,
        )
        name_forced_filters = self._build_name_forced_filters(
            prompt=prompt,
            intent_entity=intent_entity,
            extracted_values=extracted_values,
            mapped_columns=columns_for_llm,
        )
        school_forced_filters = self._build_school_forced_filters(
            extracted_values=extracted_values,
            mapped_columns=columns_for_llm,
        )
        forced_filters = self._merge_forced_filters(
            existing_filters=forced_filters,
            forced_filters=name_forced_filters,
            prompt=prompt,
        )
        forced_filters = self._merge_forced_filters(
            existing_filters=forced_filters,
            forced_filters=school_forced_filters,
            prompt=prompt,
        )
        tier2_forced_filters = self._build_tier2_forced_filters(
            plan_ir=tier2_plan_ir if isinstance(tier2_plan_ir, dict) else {},
            mapped_columns=columns_for_llm,
        )
        forced_filters = self._merge_forced_filters(
            existing_filters=forced_filters,
            forced_filters=tier2_forced_filters,
            prompt=prompt,
        )
        semantic_forced_filters = self._build_semantic_extract_forced_filters(
            semantic_extract=semantic_extract_payload if isinstance(semantic_extract_payload, dict) else {},
            mapped_columns=columns_for_llm,
            vertical_norm=vertical_norm,
        )
        forced_filters = self._merge_forced_filters(
            existing_filters=forced_filters,
            forced_filters=semantic_forced_filters,
            prompt=prompt,
        )
        forced_filters = self._merge_forced_filters(
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
        payload = self._normalize_llm_payload(payload, candidate_columns=columns_for_llm)
        payload["filters"] = self._merge_forced_filters(
            existing_filters=payload.get("filters"),
            forced_filters=forced_filters,
            prompt=prompt,
        )
        payload["selected_columns"] = self._minimize_selected_columns(
            selected_columns=payload.get("selected_columns"),
            prompt=prompt,
            explicit_concept_keys=explicit_concept_keys,
            forced_filters=forced_filters,
        )
        payload = self._apply_skeleton_constraints(
            payload=payload,
            skeleton=skeleton,
            slot_intent=slot_intent,
            prompt=prompt,
        )

        try:
            parsed = LLMPlanPayload.model_validate(payload)
        except ValidationError as exc:
            raise ForgeError(
                "Invalid LLM planning response",
                status_code=502,
                details={"errors": exc.errors(), "payload": payload},
            ) from exc

        grounded = self._ground_plan(
            parsed,
            columns_for_llm,
            concepts_for_llm,
            prompt=prompt,
            domain_id=domain_id,
        )
        grounded = self._apply_value_aliases_to_llm_plan(vertical_norm=vertical_norm, llm_plan=grounded)
        grounded, grounded_filter_warnings = self._enforce_grounded_org_filters(
            llm_plan=grounded,
            prompt=prompt,
            domain_id=domain_id,
            mapped_columns=columns_for_llm,
            semantic_extract=semantic_extract_payload if isinstance(semantic_extract_payload, dict) else {},
        )
        grounded, gate_warnings = self._apply_plan_validity_gate(
            llm_plan=grounded,
            prompt=prompt,
            intent_entity=intent_entity,
            extracted_values=extracted_values,
            mapped_columns=columns_for_llm,
            domain_id=domain_id,
        )
        if slot_intent.implies_count_metric(prompt):
            grounded = self._enforce_count_commercial_rule(
                llm_plan=grounded,
                role_guardrails=role_guardrails,
            )
        try:
            self._validate_sql_json(
                sql_json=grounded.get("sql_json"),
                allowed_model_column_ids=allowed_model_column_ids,
            )
        except ForgeError:
            fallback = self._fallback_skeleton_plan(
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

    def _build_slot_driven_intent(
        self,
        *,
        prompt: str,
        vertical_norm: str,
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
        time_normalized = normalize_time_terms(time_terms, vertical=vertical_norm)
        if not time_normalized and str(vertical_norm or "").lower() == "education":
            if re.search(r"\b(this school year|current school year)\b", str(prompt or "").lower()):
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

    def _search_slot_scoped_concepts(
        self,
        *,
        prompt: str,
        slot_intent: SlotDrivenIntent,
        vertical_norm: str,
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
            metric_hits = self._search_concepts_for_query(
                query=metric_query,
                vertical_norm=vertical_norm,
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
                dimension_hits = self._search_concepts_for_query(
                    query=dimension_query,
                    vertical_norm=vertical_norm,
                    max_concepts=min(20, max_concepts),
                    deterministic_matches=deterministic_matches,
                )
                timings["dimension"] = _elapsed_ms(t_dimension)
        if slot_intent.subgroup_terms:
            subgroup_query = " ".join(slot_intent.subgroup_terms)
            queries["subgroup"] = subgroup_query
            t_subgroup = time.perf_counter()
            subgroup_hits = self._search_concepts_for_query(
                query=subgroup_query,
                vertical_norm=vertical_norm,
                max_concepts=min(20, max_concepts),
                deterministic_matches=deterministic_matches,
            )
            timings["subgroup"] = _elapsed_ms(t_subgroup)

        has_slot_queries = bool(queries)
        if not has_slot_queries:
            queries["fallback"] = prompt
            t_fallback = time.perf_counter()
            fallback_hits = self._search_concepts_for_query(
                query=prompt,
                vertical_norm=vertical_norm,
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
        concept_info = self._load_concept_details(vertical_norm=vertical_norm, concept_keys=all_keys)
        metric_filtered = self._filter_hits_for_role(
            hits=metric_hits,
            concept_info=concept_info,
            allowed_semantic_types={"metric", "measure"},
            role="metric",
        )
        dimension_filtered = self._filter_hits_for_role(
            hits=dimension_hits,
            concept_info=concept_info,
            allowed_semantic_types={"dimension", "attribute", "group_by", "geography"},
            role="dimension",
        )
        subgroup_filtered = self._filter_hits_for_role(
            hits=subgroup_hits,
            concept_info=concept_info,
            allowed_semantic_types={"subgroup", "population", "flag", "descriptor", "attribute"},
            role="subgroup",
        )
        subgroup_filtered = self._ensure_subgroup_race_hits(
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

    def _search_concepts_for_query(
        self,
        *,
        query: str,
        vertical_norm: str,
        max_concepts: int,
        deterministic_matches: Optional[Sequence[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        out = self._concept_retrieval.search(
            prompt=query,
            vertical_norm=vertical_norm,
            max_concepts=max_concepts,
            deterministic_matches=deterministic_matches,
        )
        return [dict(row) for row in list(out.get("hits") or []) if isinstance(row, dict)]

    def _filter_hits_for_role(
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
            is_identifier = self._is_identifier_like_concept(concept_key=key, concept_info=info)
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
    def _ensure_subgroup_race_hits(
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
    def _inject_time_concept_hits(
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

    def _build_role_column_guardrails(
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
            subgroups = self._merge_ranked_rows(primary=subgroups, secondary=subgroup_seed_rows, limit=20)
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
                if not self._is_identifier_like_concept(
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
                if not self._is_identifier_like_concept(
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
            domain_hint=self._infer_domain_hint_from_rows(rows),
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

    @staticmethod
    def _select_preferred_time_column(
        *,
        domain_hint: str,
        mapped_columns_for_time_concept: Sequence[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        preference_map: Dict[str, Dict[str, Any]] = {
            "enrollment": {
                "preferred_time_concept_key": "SCHOOL_YEAR",
                "preferred_column_names": ["school_year", "school_year_id", "school_year_key"],
            },
            "generic": {
                "preferred_time_concept_key": "SCHOOL_YEAR",
                "preferred_column_names": ["school_year", "year"],
            },
        }
        rule = preference_map.get(str(domain_hint or "generic").lower(), preference_map["generic"])
        concept_key = str(rule.get("preferred_time_concept_key") or "SCHOOL_YEAR").upper()
        preferred_names = [str(name).lower() for name in list(rule.get("preferred_column_names") or [])]
        rows = [dict(row) for row in mapped_columns_for_time_concept if isinstance(row, dict)]
        if not rows:
            return None
        rows.sort(
            key=lambda row: (
                0 if str(row.get("concept_key") or "").strip().upper() == concept_key else 1,
                0 if str(row.get("column_name") or "").strip().lower() in preferred_names else 1,
                -(_to_float(row.get("effective_weight")) or _to_float(row.get("final_score")) or 0.0),
                _to_int(row.get("model_column_id")) or 0,
            )
        )
        return rows[0]

    def _build_plan_skeleton(
        self,
        *,
        prompt: str,
        domain_id: Optional[int],
        slot_intent: SlotDrivenIntent,
        role_guardrails: Dict[str, Any],
        candidate_columns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        dimensions = [dict(row) for row in list(role_guardrails.get("dimension_columns") or []) if isinstance(row, dict)]
        subgroups = [dict(row) for row in list(role_guardrails.get("subgroup_columns") or []) if isinstance(row, dict)]
        metrics = [dict(row) for row in list(role_guardrails.get("metric_columns") or []) if isinstance(row, dict)]
        time_columns = [dict(row) for row in list(role_guardrails.get("time_columns") or []) if isinstance(row, dict)]

        selected_columns: List[Dict[str, Any]] = []
        filters: List[Dict[str, Any]] = []
        notes: List[str] = []
        seen_mid: set[int] = set()
        for row in dimensions:
            mid = _to_int(row.get("model_column_id"))
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if mid is None or concept_key == "" or mid in seen_mid:
                continue
            seen_mid.add(mid)
            selected_columns.append({"concept_key": concept_key, "model_column_id": mid})
        for row in subgroups[:1]:
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if concept_key:
                if concept_key in {"RACE", "ETHNICITY", "RACE_ETHNICITY"}:
                    continue
                column_name = str(row.get("column_name") or "").strip().lower()
                subgroup_value: Any = True if concept_key.startswith("IS_") or column_name.startswith("is_") else "EL"
                filters.append({"concept_key": concept_key, "op": "=", "value": subgroup_value})

        if time_columns and slot_intent.normalized_time:
            time_row = time_columns[0]
            concept_key = str(time_row.get("concept_key") or "").strip().upper()
            time_value = slot_intent.normalized_time[0].key
            if concept_key and time_value:
                filters.append({"concept_key": concept_key, "op": "=", "value": time_value})

        if slot_intent.implies_count_metric(prompt):
            metric_row = metrics[0] if metrics else (candidate_columns[0] if candidate_columns else None)
            if isinstance(metric_row, dict):
                metric_key = str(metric_row.get("concept_key") or "").strip().upper()
                metric_mid = _to_int(metric_row.get("model_column_id"))
                if metric_mid is not None and metric_key and metric_mid not in seen_mid:
                    seen_mid.add(metric_mid)
                    selected_columns.append({"concept_key": metric_key, "model_column_id": metric_mid})
                    notes.append("skeleton_enforced_count")

        sql_json, _ = self._build_grounded_sql_json(
            prompt=prompt,
            domain_id=domain_id,
            selected_columns=selected_columns,
            filters=filters,
            candidate_by_mid=_candidate_by_mid(candidate_columns),
            candidate_by_concept=_candidate_by_concept(candidate_columns),
            llm_sql_json={},
        )
        if slot_intent.implies_count_metric(prompt):
            sql_json = self._inject_count_aggregation(
                sql_json=sql_json,
                metric_columns=list(role_guardrails.get("metric_columns") or []),
                dimension_columns=dimensions,
            )

        return {
            "sql_json": sql_json,
            "selected_columns": selected_columns,
            "filters": filters,
            "notes": notes,
        }

    @staticmethod
    def _inject_count_aggregation(
        *,
        sql_json: Dict[str, Any],
        metric_columns: Sequence[Dict[str, Any]],
        dimension_columns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        out = dict(sql_json or {})
        aggs = out.get("aggs")
        if not isinstance(aggs, dict):
            aggs = {"enabled": True, "groupBy": [], "metrics": []}
            out["aggs"] = aggs
        aggs["enabled"] = True
        if not isinstance(aggs.get("groupBy"), list):
            aggs["groupBy"] = []
        if not isinstance(aggs.get("metrics"), list):
            aggs["metrics"] = []

        group_seen = {
            (_to_int(item.get("modelColumnId")), str(item.get("columnName") or "").lower())
            for item in aggs.get("groupBy", [])
            if isinstance(item, dict)
        }
        for row in dimension_columns:
            field = {
                "modelColumnId": _to_int(row.get("model_column_id")),
                "workspaceTableId": _to_int(row.get("workspace_table_id")),
                "columnName": row.get("column_name"),
                "exprId": None,
                "alias": None,
            }
            signature = (_to_int(field.get("modelColumnId")), str(field.get("columnName") or "").lower())
            if signature not in group_seen and field["modelColumnId"] is not None and field["columnName"]:
                aggs["groupBy"].append(field)
                group_seen.add(signature)

        if not aggs["metrics"]:
            metric_row = metric_columns[0] if metric_columns else None
            metric_field = None
            fn = "count"
            if isinstance(metric_row, dict):
                candidate_field = {
                    "modelColumnId": _to_int(metric_row.get("model_column_id")),
                    "workspaceTableId": _to_int(metric_row.get("workspace_table_id")),
                    "columnName": metric_row.get("column_name"),
                    "exprId": None,
                    "alias": None,
                }
                if (
                    isinstance(candidate_field.get("columnName"), str)
                    and str(candidate_field.get("columnName") or "").strip()
                ):
                    metric_field = candidate_field
                if "student" in str(metric_row.get("concept_key") or "").lower():
                    fn = "count_distinct"
            aggs["metrics"].append(
                {
                    "id": "semantic_plan_metric_count",
                    "fn": fn,
                    "field": metric_field,
                    "label": "count",
                }
            )
        return out

    def _apply_skeleton_constraints(
        self,
        *,
        payload: Dict[str, Any],
        skeleton: Dict[str, Any],
        slot_intent: SlotDrivenIntent,
        prompt: str,
    ) -> Dict[str, Any]:
        out = dict(payload or {})
        if slot_intent.implies_count_metric(prompt):
            if not isinstance(out.get("sql_json"), dict):
                out["sql_json"] = dict(skeleton.get("sql_json") or {})
            else:
                sql_json = dict(out.get("sql_json") or {})
                if not isinstance(sql_json.get("aggs"), dict) or not list((sql_json.get("aggs") or {}).get("metrics") or []):
                    sql_json["aggs"] = (skeleton.get("sql_json") or {}).get("aggs")
                out["sql_json"] = sql_json
                skeleton_selected = [dict(item) for item in list(skeleton.get("selected_columns") or []) if isinstance(item, dict)]
                selected = [dict(item) for item in list(out.get("selected_columns") or []) if isinstance(item, dict)]
                seen = {(_to_int(item.get("model_column_id")), str(item.get("concept_key") or "").upper()) for item in selected}
                for item in skeleton_selected:
                    key = (_to_int(item.get("model_column_id")), str(item.get("concept_key") or "").upper())
                    if key in seen:
                        continue
                    selected.append(item)
                    seen.add(key)
                out["selected_columns"] = selected
        return out

    def _enforce_count_commercial_rule(
        self,
        *,
        llm_plan: Dict[str, Any],
        role_guardrails: Dict[str, Any],
    ) -> Dict[str, Any]:
        out = dict(llm_plan or {})
        sql_json = dict(out.get("sql_json") or {})
        sql_json = self._inject_count_aggregation(
            sql_json=sql_json,
            metric_columns=list(role_guardrails.get("metric_columns") or []),
            dimension_columns=list(role_guardrails.get("dimension_columns") or []),
        )
        out["sql_json"] = sql_json
        return out

    def _fallback_skeleton_plan(
        self,
        *,
        prompt: str,
        domain_id: Optional[int],
        skeleton: Dict[str, Any],
        candidate_columns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        selected_columns = [dict(item) for item in list(skeleton.get("selected_columns") or []) if isinstance(item, dict)]
        filters = [dict(item) for item in list(skeleton.get("filters") or []) if isinstance(item, dict)]
        sql_json, _ = self._build_grounded_sql_json(
            prompt=prompt,
            domain_id=domain_id,
            selected_columns=selected_columns,
            filters=filters,
            candidate_by_mid=_candidate_by_mid(candidate_columns),
            candidate_by_concept=_candidate_by_concept(candidate_columns),
            llm_sql_json=dict((skeleton or {}).get("sql_json") or {}),
        )
        if isinstance((skeleton or {}).get("sql_json"), dict) and isinstance(((skeleton or {}).get("sql_json") or {}).get("aggs"), dict):
            sql_json["aggs"] = ((skeleton or {}).get("sql_json") or {}).get("aggs")
        return {
            "sql_json": sql_json,
            "selected_columns": selected_columns,
            "filters": filters,
            "join_plan": {},
            "confidence": 0.45,
            "notes": list((skeleton or {}).get("notes") or []),
        }

    def _validate_sql_json(self, *, sql_json: Any, allowed_model_column_ids: set[int]) -> None:
        if not allowed_model_column_ids:
            return
        if not isinstance(sql_json, dict):
            return
        illegal = self._collect_illegal_model_column_ids(sql_json=sql_json, allowed_model_column_ids=allowed_model_column_ids)
        if illegal:
            raise ForgeError(
                "Planner used disallowed columns",
                status_code=502,
                details={"illegal_model_column_ids": sorted(illegal)},
            )

    @staticmethod
    def _collect_illegal_model_column_ids(*, sql_json: Dict[str, Any], allowed_model_column_ids: set[int]) -> set[int]:
        seen: set[int] = set()

        def _check_field(field: Any) -> None:
            if not isinstance(field, dict):
                return
            mid = _to_int(field.get("modelColumnId"))
            if mid is not None and mid not in allowed_model_column_ids:
                seen.add(mid)

        for column in list(sql_json.get("columns") or []):
            if isinstance(column, dict):
                _check_field(column.get("field"))
        for sort in list(sql_json.get("sorting") or []):
            if isinstance(sort, dict):
                _check_field(sort.get("col"))

        def _walk_filter(node: Any) -> None:
            if not isinstance(node, dict):
                return
            node_type = str(node.get("type") or "").strip().lower()
            if node_type == "condition":
                _check_field(node.get("field"))
                return
            if node_type == "group":
                for child in list(node.get("children") or []):
                    _walk_filter(child)

        _walk_filter(sql_json.get("filters"))

        aggs = sql_json.get("aggs")
        if isinstance(aggs, dict):
            for group in list(aggs.get("groupBy") or []):
                _check_field(group)
            for metric in list(aggs.get("metrics") or []):
                if isinstance(metric, dict):
                    _check_field(metric.get("field"))
        return seen

    @staticmethod
    def _normalize_llm_payload(
        payload: Dict[str, Any],
        *,
        candidate_columns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}

        normalized: Dict[str, Any] = dict(payload)
        normalized.setdefault("sql_json", {})

        concept_by_model_column_id: Dict[int, str] = {}
        concept_by_table_column: Dict[Tuple[str, str], str] = {}
        concept_by_column_name: Dict[str, Optional[str]] = {}
        for row in candidate_columns:
            mid = _to_int(row.get("model_column_id"))
            concept_key = str(row.get("concept_key") or "").strip().upper()
            table_name = str(row.get("table_name") or "").strip().lower()
            column_name = str(row.get("column_name") or "").strip().lower()
            if mid is not None and concept_key:
                concept_by_model_column_id[mid] = concept_key
            if table_name and column_name and concept_key:
                concept_by_table_column[(table_name, column_name)] = concept_key
            if column_name and concept_key:
                if column_name in concept_by_column_name and concept_by_column_name[column_name] != concept_key:
                    concept_by_column_name[column_name] = None
                elif column_name not in concept_by_column_name:
                    concept_by_column_name[column_name] = concept_key

        selected_columns: List[Dict[str, Any]] = []
        raw_selected = normalized.get("selected_columns")
        if isinstance(raw_selected, list):
            for item in raw_selected:
                if isinstance(item, (int, float, str)):
                    mid = _to_int(item)
                    if mid is None:
                        continue
                    concept_key = concept_by_model_column_id.get(mid)
                    if not concept_key:
                        continue
                    selected_columns.append({"concept_key": concept_key, "model_column_id": mid})
                    continue
                if isinstance(item, dict):
                    mid = _to_int(item.get("model_column_id"))
                    if mid is None:
                        mid = _to_int(item.get("modelColumnId"))
                    if mid is None:
                        continue
                    concept_key = str(item.get("concept_key") or item.get("conceptKey") or "").strip().upper()
                    if concept_key == "":
                        concept_key = concept_by_model_column_id.get(mid, "")
                    if concept_key == "":
                        continue
                    selected_columns.append({"concept_key": concept_key, "model_column_id": mid})
        normalized["selected_columns"] = selected_columns

        filters: List[Dict[str, Any]] = []
        raw_filters = normalized.get("filters")
        if isinstance(raw_filters, list):
            for item in raw_filters:
                if not isinstance(item, dict):
                    continue
                mid = _to_int(item.get("model_column_id"))
                if mid is None:
                    mid = _to_int(item.get("modelColumnId"))
                concept_key = str(item.get("concept_key") or item.get("conceptKey") or "").strip().upper()
                if concept_key == "" and mid is not None:
                    concept_key = concept_by_model_column_id.get(mid, "")
                if concept_key == "":
                    column_expr = str(item.get("column") or "").strip().lower()
                    if column_expr:
                        parts = [p for p in column_expr.split(".") if p]
                        if len(parts) >= 2:
                            concept_key = concept_by_table_column.get((parts[-2], parts[-1]), "")
                        if concept_key == "" and parts:
                            concept_key = concept_by_column_name.get(parts[-1]) or ""
                op = str(item.get("op") or item.get("operator") or "").strip()
                if concept_key == "" or op == "":
                    continue
                filters.append(
                    {
                        "concept_key": concept_key,
                        "op": op,
                        "value": item.get("value"),
                    }
                )
        normalized["filters"] = filters

        raw_join_plan = normalized.get("join_plan")
        if isinstance(raw_join_plan, list):
            normalized["join_plan"] = {"joins": raw_join_plan}
        elif isinstance(raw_join_plan, dict):
            normalized["join_plan"] = raw_join_plan
        else:
            normalized["join_plan"] = {}

        raw_notes = normalized.get("notes")
        if isinstance(raw_notes, str):
            notes = [raw_notes.strip()] if raw_notes.strip() else []
        elif isinstance(raw_notes, list):
            notes = [str(n).strip() for n in raw_notes if str(n).strip()]
        else:
            notes = []
        normalized["notes"] = notes

        confidence = _to_float(normalized.get("confidence"))
        if confidence is None:
            confidence = 0.5
        normalized["confidence"] = max(0.0, min(1.0, confidence))
        return normalized

    @staticmethod
    def _ground_plan(
        plan: LLMPlanPayload,
        candidate_columns: Sequence[Dict[str, Any]],
        concepts: Sequence[Dict[str, Any]],
        *,
        prompt: str,
        domain_id: Optional[int],
    ) -> Dict[str, Any]:
        valid_mids = {int(col.get("model_column_id")) for col in candidate_columns if col.get("model_column_id") is not None}
        candidate_by_mid: Dict[int, Dict[str, Any]] = {}
        candidate_by_concept: Dict[str, List[Dict[str, Any]]] = {}
        for row in candidate_columns:
            mid = _to_int(row.get("model_column_id"))
            if mid is None:
                continue
            candidate_by_mid[mid] = dict(row)
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if concept_key:
                candidate_by_concept.setdefault(concept_key, []).append(dict(row))
        mapped_concepts = set(candidate_by_concept.keys())

        selected_seen: set[int] = set()
        selected_columns: List[Dict[str, Any]] = []
        for item in plan.selected_columns:
            mid = int(item.model_column_id)
            if mid not in valid_mids or mid in selected_seen:
                continue
            selected_seen.add(mid)
            concept_key = str((candidate_by_mid.get(mid) or {}).get("concept_key") or item.concept_key).upper()
            selected_columns.append(
                {
                    "concept_key": concept_key,
                    "model_column_id": mid,
                }
            )
        filters = [
            item.model_dump(mode="json")
            for item in plan.filters
            if str(item.concept_key or "").upper() in mapped_concepts
        ]

        grounded_sql_json, sql_json_dropped = PlanService._build_grounded_sql_json(
            prompt=prompt,
            domain_id=domain_id,
            selected_columns=selected_columns,
            filters=filters,
            candidate_by_mid=candidate_by_mid,
            candidate_by_concept=candidate_by_concept,
            llm_sql_json=plan.sql_json,
        )

        removed = (len(plan.selected_columns) - len(selected_columns)) + (len(plan.filters) - len(filters)) + sql_json_dropped
        confidence = float(plan.confidence)
        notes = list(plan.notes)
        if removed > 0:
            confidence = max(0.0, confidence - min(0.2, removed * 0.03))
            notes.append(f"grounding_removed={removed}")

        return {
            "sql_json": grounded_sql_json,
            "selected_columns": selected_columns,
            "filters": filters,
            "join_plan": plan.join_plan,
            "confidence": round(confidence, 4),
            "notes": notes,
        }

    @staticmethod
    def _build_grounded_sql_json(
        *,
        prompt: str,
        domain_id: Optional[int],
        selected_columns: Sequence[Dict[str, Any]],
        filters: Sequence[Dict[str, Any]],
        candidate_by_mid: Dict[int, Dict[str, Any]],
        candidate_by_concept: Dict[str, List[Dict[str, Any]]],
        llm_sql_json: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], int]:
        dropped = 0
        edits: List[Any] = []
        filter_conditions: List[Dict[str, Any]] = []
        if domain_id is not None:
            try:
                edits.append(SetDomainEdit(op="setDomain", domainId=int(domain_id)))
            except Exception:
                dropped += 1

        table_hint = PlanService._extract_from_table_hint(llm_sql_json)
        selected_rows_by_concept: Dict[str, List[Dict[str, Any]]] = {}

        for item in selected_columns:
            mid = _to_int(item.get("model_column_id"))
            if mid is None:
                dropped += 1
                continue
            row = candidate_by_mid.get(mid)
            if not isinstance(row, dict):
                dropped += 1
                continue
            concept_key = str(item.get("concept_key") or row.get("concept_key") or "").strip().upper()
            if concept_key:
                selected_rows_by_concept.setdefault(concept_key, []).append(row)
            column_name = str(row.get("column_name") or "").strip()
            if column_name == "":
                dropped += 1
                continue
            try:
                edits.append(
                    AddSelectEdit(
                        op="addSelect",
                        col=SqlColumnKey(
                            modelColumnId=mid,
                            columnName=column_name,
                            workspaceTableId=_to_int(row.get("workspace_table_id")),
                            exprId=None,
                            alias=None,
                        ),
                        alias=None,
                    )
                )
            except Exception:
                dropped += 1

        for item in filters:
            concept_key = str(item.get("concept_key") or "").strip().upper()
            op = PlanService._normalize_filter_operator(str(item.get("op") or ""))
            if concept_key == "" or op is None:
                dropped += 1
                continue

            row = PlanService._resolve_filter_column(
                concept_key=concept_key,
                selected_rows_by_concept=selected_rows_by_concept,
                candidate_by_concept=candidate_by_concept,
                table_hint=table_hint,
            )
            if not isinstance(row, dict):
                dropped += 1
                continue
            mid = _to_int(row.get("model_column_id"))
            column_name = str(row.get("column_name") or "").strip()
            if mid is None or column_name == "":
                dropped += 1
                continue
            filter_conditions.append(
                {
                    "type": "condition",
                    "id": f"semantic_plan_filter_{len(filter_conditions) + 1}",
                    "field": {
                        "modelColumnId": mid,
                        "columnName": column_name,
                        "workspaceTableId": _to_int(row.get("workspace_table_id")),
                        "exprId": None,
                        "alias": None,
                    },
                    "op": op,
                    "value": item.get("value"),
                }
            )

        sql_json = apply_edits(None, edits, prompt=prompt)
        if filter_conditions:
            sql_json["filters"] = {
                "type": "group",
                "id": "semantic_plan_filters",
                "match": "and",
                "children": filter_conditions,
            }
        meta = sql_json.get("meta")
        if isinstance(meta, dict):
            meta["tool"] = "semantic_plan"
            if table_hint:
                meta["fromTableHint"] = table_hint
        return sql_json, dropped

    @staticmethod
    def _extract_from_table_hint(sql_json: Dict[str, Any]) -> Optional[str]:
        if not isinstance(sql_json, dict):
            return None
        raw_from = sql_json.get("from")
        if isinstance(raw_from, dict):
            raw_from = raw_from.get("value")
        if not isinstance(raw_from, str):
            return None
        text = raw_from.strip()
        if text == "":
            return None
        text = text.split()[-1]
        if "." in text:
            text = text.split(".")[-1]
        return text.strip().lower() or None

    @staticmethod
    def _resolve_filter_column(
        *,
        concept_key: str,
        selected_rows_by_concept: Dict[str, List[Dict[str, Any]]],
        candidate_by_concept: Dict[str, List[Dict[str, Any]]],
        table_hint: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        selected_rows = [dict(row, __selected__=True) for row in list(selected_rows_by_concept.get(concept_key) or [])]
        candidate_rows = [dict(row, __selected__=False) for row in list(candidate_by_concept.get(concept_key) or [])]
        all_rows = selected_rows + candidate_rows

        if table_hint:
            for row in all_rows:
                if str(row.get("table_name") or "").strip().lower() == table_hint:
                    return row

        if not all_rows:
            return None

        all_rows.sort(
            key=lambda row: PlanService._filter_column_rank(
                concept_key=concept_key,
                row=row,
            )
        )
        return all_rows[0]

    @staticmethod
    def _filter_column_rank(*, concept_key: str, row: Dict[str, Any]) -> Tuple[int, int, float, int]:
        table_name = str(row.get("table_name") or "").strip().lower()
        column_name = str(row.get("column_name") or "").strip().lower()
        is_selected = 0 if bool(row.get("__selected__")) else 1

        if concept_key in {"SCHOOL_NAME", "STUDENT_SCHOOL_NAME"}:
            if table_name == "dim_school" and column_name == "school_name":
                preference = 0
            elif table_name.startswith("fct_student_") and "school_name" in column_name:
                preference = 1
            elif "school_name" in column_name:
                preference = 2
            else:
                preference = 3
        else:
            preference = 5

        score = -(_to_float(row.get("effective_weight")) or _to_float(row.get("final_score")) or 0.0)
        model_column_id = _to_int(row.get("model_column_id")) or 0
        return preference, is_selected, score, model_column_id

    @staticmethod
    def _normalize_filter_operator(op: str) -> Optional[str]:
        value = str(op or "").strip().lower()
        mapping = {
            "=": "equals",
            "==": "equals",
            "eq": "equals",
            "equals": "equals",
            "contains": "contains",
            "like": "contains",
            "starts_with": "starts_with",
            "startswith": "starts_with",
            "prefix": "starts_with",
            "in": "in",
            "between": "between",
            "gt": "gt",
            ">": "gt",
            "lt": "lt",
            "<": "lt",
            "!=": "not_equals",
            "<>": "not_equals",
            "ne": "not_equals",
            "not_equal": "not_equals",
            "not_equals": "not_equals",
        }
        return mapping.get(value)

    def _load_concept_details(self, *, vertical_norm: str, concept_keys: Sequence[str]) -> Dict[str, Dict[str, Any]]:
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
              AND vertical_norm IN (:vertical_norm, 'generic')
              AND `status` = 'active'
            ORDER BY CASE WHEN vertical_norm = :vertical_norm THEN 0 ELSE 1 END
            """,
            {
                **in_params,
                "vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic",
            },
        )
        out: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            key = str(row.get("concept_key") or "").upper()
            if key and key not in out:
                out[key] = dict(row)
        return out

    def _apply_intent_entity_to_concept_hits(
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
            )
            score = _to_float(row.get("score")) or 0.0
            row["score"] = round(score * factor, 4)
            row["entity_factor"] = factor
            rows.append(row)

        rows.sort(key=lambda item: -(_to_float(item.get("score")) or 0.0))
        return self._ensure_keys_in_hits(hits=rows, required_keys=required, max_concepts=max_concepts)

    def _apply_tier2_concept_boosts(
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
                )
                if subject_entity == "student" and concept_key.startswith(("STAFF_", "PARENT_")) and "NAME" in concept_key:
                    factor *= 0.55
                if subject_entity in {"staff", "parent"} and concept_key.startswith("STUDENT_") and "NAME" in concept_key:
                    factor *= 0.6

            if has_name and ("NAME" in concept_key or concept_key.endswith("_ID")):
                if subject_entity == "student" and concept_key.startswith("STUDENT_") and "NAME" in concept_key:
                    factor *= 1.3
                elif concept_key in {"FIRST_NAME", "LAST_NAME", "MIDDLE_NAME"}:
                    factor *= 1.1
            if has_school and ("SCHOOL" in concept_key or concept_key in {"DISTRICT_NAME", "LEA_ID"}):
                factor *= 1.25
            if has_district and "DISTRICT" in concept_key:
                factor *= 1.2
            if has_grade and "GRADE" in concept_key:
                factor *= 1.18
            if has_race and ("RACE" in concept_key or "ETHNIC" in concept_key):
                factor *= 1.18

            row["score"] = round(score * factor, 4)
            row["tier2_factor"] = round(factor, 4)

        rows.sort(key=lambda item: -(_to_float(item.get("score")) or 0.0))
        return self._ensure_keys_in_hits(hits=rows, required_keys=required, max_concepts=max_concepts)

    @staticmethod
    def _extract_values_from_tier2_plan_ir(plan_ir: Any) -> List[Dict[str, Any]]:
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
    def _merge_extracted_values(
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
    def _build_tier2_forced_filters(
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
    def _build_semantic_extract_forced_filters(
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
            row = PlanService._pick_best_el_subgroup_row(mapped_columns=mapped_columns)
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

    def _lexical_alias_concept_hits(self, *, prompt: str, vertical_norm: str) -> List[Dict[str, Any]]:
        ngrams = _build_prompt_ngrams(prompt)
        if not ngrams:
            return []
        vertical = str(vertical_norm or "generic").strip().lower() or "generic"
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
                WHERE vertical_norm IN (:vertical_norm, 'generic')
                  AND (
                    (match_kind = 'exact' AND LOWER(alias_key) = :ngram)
                    OR
                    (match_kind = 'contains' AND :ngram LIKE CONCAT('%', LOWER(alias_key), '%'))
                  )
                ORDER BY
                  CASE WHEN vertical_norm = :vertical_norm THEN 0 ELSE 1 END,
                  weight DESC,
                  id ASC
                """,
                {"vertical_norm": vertical, "ngram": ngram},
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
                if existing is None or self._lexical_rank(candidate) > self._lexical_rank(existing):
                    matches[concept_key] = candidate
        return sorted(matches.values(), key=lambda row: -float(row.get("score") or 0.0))

    @staticmethod
    def _lexical_rank(row: Dict[str, Any]) -> Tuple[float, int, int]:
        score = float(row.get("score") or 0.0)
        ngram_len = len(str(row.get("matched_ngram") or ""))
        exact = 1 if str(row.get("match_kind") or "").lower() == "exact" else 0
        return score, ngram_len, exact

    def _merge_concept_hits(
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
        return self._ensure_keys_in_hits(hits=rows, required_keys=set(lexical_keys), max_concepts=max_concepts)

    @staticmethod
    def _ensure_keys_in_hits(
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

    def _minimize_selected_columns(
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
            if self._is_noisy_projection_concept(concept_key=concept_key) and concept_key not in explicit:
                continue
            key = (concept_key, model_column_id)
            if key in seen:
                continue
            seen.add(key)
            out.append({"concept_key": concept_key, "model_column_id": model_column_id})
        return out

    @staticmethod
    def _is_noisy_projection_concept(*, concept_key: str) -> bool:
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

    def _rebalance_identifier_heavy_hits(
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

        if self._prompt_requests_identifier(prompt):
            return self._ensure_keys_in_hits(hits=deduped, required_keys=force_keys, max_concepts=max_concepts)

        non_identifier_hits: List[Dict[str, Any]] = []
        identifier_hits: List[Dict[str, Any]] = []
        for hit in deduped:
            key = str(hit.get("concept_key") or "").strip().upper()
            if key in force_keys:
                non_identifier_hits.append(dict(hit))
                continue
            info = concept_info.get(key, {})
            if self._is_identifier_like_concept(concept_key=key, concept_info=info):
                adjusted = dict(hit)
                score = _to_float(adjusted.get("score")) or 0.0
                penalty = 0.35 if has_subgroup_intent and not self._prompt_requests_identifier(prompt) else 0.2
                adjusted["score"] = round(score - penalty, 4)
                identifier_hits.append(adjusted)
            else:
                non_identifier_hits.append(dict(hit))

        non_identifier_hits.sort(key=lambda row: -(_to_float(row.get("score")) or 0.0))
        identifier_hits.sort(key=lambda row: -(_to_float(row.get("score")) or 0.0))

        if not non_identifier_hits:
            return identifier_hits[:max_concepts]

        identifier_limit = 1
        out = list(non_identifier_hits[:max_concepts])
        remaining = max(0, max_concepts - len(out))
        if remaining > 0 and identifier_hits:
            out.extend(identifier_hits[: min(remaining, identifier_limit)])
        out = out[: max(max_concepts, len(force_keys))]
        return self._ensure_keys_in_hits(hits=out, required_keys=force_keys, max_concepts=max_concepts)

    @staticmethod
    def _prompt_requests_identifier(prompt: str) -> bool:
        text = str(prompt or "").strip().lower()
        if text == "":
            return False
        return re.search(r"\b(id|ids|identifier|identifiers|code|codes|key|keys|sk)\b", text) is not None

    @staticmethod
    def _is_identifier_like_concept(*, concept_key: str, concept_info: Dict[str, Any]) -> bool:
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

    def _resolve_prompt_value_constraints(
        self,
        *,
        prompt: str,
        vertical_norm: str,
        concept_hits: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        resolved = self._value_alias_resolver.resolve(prompt=prompt, vertical_norm=vertical_norm)
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

    @staticmethod
    def _apply_constraint_overrides_to_concept_hits(
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
    def _build_forced_filters(
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

    def _build_name_forced_filters(
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

        preferred_concepts = _name_concepts_for_entity(entity)
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

    @staticmethod
    def _build_school_forced_filters(
        *,
        extracted_values: Sequence[Dict[str, Any]],
        mapped_columns: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        school_value = _resolve_school_literal(extracted_values)
        if school_value is None:
            return []
        available_concepts = {
            str(row.get("concept_key") or "").strip().upper()
            for row in mapped_columns
            if isinstance(row, dict) and str(row.get("concept_key") or "").strip()
        }
        for concept_key in ("SCHOOL_NAME", "STUDENT_SCHOOL_NAME"):
            if concept_key in available_concepts:
                return [{"concept_key": concept_key, "op": "contains", "value": school_value}]
        return []

    @staticmethod
    def _merge_forced_filters(
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

    def _apply_value_aliases_to_llm_plan(self, *, vertical_norm: str, llm_plan: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(llm_plan, dict):
            return llm_plan
        raw_filters = llm_plan.get("filters")
        if not isinstance(raw_filters, list) or not raw_filters:
            return llm_plan

        concept_keys: List[str] = []
        for item in raw_filters:
            if not isinstance(item, dict):
                continue
            key = str(item.get("concept_key") or "").strip().upper()
            if key and key not in concept_keys:
                concept_keys.append(key)
        if not concept_keys:
            return llm_plan

        rules_by_concept = self._load_value_alias_rules(vertical_norm=vertical_norm, concept_keys=concept_keys)
        normalized_filters, changed = self._normalize_filters_with_value_aliases(raw_filters, rules_by_concept)
        normalized_filters, canonical_changed = self._canonicalize_filters_with_static_aliases(
            filters=normalized_filters,
            vertical_norm=vertical_norm,
        )
        total_changed = changed + canonical_changed
        if total_changed <= 0:
            return llm_plan

        out = dict(llm_plan)
        out["filters"] = normalized_filters
        out["sql_json"] = self._sync_sql_json_filter_values(llm_plan.get("sql_json"), normalized_filters)
        notes_raw = out.get("notes")
        notes = list(notes_raw) if isinstance(notes_raw, list) else []
        notes.append(f"value_aliases_applied={total_changed}")
        out["notes"] = notes
        return out

    @staticmethod
    def _canonicalize_filters_with_static_aliases(
        *,
        filters: Sequence[Dict[str, Any]],
        vertical_norm: str,
    ) -> Tuple[List[Dict[str, Any]], int]:
        out: List[Dict[str, Any]] = []
        changed = 0
        for item in filters:
            if not isinstance(item, dict):
                out.append(item)
                continue
            concept_key = str(item.get("concept_key") or "").strip().upper()
            value = item.get("value")
            if isinstance(value, str) and concept_key:
                canonical = canonicalize_value(concept_key, value, vertical=vertical_norm)
                if canonical and canonical != value:
                    next_item = dict(item)
                    next_item["value"] = canonical
                    out.append(next_item)
                    changed += 1
                    continue
            out.append(dict(item))
        return out, changed

    def _enforce_grounded_org_filters(
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
        sql_json, _ = self._build_grounded_sql_json(
            prompt=prompt,
            domain_id=domain_id,
            selected_columns=[dict(item) for item in list(out.get("selected_columns") or []) if isinstance(item, dict)],
            filters=repaired_filters,
            candidate_by_mid=_candidate_by_mid(mapped_columns),
            candidate_by_concept=_candidate_by_concept(mapped_columns),
            llm_sql_json=out.get("sql_json") if isinstance(out.get("sql_json"), dict) else {},
        )
        out["sql_json"] = sql_json
        return out, list(dict.fromkeys(warnings))

    def _apply_plan_validity_gate(
        self,
        *,
        llm_plan: Dict[str, Any],
        prompt: str,
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
            selected_columns = self._ensure_student_first_last_projection(
                selected_columns=selected_columns,
                mapped_columns=mapped_columns,
            )
            filters = self._ensure_school_name_filter(
                filters=filters,
                extracted_values=extracted_values,
                mapped_columns=mapped_columns,
                prompt=prompt,
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

            out["join_plan"] = self._ensure_student_school_join_plan(
                join_plan=out.get("join_plan"),
                selected_columns=selected_columns,
                filters=filters,
                mapped_columns=mapped_columns,
            )

            sql_json, _ = self._build_grounded_sql_json(
                prompt=prompt,
                domain_id=domain_id,
                selected_columns=selected_columns,
                filters=filters,
                candidate_by_mid=_candidate_by_mid(mapped_columns),
                candidate_by_concept=_candidate_by_concept(mapped_columns),
                llm_sql_json=out.get("sql_json") if isinstance(out.get("sql_json"), dict) else {},
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
            injected_filters = self._build_name_forced_filters(
                prompt=prompt,
                intent_entity=intent,
                extracted_values=extracted_values,
                mapped_columns=mapped_columns,
            )
            if injected_filters:
                filters = self._merge_forced_filters(
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

        sql_json, _ = self._build_grounded_sql_json(
            prompt=prompt,
            domain_id=domain_id,
            selected_columns=[dict(item) for item in out.get("selected_columns", []) if isinstance(item, dict)],
            filters=[dict(item) for item in out.get("filters", []) if isinstance(item, dict)],
            candidate_by_mid=_candidate_by_mid(mapped_columns),
            candidate_by_concept=_candidate_by_concept(mapped_columns),
            llm_sql_json=out.get("sql_json") if isinstance(out.get("sql_json"), dict) else {},
        )
        out["sql_json"] = sql_json
        return out, warnings

    @staticmethod
    def _build_default_projection(
        *,
        intent_entity: str,
        mapped_columns: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        keys = _default_projection_concepts(intent_entity)
        if not keys:
            return []

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
            rows = list(rows_by_concept.get(concept_key) or [])
            if not rows:
                continue
            rows.sort(
                key=lambda item: (
                    0 if str(item.get("table_name") or "").strip().lower() == f"dim_{intent_entity}" else 1,
                    -(_to_float(item.get("effective_weight")) or _to_float(item.get("final_score")) or 0.0),
                    int(item.get("model_column_id") or 0),
                )
            )
            best = rows[0]
            mid = _to_int(best.get("model_column_id"))
            if mid is None or mid in seen_mid:
                continue
            seen_mid.add(mid)
            selected.append({"concept_key": concept_key, "model_column_id": mid})
        if not selected and intent_entity == "student":
            for concept_key in ("STUDENT_ID", "ID"):
                rows = list(rows_by_concept.get(concept_key) or [])
                if not rows:
                    continue
                rows.sort(
                    key=lambda item: (
                        0 if str(item.get("table_name") or "").strip().lower() == "dim_student" else 1,
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

    def _ensure_student_first_last_projection(
        self,
        *,
        selected_columns: Sequence[Dict[str, Any]],
        mapped_columns: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        out = [dict(item) for item in selected_columns if isinstance(item, dict)]
        if _has_student_first_last_projection(out):
            return out

        first_last = self._build_student_first_last_projection(mapped_columns=mapped_columns)
        if not first_last:
            return out
        seen = {
            (_to_int(item.get("model_column_id")), str(item.get("concept_key") or "").strip().upper())
            for item in out
        }
        for item in first_last:
            key = (_to_int(item.get("model_column_id")), str(item.get("concept_key") or "").strip().upper())
            if key in seen:
                continue
            out.append(item)
            seen.add(key)
        return out

    @staticmethod
    def _build_student_first_last_projection(*, mapped_columns: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_concept: Dict[str, List[Dict[str, Any]]] = {}
        for row in mapped_columns:
            if not isinstance(row, dict):
                continue
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if concept_key:
                by_concept.setdefault(concept_key, []).append(dict(row))

        selected: List[Dict[str, Any]] = []
        for concept_candidates in (("STUDENT_FIRST_NAME", "FIRST_NAME"), ("STUDENT_LAST_NAME", "LAST_NAME")):
            chosen: Optional[Dict[str, Any]] = None
            for concept_key in concept_candidates:
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
            if mid is None or concept_key == "":
                continue
            selected.append({"concept_key": concept_key, "model_column_id": mid})
        return selected

    def _ensure_school_name_filter(
        self,
        *,
        filters: Sequence[Dict[str, Any]],
        extracted_values: Sequence[Dict[str, Any]],
        mapped_columns: Sequence[Dict[str, Any]],
        prompt: str,
    ) -> List[Dict[str, Any]]:
        base = [dict(item) for item in filters if isinstance(item, dict)]
        forced = self._build_school_forced_filters(
            extracted_values=extracted_values,
            mapped_columns=mapped_columns,
        )
        return self._merge_forced_filters(
            existing_filters=base,
            forced_filters=forced,
            prompt=prompt,
        )

    @staticmethod
    def _ensure_student_school_join_plan(
        *,
        join_plan: Any,
        selected_columns: Sequence[Dict[str, Any]],
        filters: Sequence[Dict[str, Any]],
        mapped_columns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        current = dict(join_plan) if isinstance(join_plan, dict) else {}
        mid_to_row = _candidate_by_mid(mapped_columns)
        selected_tables = {
            str((mid_to_row.get(_to_int(col.get("model_column_id")) or -1) or {}).get("table_name") or "").strip().lower()
            for col in selected_columns
            if isinstance(col, dict)
        }
        has_school_filter = any(
            str(item.get("concept_key") or "").strip().upper() in {"SCHOOL_NAME", "STUDENT_SCHOOL_NAME"}
            for item in filters
            if isinstance(item, dict)
        )
        if "dim_student" not in selected_tables or not has_school_filter:
            return current

        joins = list(current.get("joins") or [])
        if not any(str(item.get("table") or "").strip().lower() == "dim_school" for item in joins if isinstance(item, dict)):
            joins.append(
                {
                    "table": "dim_school",
                    "on": [{"concept_key": "SCHOOL_ID", "op": "=", "value": "SCHOOL_ID"}],
                }
            )
        current["primary_table"] = str(current.get("primary_table") or "dim_student")
        current["joins"] = joins
        return current

    def _load_value_alias_rules(self, *, vertical_norm: str, concept_keys: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
        keys = [str(k or "").strip().upper() for k in concept_keys if str(k or "").strip()]
        if not keys:
            return {}
        in_sql, in_params = _in_clause("ck", keys)
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              sc.concept_key,
              va.alias_value,
              va.canonical_value,
              va.match_kind,
              va.weight,
              va.vertical_norm
            FROM semantic_value_alias va
            JOIN semantic_concept sc ON sc.id = va.semantic_concept_id
            WHERE sc.concept_key IN ({in_sql})
              AND va.vertical_norm IN (:vertical_norm, 'generic')
            ORDER BY
              CASE WHEN va.vertical_norm = :vertical_norm THEN 0 ELSE 1 END,
              sc.concept_key,
              va.weight DESC,
              va.id ASC
            """,
            {
                **in_params,
                "vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic",
            },
        )
        out: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            key = str(row.get("concept_key") or "").strip().upper()
            if key == "":
                continue
            out.setdefault(key, []).append(dict(row))
        return out

    @staticmethod
    def _normalize_filters_with_value_aliases(
        filters: Sequence[Dict[str, Any]],
        rules_by_concept: Dict[str, List[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], int]:
        out: List[Dict[str, Any]] = []
        changed = 0
        for item in filters:
            if not isinstance(item, dict):
                out.append(item)
                continue
            key = str(item.get("concept_key") or "").strip().upper()
            rules = rules_by_concept.get(key, [])
            next_item = dict(item)
            next_value, did_change = PlanService._normalize_filter_value_with_rules(item.get("value"), rules)
            if did_change:
                changed += 1
                next_item["value"] = next_value
            out.append(next_item)
        return out, changed

    @staticmethod
    def _normalize_filter_value_with_rules(value: Any, rules: Sequence[Dict[str, Any]]) -> Tuple[Any, bool]:
        if not rules:
            return value, False
        if isinstance(value, str):
            return PlanService._apply_value_alias_rules_to_string(value, rules)
        if isinstance(value, list):
            did_change = False
            out: List[Any] = []
            for item in value:
                if isinstance(item, str):
                    normalized, changed = PlanService._apply_value_alias_rules_to_string(item, rules)
                    out.append(normalized)
                    did_change = did_change or changed
                else:
                    out.append(item)
            return out, did_change
        return value, False

    @staticmethod
    def _apply_value_alias_rules_to_string(value: str, rules: Sequence[Dict[str, Any]]) -> Tuple[str, bool]:
        source = str(value or "").strip()
        if source == "":
            return value, False
        source_lower = source.lower()

        for rule in rules:
            alias = str(rule.get("alias_value") or "").strip()
            canonical = str(rule.get("canonical_value") or "").strip()
            match_kind = str(rule.get("match_kind") or "contains").strip().lower()
            if alias == "" or canonical == "":
                continue

            alias_lower = alias.lower()
            matched = False
            if match_kind == "exact":
                matched = source_lower == alias_lower
            elif match_kind == "contains":
                matched = alias_lower in source_lower
            elif match_kind == "prefix":
                matched = source_lower.startswith(alias_lower)
            elif match_kind == "regex":
                try:
                    matched = re.search(alias, source, flags=re.IGNORECASE) is not None
                except re.error:
                    matched = False
            if matched:
                return canonical, canonical != value
        return value, False

    @staticmethod
    def _sync_sql_json_filter_values(sql_json: Any, filters: Sequence[Dict[str, Any]]) -> Any:
        if not isinstance(sql_json, dict) or not isinstance(filters, Sequence):
            return sql_json
        try:
            out = json.loads(json.dumps(sql_json))
        except Exception:
            out = dict(sql_json)

        where_node = out.get("where")
        if isinstance(where_node, list):
            PlanService._sync_where_items(where_node, filters)
        elif isinstance(where_node, dict):
            conds = where_node.get("conditions")
            if isinstance(conds, list):
                PlanService._sync_where_items(conds, filters)

        filters_node = out.get("filters")
        if isinstance(filters_node, dict):
            conditions: List[Dict[str, Any]] = []
            PlanService._collect_filter_conditions(filters_node, conditions)
            for idx, cond in enumerate(conditions):
                if idx >= len(filters):
                    break
                cond["value"] = filters[idx].get("value")
        return out

    @staticmethod
    def _sync_where_items(where_items: List[Any], filters: Sequence[Dict[str, Any]]) -> None:
        for idx, item in enumerate(where_items):
            if idx >= len(filters):
                break
            if not isinstance(item, dict):
                continue
            value = filters[idx].get("value")
            param = item.get("param")
            if isinstance(param, dict):
                param["value"] = value
            elif "value" in item:
                item["value"] = value

    @staticmethod
    def _collect_filter_conditions(node: Dict[str, Any], out: List[Dict[str, Any]]) -> None:
        node_type = str(node.get("type") or "").strip().lower()
        if node_type == "condition":
            out.append(node)
            return
        if node_type != "group":
            return
        for child in node.get("children") or []:
            if isinstance(child, dict):
                PlanService._collect_filter_conditions(child, out)


def _dedupe_text_values(values: Sequence[Any]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if text == "":
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _first_nonempty(values: Sequence[Any]) -> Optional[str]:
    for raw in values:
        text = str(raw or "").strip()
        if text:
            return text
    return None


def is_grounded_value(value: str, spacy: Dict[str, Any], gazetteer_matches: Sequence[str]) -> bool:
    candidate = _normalize_grounded_text(value)
    if candidate == "":
        return False

    grounded_values: List[str] = []
    slots = spacy.get("slots") if isinstance(spacy.get("slots"), dict) else {}
    by_label = spacy.get("by_label") if isinstance(spacy.get("by_label"), dict) else {}
    ents = spacy.get("ents") if isinstance(spacy.get("ents"), list) else []

    for bucket in (
        list(slots.get("org_districts") or []),
        list(slots.get("org_schools") or []),
        list(by_label.get("ORG_DISTRICT") or []),
        list(by_label.get("ORG_SCHOOL") or []),
        list(gazetteer_matches or []),
    ):
        for raw in bucket:
            text = _normalize_grounded_text(raw)
            if text:
                grounded_values.append(text)

    for ent in ents:
        if not isinstance(ent, dict):
            continue
        label = str(ent.get("label") or "").strip().upper()
        if label not in {"ORG_DISTRICT", "ORG_SCHOOL"}:
            continue
        text = _normalize_grounded_text(ent.get("text"))
        if text:
            grounded_values.append(text)

    for grounded in grounded_values:
        if grounded == candidate:
            return True
        if grounded in candidate or candidate in grounded:
            return True
    return False


def _normalize_grounded_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text == "":
        return ""
    text = re.sub(r"[^\w\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_prompt_ngrams(prompt: str) -> List[str]:
    text = str(prompt or "").lower()
    text = re.sub(r"[^a-z0-9\\s]+", " ", text)
    tokens = [tok for tok in text.split() if tok]
    out: List[str] = []
    for n in (3, 2, 1):
        for idx in range(0, max(0, len(tokens) - n + 1)):
            out.append(" ".join(tokens[idx : idx + n]))
    return list(dict.fromkeys(out))


def _prompt_has_student_intent(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    return re.search(r"\b(student|students|kid|kids|pupil|pupils|learner|learners)\b", text) is not None


def _infer_intent_entity(prompt: str) -> Optional[str]:
    text = str(prompt or "").strip().lower()
    if text == "":
        return None
    if re.search(r"\b(student|students|kid|kids|pupil|pupils|learner|learners)\b", text):
        return "student"
    if re.search(r"\b(staff|teacher|teachers)\b", text):
        return "staff"
    if re.search(r"\b(parent|parents)\b", text):
        return "parent"
    return None


def _norm_entity(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if text in {"student", "staff", "parent"}:
        return text
    return None


def _name_concepts_for_entity(entity: str) -> List[str]:
    if entity == "student":
        return ["STUDENT_LAST_NAME", "LAST_NAME", "STUDENT_FIRST_NAME", "FIRST_NAME"]
    if entity == "staff":
        return ["STAFF_LAST_NAME", "LAST_NAME", "STAFF_FIRST_NAME", "FIRST_NAME"]
    if entity == "parent":
        return ["PARENT_LAST_NAME", "LAST_NAME", "PARENT_FIRST_NAME", "FIRST_NAME"]
    return []


def _default_projection_concepts(entity: str) -> List[str]:
    if entity == "student":
        return [
            "STUDENT_ID",
            "STUDENT_FIRST_NAME",
            "FIRST_NAME",
            "STUDENT_LAST_NAME",
            "LAST_NAME",
        ]
    if entity == "staff":
        return ["STAFF_ID", "STAFF_FIRST_NAME", "FIRST_NAME", "STAFF_LAST_NAME", "LAST_NAME"]
    if entity == "parent":
        return ["PARENT_ID", "PARENT_FIRST_NAME", "FIRST_NAME", "PARENT_LAST_NAME", "LAST_NAME"]
    return []


def _resolve_name_literal(*, prompt: str, extracted_values: Sequence[Dict[str, Any]]) -> Optional[str]:
    for item in extracted_values:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").strip().lower() != "name":
            continue
        value = str(item.get("value") or "").strip()
        if value:
            return value
    text = str(prompt or "").strip()
    pattern = re.compile(r"\b(?:named|name\s+is|called)\s+([A-Za-z][A-Za-z'\-]*)", flags=re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    value = str(match.group(1) or "").strip()
    return value or None


def _resolve_required_literal(*, prompt: str, extracted_values: Sequence[Dict[str, Any]]) -> Optional[str]:
    extracted = _resolve_name_literal(prompt=prompt, extracted_values=extracted_values)
    if extracted:
        return extracted
    tokens = re.findall(r"[A-Za-z][A-Za-z'\-]*", str(prompt or ""))
    subgroup_acronyms = {"EL", "ELL", "ESL", "LEP", "MLL", "IEP", "SPED"}
    for idx, token in enumerate(tokens):
        if idx == 0:
            continue
        if token.upper() in subgroup_acronyms:
            continue
        if token[:1].isupper():
            return token
    return None


def _resolve_school_literal(extracted_values: Sequence[Dict[str, Any]]) -> Optional[str]:
    for item in extracted_values:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").strip().lower() != "school_name":
            continue
        value = str(item.get("value") or "").strip()
        if value:
            return value
    return None


def _prompt_requests_first_last_names(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    has_first = re.search(r"\bfirst\b", text) is not None
    has_last = re.search(r"\blast\b", text) is not None
    has_name = re.search(r"\bname\b|\bnames\b", text) is not None
    return has_first and has_last and has_name


def _requires_student_name_projection_with_school(
    *,
    prompt: str,
    intent_entity: Optional[str],
    school_literal: Optional[str],
) -> bool:
    return (
        str(intent_entity or "").strip().lower() == "student"
        and _prompt_requests_first_last_names(prompt)
        and bool(school_literal)
    )


def _has_student_first_last_projection(selected_columns: Sequence[Dict[str, Any]]) -> bool:
    keys = {
        str(item.get("concept_key") or "").strip().upper()
        for item in selected_columns
        if isinstance(item, dict)
    }
    has_first = bool(keys & {"STUDENT_FIRST_NAME", "FIRST_NAME"})
    has_last = bool(keys & {"STUDENT_LAST_NAME", "LAST_NAME"})
    return has_first and has_last


def _has_school_name_filter(*, filters: Sequence[Dict[str, Any]], school_literal: Optional[str]) -> bool:
    target = str(school_literal or "").strip().lower()
    if target == "":
        return False
    for item in filters:
        if not isinstance(item, dict):
            continue
        concept_key = str(item.get("concept_key") or "").strip().upper()
        if concept_key not in {"SCHOOL_NAME", "STUDENT_SCHOOL_NAME"}:
            continue
        value = str(item.get("value") or "").strip().lower()
        if target in value:
            return True
    return False


def _concept_entity_factor(
    *,
    intent_entity: str,
    concept_key: str,
    concept_entity: Optional[str],
) -> float:
    key = str(concept_key or "").strip().upper()
    entity = _norm_entity(concept_entity)
    factor = 1.0

    if entity == intent_entity:
        factor = 1.4
    elif entity is not None and entity != intent_entity:
        factor = 0.7

    if intent_entity == "student":
        if key in {"STUDENT_FIRST_NAME", "STUDENT_LAST_NAME", "STUDENT_MIDDLE_NAME"}:
            return max(factor, 1.6)
        if key in {"FIRST_NAME", "LAST_NAME", "MIDDLE_NAME"}:
            return min(factor, 0.85)
        if key.startswith("STAFF_") and "NAME" in key:
            return min(factor, 0.5)
        if key.startswith("PARENT_") and "NAME" in key:
            return min(factor, 0.5)
    return factor


def _filters_contain_literal(*, filters: Sequence[Dict[str, Any]], literal: str) -> bool:
    target = str(literal or "").strip().lower()
    if target == "":
        return False
    for item in filters:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if isinstance(value, str) and target in value.strip().lower():
            return True
        if isinstance(value, list):
            for element in value:
                if isinstance(element, str) and target in element.strip().lower():
                    return True
    return False


def _candidate_by_mid(candidate_columns: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for row in candidate_columns:
        if not isinstance(row, dict):
            continue
        mid = _to_int(row.get("model_column_id"))
        if mid is None:
            continue
        out[mid] = dict(row)
    return out


def _candidate_by_concept(candidate_columns: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for row in candidate_columns:
        if not isinstance(row, dict):
            continue
        concept_key = str(row.get("concept_key") or "").strip().upper()
        if concept_key == "":
            continue
        out.setdefault(concept_key, []).append(dict(row))
    return out


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _trim(value: str, size: int) -> str:
    text = str(value or "").strip()
    if len(text) <= size:
        return text
    return text[:size].rstrip()


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _dict_get(payload: Any, *path: str) -> Any:
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _in_clause(prefix: str, values: Sequence[str]) -> Tuple[str, Dict[str, Any]]:
    params: Dict[str, Any] = {}
    names: List[str] = []
    for idx, val in enumerate(values):
        key = f"{prefix}{idx}"
        names.append(f":{key}")
        params[key] = str(val)
    return ", ".join(names), params


__all__ = ["PlanService"]
