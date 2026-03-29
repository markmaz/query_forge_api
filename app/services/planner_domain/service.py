from __future__ import annotations

import logging
import uuid
from time import perf_counter
from typing import Any, Dict, List, Mapping, Optional

from pydantic import ValidationError

from app.config.llm_resolver import build_llm_client_for_role
from app.config import (
    EMBEDDING_MODEL_NAME,
    PLANNER_UNIFIED_LLM,
    QDRANT_COLUMN_COLLECTION_V2,
    QF_PLAN_DOMAIN_FAST_MODE_DEFAULT,
    QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED,
    QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED,
    QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED,
    QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_ITEMS,
    QF_PLAN_DOMAIN_NEXT_ACTIONS_ASYNC_DEFAULT,
    QF_PLAN_DOMAIN_PIPELINE_TRACE_ENABLED,
    QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE,
    QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE,
    QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED,
    QF_PLAN_DOMAIN_TIMING_PROFILE_ENABLED,
    SEMANTIC_PLAN_LLM_MODEL,
    SEMANTIC_PLAN_LLM_TIMEOUT_SECONDS,
    VLLM_BASE_URL,
)
from app.constants.llm_roles import LLMRole
from app.exceptions.forge_error import ForgeError
from app.infra.embedding_model import EmbeddingModel
from app.infra.qdrant_client import QdrantClientWrapper
from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.services.domains.capabilities_service import DomainCapabilitiesService
from app.services.domain.domain_time_policy_service import DomainTimePolicyService
from app.services.domain.planner_domain_capability_service import PlannerDomainCapabilityService
from app.services.domain.planner_rerank_policy_service import PlannerRerankPolicyService
from app.services.llm.llm_client import LLMClient
from app.services.planner.semantic_grounding_service import SemanticGroundingService
from app.services.planner_domain.conversation_store import (
    HybridPlannerDomainConversationStore,
    PlannerDomainConversationStore,
    default_conversation_ttl_seconds,
    new_conversation_id,
)
from app.services.planner_domain.conversation_context import (
    _bootstrap_conversation_state_from_seed,
    _norm_vertical,
    _plan_conversation_context_from_state,
    normalize_plan_prompt,
)
from app.services.planner_domain.column_scoring import (
    _column_heuristic_boost,
    _required_column_keys,
)
from app.services.planner_domain.domain_selection_service import DomainSelectionService
from app.services.planner_domain.explanation_service import ExplanationService
from app.services.planner_domain.llm_planning_service import LLMPlanningService
from app.services.planner_domain.next_actions_service import NextActionsService
import app.services.planner_domain.next_actions_service as next_actions_service_module
import app.services.planner_domain.pipeline_trace as pipeline_trace_module
from app.services.planner_domain.plan_postprocess_service import PlanPostprocessService
from app.services.planner_domain.plan_enrichment_service import PlanEnrichmentService
from app.services.planner_domain.plan_finalization_service import PlanFinalizationService
from app.services.planner_domain.semantic_integration_service import SemanticIntegrationService
from app.services.planner_domain.response_builder_service import PlannerResponseBuilderService
from app.services.planner_domain.map_to_sqljson import map_plan_v2_to_sqljson
from app.services.planner_domain.prompt_signal_service import PromptSignalService
from app.services.planner_domain.rerank_policy_engine import PlannerDomainRerankPolicyEngine
from app.services.planner_domain.schema_v2 import plan_v2_json_schema
from app.services.planner_domain.types import (
    PlanDomainNextActionsRequest,
    PlanDomainRequest,
)
from app.services.planner_domain.normalizers.entity import (
    _normalize_country_filters_in_plan,
    _normalize_school_name_filters_in_plan,
    _normalize_staff_role_filters_in_plan,
)
from app.services.planner_domain.normalizers.metric import (
    _normalize_adm_default_filters_in_plan,
    _normalize_top_bottom_ranking_in_plan,
)
from app.services.planner_domain.normalizers.time import (
    _normalize_relative_time_in_plan,
    _normalize_year_keyword_filters_in_plan,
    _normalize_school_year_filters_in_plan,
    _normalize_semester_filters_in_plan,
)
from app.services.planner_domain.normalization_pipeline import NormalizationPipeline
from app.services.planner_domain.pipeline_trace import (
    _add_pipeline_step,
    _append_pipeline_trace_step,
    _capabilities_summary,
    _elapsed_ms,
    PipelineTraceService,
)
from app.services.planner_domain.plan_helpers import (
    _selected_domain_name,
    _serialize_domain_candidates_for_debug,
    _to_int,
)
from app.services.semantic.value_alias_resolution_service import ValueAliasResolutionService
from app.services.vector import DomainVectorIndexService

logger = logging.getLogger(__name__)


class PlannerDomainService:
    def __init__(
        self,
        *,
        capabilities_service: Optional[DomainCapabilitiesService] = None,
        domain_vector_service: Optional[DomainVectorIndexService] = None,
        llm_client: Optional[LLMClient] = None,
        embedding_model: Optional[EmbeddingModel] = None,
        column_qdrant: Optional[QdrantClientWrapper] = None,
        value_alias_resolver: Optional[ValueAliasResolutionService] = None,
        semantic_grounding_service: Optional[SemanticGroundingService] = None,
        domain_time_policy_service: Optional[DomainTimePolicyService] = None,
        planner_domain_capability_service: Optional[PlannerDomainCapabilityService] = None,
        planner_rerank_policy_service: Optional[PlannerRerankPolicyService] = None,
        prompt_signal_service: Optional[PromptSignalService] = None,
        conversation_store: Optional[PlannerDomainConversationStore] = None,
        conversation_ttl_seconds: Optional[int] = None,
        pipeline_trace_service: Optional[PipelineTraceService] = None,
    ) -> None:
        self._capabilities = capabilities_service or DomainCapabilitiesService()
        self._domain_vector = domain_vector_service or DomainVectorIndexService()
        self._explicit_llm = llm_client is not None
        self._llm = llm_client or LLMClient(
            endpoint=VLLM_BASE_URL,
            model=SEMANTIC_PLAN_LLM_MODEL,
            timeout_seconds=SEMANTIC_PLAN_LLM_TIMEOUT_SECONDS,
        )
        self._embedding = embedding_model
        self._column_qdrant = column_qdrant
        pipeline_trace_module.QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE = QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE
        pipeline_trace_module.QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE = QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE
        next_actions_service_module.QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED = QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED
        next_actions_service_module.QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_ITEMS = QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_ITEMS
        self._semantic_integration = SemanticIntegrationService(
            value_alias_resolver=value_alias_resolver or ValueAliasResolutionService(sql=ForgeMetaSQL()),
            semantic_grounding_service=semantic_grounding_service,
        )
        self._normalization = NormalizationPipeline(
            normalizers=[
                ("country", _normalize_country_filters_in_plan),
                ("school_year", _normalize_school_year_filters_in_plan),
                ("year_keyword", _normalize_year_keyword_filters_in_plan),
                ("semester", _normalize_semester_filters_in_plan),
                ("school_name", _normalize_school_name_filters_in_plan),
                ("staff_role", _normalize_staff_role_filters_in_plan),
                ("adm_default", _normalize_adm_default_filters_in_plan),
                ("relative_time", _normalize_relative_time_in_plan),
                ("top_bottom", _normalize_top_bottom_ranking_in_plan),
            ]
        )
        self._domain_time_policy = domain_time_policy_service or DomainTimePolicyService()
        self._planner_domain_capabilities = planner_domain_capability_service or PlannerDomainCapabilityService()
        self._planner_rerank_policies = planner_rerank_policy_service or PlannerRerankPolicyService()
        self._prompt_signal_service = prompt_signal_service or PromptSignalService()
        self._rerank_policy_engine = PlannerDomainRerankPolicyEngine(
            prompt_signal_service=self._prompt_signal_service,
            capability_service=self._planner_domain_capabilities,
            policy_service=self._planner_rerank_policies,
        )
        self._domain_selection = DomainSelectionService(
            domain_vector=self._domain_vector,
            capabilities_service=self._capabilities,
            rerank_policy_engine=self._rerank_policy_engine,
            embedding_model_factory=self._embedding_model,
            column_vector_factory=self._column_vector_client,
            semantic_grounding_factory=self._semantic_integration._semantic_grounding_service,
            semantic_alias_constraints_fn=self._semantic_integration.resolve_alias_constraints,
        )
        self._llm_planning = LLMPlanningService(llm_client=self._llm)
        self._explanation = ExplanationService(
            llm_client=self._llm,
            llm_explanation_enabled=QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED,
        )
        self._next_actions = NextActionsService(llm_client=self._llm)
        self._postprocess = PlanPostprocessService(
            llm_planning_service=self._llm_planning,
            semantic_integration=self._semantic_integration,
            normalization_pipeline=self._normalization,
        )
        self._enrichment = PlanEnrichmentService(
            explanation_service=self._explanation,
            next_actions_service=self._next_actions,
        )
        self._response_builder = PlannerResponseBuilderService()
        self._pipeline_trace = pipeline_trace_service or PipelineTraceService()
        self._conversation_store = conversation_store or HybridPlannerDomainConversationStore()
        self._conversation_ttl_seconds = max(60, int(conversation_ttl_seconds or default_conversation_ttl_seconds()))
        self._finalization = PlanFinalizationService(
            conversation_store=self._conversation_store,
            conversation_ttl_seconds=self._conversation_ttl_seconds,
            pipeline_trace_service=self._pipeline_trace,
        )
        self._llm_runtime_meta: Dict[str, Any] = {
            "source": "bootstrap",
            "role": LLMRole.PLANNER,
            "llm_id": None,
            "provider": "generic",
            "model": str(getattr(self._llm, "_model", "") or ""),
            "endpoint": str(getattr(self._llm, "_endpoint", "") or ""),
        }

    def _resolve_runtime_llm(
        self,
        *,
        workspace_id: str,
        role: str,
        llm_id_override: Optional[int] = None,
    ) -> None:
        if self._explicit_llm:
            return
        resolved = build_llm_client_for_role(
            workspace_id=workspace_id,
            role=role,
            llm_id_override=llm_id_override,
            timeout_seconds=None,
        )
        self._llm = resolved.client
        self._llm_planning._llm = self._llm
        self._explanation = ExplanationService(
            llm_client=self._llm,
            llm_explanation_enabled=QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED,
        )
        self._enrichment = PlanEnrichmentService(
            explanation_service=self._explanation,
            next_actions_service=self._next_actions,
        )
        self._postprocess = PlanPostprocessService(
            llm_planning_service=self._llm_planning,
            semantic_integration=self._semantic_integration,
            normalization_pipeline=self._normalization,
        )
        self._llm_runtime_meta = {
            "source": resolved.source,
            "role": resolved.role,
            "llm_id": resolved.llm_id,
            "provider": resolved.provider,
            "model": resolved.model,
            "endpoint": resolved.endpoint,
        }

    def plan(
        self,
        payload: Dict[str, Any],
        *,
        user_id: str,
    ) -> Dict[str, Any]:
        try:
            req = PlanDomainRequest.model_validate(payload or {})
        except ValidationError as exc:
            raise ForgeError("Invalid plan_domain request", status_code=400, details={"errors": exc.errors()}) from exc
        self._resolve_runtime_llm(
            workspace_id=req.workspace_id,
            role=LLMRole.PLANNER,
            llm_id_override=req.llm_id,
        )

        profile_enabled = bool(QF_PLAN_DOMAIN_TIMING_PROFILE_ENABLED or req.profile_pipeline)
        trace_capture_enabled = bool(
            QF_PLAN_DOMAIN_PIPELINE_TRACE_ENABLED
            or req.profile_pipeline_data
            or req.profile_pipeline
        )
        pipeline_profile_steps: List[Dict[str, Any]] = []
        t0 = perf_counter()
        t_context = perf_counter()

        conversation_id = req.conversation_id or new_conversation_id()
        seeded_from_client = False
        seed_plan = dict(req.context_seed_plan_json_v2 or {}) if isinstance(req.context_seed_plan_json_v2, Mapping) else {}
        seed_last_prompt = normalize_plan_prompt(str(req.context_seed_last_prompt or "")) if req.context_seed_last_prompt else ""
        try:
            prior_state = self._conversation_store.get_state(
                workspace_id=req.workspace_id,
                user_id=str(user_id),
                conversation_id=conversation_id,
            )
        except Exception as exc:
            logger.warning("planner_domain conversation load failed conversation_id=%s err=%s", conversation_id, exc)
            prior_state = None
        if req.conversation_id and prior_state is None:
            if seed_plan:
                seeded_from_client = True
                prior_state = _bootstrap_conversation_state_from_seed(
                    workspace_id=req.workspace_id,
                    user_id=str(user_id),
                    vertical_norm=req.vertical_norm,
                    seed_plan_json_v2=seed_plan,
                    seed_last_prompt=seed_last_prompt,
                )
            elif req.allow_unknown_conversation:
                prior_state = None
            else:
                raise ForgeError("Conversation not found", status_code=404, details={"conversation_id": conversation_id})
        context = _plan_conversation_context_from_state(
            conversation_id=conversation_id,
            prompt=req.prompt,
            state=prior_state,
            force_followup=seeded_from_client,
            seeded_from_client=seeded_from_client,
        )
        _add_pipeline_step(
            profile_steps=pipeline_profile_steps,
            enabled=profile_enabled,
            step="conversation_context",
            label="Load and prepare conversation context",
            started_at=t_context,
        )

        fast_mode = bool(req.fast_mode) if req.fast_mode is not None else bool(QF_PLAN_DOMAIN_FAST_MODE_DEFAULT)
        trace_id = str(uuid.uuid4())
        pipeline_trace: Dict[str, Any] = {
            "trace_id": trace_id,
            "workspace_id": req.workspace_id,
            "user_id": str(user_id),
            "conversation_id": conversation_id,
            "prompt": req.prompt,
            "fast_mode": fast_mode,
            "planner_unified_llm": bool(PLANNER_UNIFIED_LLM),
            "planner_compact_enabled": bool(QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED),
            "llm_resolution": dict(self._llm_runtime_meta),
            "steps": [],
        }
        timings: Dict[str, int] = {}

        t_prompt_norm = perf_counter()
        normalized_prompt = normalize_plan_prompt(req.prompt)
        vertical = _norm_vertical(req.vertical_norm)
        if context is not None and vertical == "generic" and context.prior_vertical_norm in {"education", "healthcare"}:
            vertical = context.prior_vertical_norm
        _add_pipeline_step(
            profile_steps=pipeline_profile_steps,
            enabled=profile_enabled,
            step="normalize_prompt_and_vertical",
            label="Normalize prompt and effective vertical",
            started_at=t_prompt_norm,
        )
        pipeline_trace["normalized_prompt"] = normalized_prompt
        pipeline_trace["vertical_norm"] = vertical
        _append_pipeline_trace_step(
            trace=pipeline_trace,
            enabled=trace_capture_enabled,
            step="normalize_prompt_and_vertical",
            data={
                "prompt": req.prompt,
                "normalized_prompt": normalized_prompt,
                "vertical_norm": vertical,
                "conversation_context_used": context is not None,
                "followup_mode": bool(context and context.followup_mode),
            },
        )

        effective_domain_id = req.base_domain_id
        if effective_domain_id is None and context is not None and context.followup_mode:
            effective_domain_id = _to_int((context.prior_plan_json_v2 or {}).get("base_domain_id"))

        t_domain = perf_counter()
        (
            domain_candidates,
            selected_domain_id,
            capabilities,
            shortlisted_columns,
            ranking_debug,
            rerank_signals,
        ) = self._domain_selection.select_domain_and_shortlist(
            workspace_id=req.workspace_id,
            user_id=str(user_id),
            vertical_norm=vertical,
            prompt=normalized_prompt,
            provided_domain_id=effective_domain_id,
        )
        timings["domain_selection"] = _add_pipeline_step(
            profile_steps=pipeline_profile_steps,
            enabled=profile_enabled,
            step="domain_selection",
            label="Select candidate domains from vector index",
            started_at=t_domain,
        )
        _append_pipeline_trace_step(
            trace=pipeline_trace,
            enabled=trace_capture_enabled,
            step="domain_selection",
            data={
                "provided_domain_id": effective_domain_id,
                "domain_candidates": _serialize_domain_candidates_for_debug(domain_candidates),
            },
        )

        t_caps = perf_counter()
        capabilities_full = DomainSelectionService.full_capabilities_for_execution(capabilities)
        semester_indicator_columns = self._semantic_integration.resolve_semester_indicator_columns(
            workspace_id=req.workspace_id,
            vertical_norm=vertical,
            capabilities=capabilities_full,
        )
        timings["capabilities"] = _add_pipeline_step(
            profile_steps=pipeline_profile_steps,
            enabled=profile_enabled,
            step="capabilities",
            label="Load capabilities, shortlist columns, resolve semester indicators",
            started_at=t_caps,
        )
        _append_pipeline_trace_step(
            trace=pipeline_trace,
            enabled=trace_capture_enabled,
            step="capabilities",
            data={
                "selected_domain_id": selected_domain_id,
                "selected_domain_name": _selected_domain_name(
                    domain_candidates=domain_candidates,
                    selected_domain_id=selected_domain_id,
                ),
                "shortlisted_columns_count": len(shortlisted_columns),
                "ranking_debug": ranking_debug,
                "capabilities_summary": _capabilities_summary(capabilities),
            },
        )

        selected_domain_name = _selected_domain_name(domain_candidates=domain_candidates, selected_domain_id=selected_domain_id)
        domain_time_policy: Dict[str, Any] = {}
        if selected_domain_id is not None:
            try:
                policy_resp = self._domain_time_policy.get_policy(
                    workspace_id=req.workspace_id,
                    user_id=str(user_id),
                    domain_id=int(selected_domain_id),
                )
                policy_obj = policy_resp.get("policy") if isinstance(policy_resp, Mapping) else None
                if isinstance(policy_obj, Mapping):
                    domain_time_policy = dict(policy_obj)
            except Exception as exc:
                logger.warning(
                    "planner_domain time_policy_load_failed workspace_id=%s domain_id=%s trace_id=%s err=%s",
                    req.workspace_id,
                    selected_domain_id,
                    trace_id,
                    exc,
                )
                domain_time_policy = {}
        _append_pipeline_trace_step(
            trace=pipeline_trace,
            enabled=trace_capture_enabled,
            step="time_policy",
            data={"domain_time_policy": domain_time_policy},
        )
        semantic_grounding_bundle = None
        semantic_value_alias_constraints: List[Dict[str, Any]] = []
        semantic_grounding_debug: Optional[Dict[str, Any]] = None
        if QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED:
            semantic_capabilities = self._domain_selection.compact_capabilities_for_llm(
                capabilities=capabilities,
                shortlisted_columns=shortlisted_columns,
                prompt=normalized_prompt,
                slot_hints=None,
                fast_mode=fast_mode,
            )
            semantic_grounding_bundle = self._semantic_integration.build_grounding_bundle(
                prompt=normalized_prompt,
                workspace_id=req.workspace_id,
                vertical_norm=vertical,
                base_domain_id=int(selected_domain_id),
                base_domain_name=selected_domain_name,
                capabilities_compact=semantic_capabilities,
                include_candidates=bool(QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED or req.debug),
                include_alias_constraints=True,
            )
            semantic_value_alias_constraints = list(semantic_grounding_bundle.alias_constraints or [])
            if req.debug:
                semantic_grounding_debug = semantic_grounding_bundle.to_debug_payload()
        schema = plan_v2_json_schema()
        llm_execution = self._llm_planning.execute_plan_generation(
            prompt=req.prompt,
            normalized_prompt=normalized_prompt,
            workspace_id=req.workspace_id,
            vertical_norm=vertical,
            base_domain_id=selected_domain_id,
            domain_name=selected_domain_name,
            capabilities=capabilities,
            shortlisted_columns=shortlisted_columns,
            schema=schema,
            conversation_context=context,
            fast_mode=fast_mode,
            trace_id=trace_id,
            semantic_constraints=semantic_value_alias_constraints,
            grounding_bundle=semantic_grounding_bundle,
            compact_capabilities_fn=self._domain_selection.compact_capabilities_for_llm,
            planner_unified_llm=bool(PLANNER_UNIFIED_LLM),
            compact_planner_enabled=bool(QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED),
            profile_pipeline_requested=bool(req.profile_pipeline),
            profile_pipeline_data_requested=bool(req.profile_pipeline_data),
            profile_enabled=profile_enabled,
            profile_steps=pipeline_profile_steps,
            pipeline_trace=pipeline_trace,
            trace_capture_enabled=trace_capture_enabled,
        )
        timings.update(llm_execution.timings)
        slots_result = llm_execution.slots_result
        slot_hints = llm_execution.slot_hints
        capabilities_llm = llm_execution.capabilities_llm
        llm_result = llm_execution.llm_result
        unified_trace = llm_execution.unified_trace

        postprocess_result = self._postprocess.run(
            llm_result=llm_result,
            slot_hints=slot_hints,
            capabilities_llm=capabilities_llm,
            trace_id=trace_id,
            workspace_id=req.workspace_id,
            vertical_norm=vertical,
            base_domain_id=selected_domain_id,
            base_domain_name=selected_domain_name,
            prompt=normalized_prompt,
            capabilities=capabilities_full,
            conversation_context=context,
            semester_indicator_columns=semester_indicator_columns,
            domain_time_policy=domain_time_policy,
            schema=schema,
            fast_mode=fast_mode,
            profile_steps=pipeline_profile_steps,
            profile_enabled=profile_enabled,
            pipeline_trace=pipeline_trace,
            trace_capture_enabled=trace_capture_enabled,
        )
        timings.update(postprocess_result.timings)
        validated = postprocess_result.validated
        llm_result = postprocess_result.llm_result
        semantic_alias_debug = postprocess_result.semantic_alias_debug
        country_debug = postprocess_result.country_debug
        school_year_debug = postprocess_result.school_year_debug
        semester_debug = postprocess_result.semester_debug
        school_name_debug = postprocess_result.school_name_debug
        staff_role_debug = postprocess_result.staff_role_debug
        adm_default_debug = postprocess_result.adm_default_debug
        district_county_retry_hint = postprocess_result.district_county_retry_hint

        t_map = perf_counter()
        sql_json = (
            map_plan_v2_to_sqljson(plan_json=validated.plan_json, capabilities=capabilities_full, prompt=req.prompt)
            if validated.is_valid
            else {}
        )
        timings["map_to_sqljson"] = _add_pipeline_step(
            profile_steps=pipeline_profile_steps,
            enabled=profile_enabled,
            step="map_to_sqljson",
            label="Map validated plan to SQL JSON",
            started_at=t_map,
        )
        _append_pipeline_trace_step(
            trace=pipeline_trace,
            enabled=trace_capture_enabled,
            step="map_to_sqljson",
            data={"sql_json": sql_json},
        )

        next_actions_async = (
            bool(req.next_actions_async)
            if req.next_actions_async is not None
            else bool(QF_PLAN_DOMAIN_NEXT_ACTIONS_ASYNC_DEFAULT)
        )
        enrichment = self._enrichment.run(
            selected_domain_id=selected_domain_id,
            selected_domain_name=selected_domain_name,
            validated_plan_json=validated.plan_json,
            capabilities=capabilities_full,
            domain_candidates=domain_candidates,
            ranking_debug=ranking_debug,
            shortlisted_columns=shortlisted_columns,
            country_debug=country_debug,
            school_year_debug=school_year_debug,
            semester_debug=semester_debug,
            prompt=normalized_prompt,
            next_actions_async=next_actions_async,
            profile_steps=pipeline_profile_steps,
            profile_enabled=profile_enabled,
            pipeline_trace=pipeline_trace,
            trace_capture_enabled=trace_capture_enabled,
        )
        explanation = enrichment.explanation
        explanation_summary_trace = enrichment.explanation_summary_trace
        next_actions = enrichment.next_actions
        next_actions_trace = enrichment.next_actions_trace

        technical_details = {
            "trace_id": trace_id,
            "conversation_id": conversation_id,
            "fast_mode": fast_mode,
            "planner_unified_llm": bool(PLANNER_UNIFIED_LLM),
            "planner_compact_enabled": bool(QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED),
            "llm_resolution": dict(self._llm_runtime_meta),
        }
        debug_payload = None
        if req.debug:
            debug_payload = self._response_builder.build_debug_payload(
                normalized_prompt=normalized_prompt,
                conversation_id=conversation_id,
                conversation_context_used=context is not None,
                followup_mode=bool(context and context.followup_mode),
                conversation_seeded_from_client=seeded_from_client,
                selected_domain_id=selected_domain_id,
                capabilities=capabilities,
                capabilities_llm=capabilities_llm,
                domain_candidates=_serialize_domain_candidates_for_debug(domain_candidates),
                domain_ranking=ranking_debug,
                rerank_signals=rerank_signals,
                column_shortlist_count=len(shortlisted_columns),
                slot_hints=slot_hints,
                semantic_assist_enabled=QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED,
                semantic_value_alias_constraints=semantic_value_alias_constraints,
                semantic_value_alias_normalization=semantic_alias_debug,
                semantic_grounding=semantic_grounding_debug,
                semester_indicator_columns=semester_indicator_columns,
                slot_raw_json=slots_result.raw_content,
                slot_attempts=slots_result.attempts,
                slot_repaired=slots_result.repaired,
                country_value_normalization=country_debug,
                school_year_value_normalization=school_year_debug,
                semester_value_normalization=semester_debug,
                school_name_filter_normalization=school_name_debug,
                staff_role_filter_normalization=staff_role_debug,
                adm_filter_normalization=adm_default_debug,
                district_county_retry_hint=district_county_retry_hint,
                llm_raw_json=llm_result.raw_content,
                llm_attempts=llm_result.attempts,
                llm_repaired=llm_result.repaired,
                planner_unified_llm=bool(PLANNER_UNIFIED_LLM),
                unified_llm_trace=unified_trace,
                explanation_summary_trace=explanation_summary_trace,
                next_actions_trace=next_actions_trace,
                technical_details=technical_details,
                profile_enabled=profile_enabled,
                pipeline_profile=pipeline_profile_steps,
                trace_capture_enabled=trace_capture_enabled,
                pipeline_trace=pipeline_trace,
            )
        response = self._response_builder.build_plan_response(
            validated=validated,
            sql_json=sql_json,
            explanation=explanation,
            next_actions=next_actions,
            next_actions_status=enrichment.next_actions_status,
            trace_id=trace_id,
            conversation_id=conversation_id,
            fast_mode=fast_mode,
            planner_unified_llm=bool(PLANNER_UNIFIED_LLM),
            planner_compact_enabled=bool(QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED),
            llm_resolution=dict(self._llm_runtime_meta),
            timings=timings,
            unified_trace=unified_trace,
            clarification_question=str(unified_trace.get("clarification_question") or "").strip() or None,
            planner_confidence=float(unified_trace.get("confidence") or 0.0),
            pipeline_profile=(pipeline_profile_steps if req.profile_pipeline else None),
            debug_payload=debug_payload,
        )
        return self._finalization.finalize(
            workspace_id=req.workspace_id,
            user_id=str(user_id),
            vertical_norm=vertical,
            normalized_prompt=normalized_prompt,
            trace_id=trace_id,
            conversation_id=conversation_id,
            plan_json_v2=validated.plan_json,
            sql_json=sql_json,
            profile_steps=pipeline_profile_steps,
            profile_enabled=profile_enabled,
            trace_capture_enabled=trace_capture_enabled,
            pipeline_trace=pipeline_trace,
            timings=timings,
            started_at=t0,
            fast_mode=fast_mode,
            planner_unified_llm=bool(PLANNER_UNIFIED_LLM),
            planner_compact_enabled=bool(QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED),
            response=response,
        )

    def get_pipeline_profile(
        self,
        *,
        trace_id: str,
        workspace_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        token = str(trace_id or "").strip()
        if token == "":
            raise ForgeError("trace_id is required", status_code=400)
        ws = str(workspace_id or "").strip()
        uid = str(user_id or "").strip()
        profile = self._pipeline_trace.get_pipeline_profile(trace_id=token, workspace_id=ws, user_id=uid)
        if profile is None:
            raise ForgeError(
                "Pipeline profile not found",
                status_code=404,
                details={"trace_id": token, "workspace_id": ws, "user_id": uid},
            )
        return profile

    def list_pipeline_profiles(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        return self._pipeline_trace.list_pipeline_profiles(limit=limit)

    def emit_failed_plan_trace(
        self,
        *,
        payload: Mapping[str, Any] | None,
        user_id: str,
        error: Exception,
    ) -> Optional[str]:
        return self._pipeline_trace.emit_failed_plan_trace(payload=payload, user_id=user_id, error=error)

    def generate_next_actions(
        self,
        payload: Dict[str, Any],
        *,
        user_id: str,
    ) -> Dict[str, Any]:
        try:
            req = PlanDomainNextActionsRequest.model_validate(payload or {})
        except ValidationError as exc:
            raise ForgeError("Invalid next actions request", status_code=400, details={"errors": exc.errors()}) from exc
        self._resolve_runtime_llm(
            workspace_id=req.workspace_id,
            role=LLMRole.SUMMARIZER,
            llm_id_override=req.llm_id,
        )

        plan_json = dict(req.plan_json_v2 or {}) if isinstance(req.plan_json_v2, Mapping) else {}
        if not plan_json:
            raise ForgeError("plan_json_v2 is required", status_code=400)

        normalized_prompt = normalize_plan_prompt(req.prompt)
        domain_id = _to_int(req.base_domain_id)
        if domain_id is None:
            domain_id = _to_int(plan_json.get("base_domain_id"))
        if domain_id is None or domain_id <= 0:
            raise ForgeError("base_domain_id is required", status_code=400)

        t0 = perf_counter()
        capabilities = self._capabilities.get_domain_capabilities(
            workspace_id=req.workspace_id,
            user_id=str(user_id),
            domain_id=domain_id,
            vertical_norm=_norm_vertical(req.vertical_norm),
        )
        capabilities_full = DomainSelectionService.full_capabilities_for_execution(capabilities=capabilities)
        selected_domain_name = str(plan_json.get("domain_name") or f"domain_{domain_id}").strip() or f"domain_{domain_id}"
        next_actions, next_actions_trace = self._next_actions.maybe_generate(
            prompt=normalized_prompt,
            selected_domain_id=domain_id,
            selected_domain_name=selected_domain_name,
            plan_json=plan_json,
            capabilities=capabilities_full,
        )
        timing_ms = _elapsed_ms(t0)
        trace_id = str(req.trace_id or uuid.uuid4()).strip() or str(uuid.uuid4())
        conversation_id = str(req.conversation_id or "").strip()
        return {
            "next_actions": next_actions,
            "next_actions_status": "ready",
            "trace_id": trace_id,
            "conversation_id": conversation_id,
            "technical_details": {
                "trace_id": trace_id,
                "conversation_id": conversation_id,
                "llm_resolution": dict(self._llm_runtime_meta),
                "planner_compact_enabled": bool(QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED),
            },
            "timings_ms": {"next_actions": timing_ms},
            "debug": {"next_actions_trace": next_actions_trace} if next_actions_trace else {},
        }


    def _embedding_model(self) -> EmbeddingModel:
        if self._embedding is None:
            self._embedding = EmbeddingModel(model_name=EMBEDDING_MODEL_NAME)
        return self._embedding

    def _column_vector_client(self) -> QdrantClientWrapper:
        if self._column_qdrant is None:
            self._column_qdrant = QdrantClientWrapper(collection_name=QDRANT_COLUMN_COLLECTION_V2)
        return self._column_qdrant

__all__ = ["PlannerDomainService", "normalize_plan_prompt"]
