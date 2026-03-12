from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from logging.handlers import WatchedFileHandler
from time import perf_counter
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from qdrant_client.http import models as qdrant_models

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import (
    EMBEDDING_MODEL_NAME,
    PLANNER_UNIFIED_LLM,
    QDRANT_COLUMN_COLLECTION_V2,
    QF_PLAN_DOMAIN_FAST_MODE_DEFAULT,
    QF_PLAN_DOMAIN_FAST_MODE_MAX_DIMENSIONS,
    QF_PLAN_DOMAIN_FAST_MODE_MAX_FILTER_COLUMNS,
    QF_PLAN_DOMAIN_FAST_MODE_PLAN_MAX_TOKENS,
    QF_PLAN_DOMAIN_FAST_MODE_SLOT_MAX_TOKENS,
    QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED,
    QF_PLAN_DOMAIN_COMPACT_MAX_TOKENS,
    QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED,
    QF_PLAN_DOMAIN_LLM_EXPLANATION_MAX_TOKENS,
    QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED,
    QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_ITEMS,
    QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_TOKENS,
    QF_PLAN_DOMAIN_NEXT_ACTIONS_ASYNC_DEFAULT,
    QF_PLAN_DOMAIN_PIPELINE_TRACE_ENABLED,
    QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE,
    QF_PLAN_DOMAIN_PIPELINE_TRACE_MAX_CHARS,
    QF_PLAN_DOMAIN_PIPELINE_TRACE_MAX_ITEMS,
    QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED,
    QF_PLAN_DOMAIN_TIMING_PROFILE_ENABLED,
    QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE,
    QF_SCHOOL_YEAR_END_MONTH,
    QF_SCHOOL_YEAR_START_MONTH,
    QF_SEMESTER_FALL_END_MONTH,
    QF_SEMESTER_FALL_LABEL,
    QF_SEMESTER_FALL_START_MONTH,
    QF_SEMESTER_SPRING_END_MONTH,
    QF_SEMESTER_SPRING_LABEL,
    QF_SEMESTER_SPRING_START_MONTH,
    QF_SEMESTER_YEAR_ROUND_END_MONTH,
    QF_SEMESTER_YEAR_ROUND_LABEL,
    QF_SEMESTER_YEAR_ROUND_START_MONTH,
    SEMANTIC_PLAN_LLM_MAX_TOKENS,
    SEMANTIC_PLAN_LLM_MODEL,
    SEMANTIC_PLAN_LLM_TIMEOUT_SECONDS,
    VLLM_BASE_URL,
)
from app.exceptions.forge_error import ForgeError
from app.infra.embedding_model import EmbeddingModel
from app.infra.qdrant_client import QdrantClientWrapper
from app.services.domains.capabilities_service import DomainCapabilitiesService
from app.services.domain.domain_time_policy_service import DomainTimePolicyService
from app.services.llm.llm_client import LLMClient
from app.services.llm.prompts_plan_v2 import (
    NEXT_ACTIONS_JSON_SCHEMA,
    SLOT_JSON_SCHEMA,
    build_developer_prompt,
    build_json_repair_prompt,
    build_next_actions_developer_prompt,
    build_next_actions_user_prompt,
    build_slot_developer_prompt,
    build_slot_user_prompt,
    build_system_prompt,
    build_user_prompt,
)
from app.services.planner.unified_llm_planner import build_plan_and_slots
from app.services.planner.compact_planner import build_compact_plan_and_project
from app.services.planner.value_normalizers.country import is_country_iso2_column, normalize_country_values
from app.services.planner.value_normalizers.school_year import is_school_year_column, normalize_school_year_values
from app.services.planner.value_normalizers.semester import is_semester_column, normalize_semester_values
from app.services.planner_domain.conversation_store import (
    HybridPlannerDomainConversationStore,
    PlannerDomainConversationStore,
    build_conversation_state,
    default_conversation_ttl_seconds,
    new_conversation_id,
)
from app.services.planner_domain.map_to_sqljson import map_plan_v2_to_sqljson
from app.services.planner_domain.schema_v2 import plan_v2_json_schema
from app.services.planner_domain.validate_v2 import validate_and_repair_plan_v2
from app.services.semantic.value_alias_resolution_service import ValueAliasResolutionService
from app.services.vector import DomainVectorIndexService

_DANGEROUS_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_LIST_STUDENTS_RE = re.compile(r"\b(show|list|give|display|return|find)\b.*\b(student|students)\b", re.IGNORECASE)
_AGGREGATE_STUDENTS_RE = re.compile(
    r"\b(how many|count|number of|total|sum|average|avg|ratio|rate|percentage|percent)\b.*\b(student|students)\b",
    re.IGNORECASE,
)
_LIST_SCHOOLS_RE = re.compile(r"\b(show|list|give|display|return|find)\b.*\b(school|schools)\b", re.IGNORECASE)
_AGGREGATE_SCHOOLS_RE = re.compile(
    r"\b(how many|count|number of|total|sum|average|avg|ratio|rate|percentage|percent)\b.*\b(school|schools)\b",
    re.IGNORECASE,
)
_SUBGROUP_HINT_RE = re.compile(
    r"\b(black|african american|african-american|hispanic|latino|el|ell|esl|lep|mll)\b",
    re.IGNORECASE,
)
_DISTRICT_LEA_TERM_RE = re.compile(r"\b(district|school district|lea|local education agency)\b", re.IGNORECASE)
_NON_WORD_RE = re.compile(r"[^a-z0-9\s]")
_CITY_STATE_ABBR_RE = re.compile(r",\s*([a-z]{2})\b", re.IGNORECASE)
_STAFF_WORK_HINT_RE = re.compile(
    r"\b(work(s|ed|ing)?|workplace|employed|employment|teach(es|ing)?|teacher|staff|job|principal|assistant\s+principal|counselor|counsellor)\b",
    re.IGNORECASE,
)
_STAFF_ROLE_TITLE_HINT_RE = re.compile(
    r"\b(principal|assistant\s+principal|teacher|counselor|counsellor|coach|librarian|superintendent|nurse|psychologist|social\s+worker|position\s+title|job\s+title|role)\b",
    re.IGNORECASE,
)
_STAFF_ROLE_VALUE_RE = re.compile(
    r"\b(assistant\s+principals?|principals?|teachers?|counselors?|counsellors?|coaches?|librarians?|superintendents?|nurses?|psychologists?|social\s+workers?)\b",
    re.IGNORECASE,
)
_SCHOOL_NAME_HINT_RE = re.compile(
    r"\b(elementary|middle|high|academy|campus|school)\b",
    re.IGNORECASE,
)
_STUDENT_ATTEND_HINT_RE = re.compile(
    r"\b(goes to|attend(s|ed|ing)?|enroll(ed|ment|ing)?|student)\b",
    re.IGNORECASE,
)
_DISCIPLINE_HINT_RE = re.compile(
    r"\b(discipline|incident|suspension|expulsion|referral|behavior|behaviour)\b",
    re.IGNORECASE,
)
_ADM_HINT_RE = re.compile(
    r"\b(adm|average\s+daily\s+membership|base\s+adm|daily\s+membership|normalized\s+adm)\b",
    re.IGNORECASE,
)
_FOLLOWUP_EDIT_HINT_RE = re.compile(
    r"\b(sort(ed)?|order(ed)?|arrange(d)?|add|remove|drop|exclude|include|hide|also|now|then|keep|same)\b",
    re.IGNORECASE,
)
_TOP_BOTTOM_LIMIT_RE = re.compile(r"\b(?P<kind>top|bottom)\s+(?P<limit>\d{1,4})\b", re.IGNORECASE)
_SORT_ONLY_PROMPT_RE = re.compile(
    r"^\s*(also\s+|now\s+|then\s+|please\s+)?(sort|order|arrange)(?:\s+the\s+results)?\s+by\b",
    re.IGNORECASE,
)
_SORT_BY_RE = re.compile(
    r"\b(?:sort|order|arrange)(?:\s+the\s+results)?\s+by\s+(?P<field>[a-z0-9_ \-]+?)(?:\s+(?P<dir>asc|desc|ascending|descending))?\s*$",
    re.IGNORECASE,
)
_NEXT_ACTION_ALLOWED_FILTER_OPS = {
    "=",
    "==",
    "eq",
    "equals",
    "!=",
    "<>",
    "ne",
    "not_equals",
    "in",
    "not_in",
    "contains",
    "like",
    "starts_with",
    "ends_with",
    "gt",
    "gte",
    "lt",
    "lte",
    "is_null",
    "is_not_null",
}
_PIPELINE_PROFILE_HEADER_RE = re.compile(
    r"plan_domain_pipeline\s+trace_id=(?P<trace_id>\S+)\s+workspace_id=(?P<workspace_id>\S+)\s+"
    r"user_id=(?P<user_id>\S+)\s+conversation_id=(?P<conversation_id>\S+)\s+total_ms=(?P<total_ms>\d+)"
)
_PIPELINE_PROFILE_STEP_RE = re.compile(r"^\s*(?P<index>\d+)\.\s+(?P<label>.+):\s+(?P<ms>\d+)ms\s*$")
_PIPELINE_PROFILE_TIMESTAMP_RE = re.compile(r"^(?P<timestamp>\d{4}-\d{2}-\d{2}\s+[0-9:,]+)")
_SEMESTER_BUCKET_CONCEPT_KEYS: Dict[str, set[str]] = {
    "spring": {
        "SEMESTER_SPRING_FLAG",
        "IS_SPRING",
        "IS_SPRING_BLOCK",
    },
    "fall": {
        "SEMESTER_FALL_FLAG",
        "IS_FALL",
        "IS_FALL_BLOCK",
    },
    "year_round": {
        "SEMESTER_YEAR_ROUND_FLAG",
        "IS_YEAR_ROUND",
        "IS_YEAR_ROUND_BLOCK",
    },
}
_STAFF_ROLE_CANONICAL: Dict[str, str] = {
    "assistant principal": "Assistant Principal",
    "assistant principals": "Assistant Principal",
    "principal": "Principal",
    "principals": "Principal",
    "teacher": "Teacher",
    "teachers": "Teacher",
    "counselor": "Counselor",
    "counselors": "Counselor",
    "counsellor": "Counselor",
    "counsellors": "Counselor",
    "coach": "Coach",
    "coaches": "Coach",
    "librarian": "Librarian",
    "librarians": "Librarian",
    "superintendent": "Superintendent",
    "superintendents": "Superintendent",
    "nurse": "Nurse",
    "nurses": "Nurse",
    "psychologist": "Psychologist",
    "psychologists": "Psychologist",
    "social worker": "Social Worker",
    "social workers": "Social Worker",
}
_US_STATE_ABBR = {
    "al",
    "ak",
    "az",
    "ar",
    "ca",
    "co",
    "ct",
    "de",
    "fl",
    "ga",
    "hi",
    "id",
    "il",
    "in",
    "ia",
    "ks",
    "ky",
    "la",
    "me",
    "md",
    "ma",
    "mi",
    "mn",
    "ms",
    "mo",
    "mt",
    "ne",
    "nv",
    "nh",
    "nj",
    "nm",
    "ny",
    "nc",
    "nd",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "vt",
    "va",
    "wa",
    "wv",
    "wi",
    "wy",
}

logger = logging.getLogger(__name__)
_PROFILE_LOGGER_NAME = "planner_domain.pipeline_profile"
_PROFILE_LOGGER_INITIALIZED = False
_TRACE_LOGGER_NAME = "planner_domain.pipeline_trace"
_TRACE_LOGGER_INITIALIZED = False


class PlanDomainRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    conversation_id: Optional[str] = None
    context_seed_plan_json_v2: Optional[Dict[str, Any]] = None
    context_seed_last_prompt: Optional[str] = None
    vertical_norm: str = "generic"
    base_domain_id: Optional[int] = None
    debug: bool = False
    allow_unknown_conversation: bool = False
    profile_pipeline: bool = False
    profile_pipeline_data: bool = False
    fast_mode: Optional[bool] = None
    next_actions_async: Optional[bool] = None

    @field_validator("conversation_id")
    @classmethod
    def _validate_conversation_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip()
        if token == "":
            return None
        if len(token) > 128:
            raise ValueError("conversation_id too long")
        return token


@dataclass(frozen=True)
class LLMPlanResult:
    plan_json: Dict[str, Any]
    raw_content: str
    attempts: int
    repaired: bool


@dataclass(frozen=True)
class SlotExtractionResult:
    payload: Dict[str, Any]
    raw_content: str
    attempts: int
    repaired: bool


@dataclass(frozen=True)
class PlanConversationContext:
    conversation_id: str
    prior_prompt: str
    prior_plan_json_v2: Dict[str, Any]
    prior_vertical_norm: str
    followup_mode: bool
    seeded_from_client: bool


class PlanDomainNextActionsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    plan_json_v2: Dict[str, Any]
    vertical_norm: str = "generic"
    base_domain_id: Optional[int] = None
    conversation_id: Optional[str] = None
    trace_id: Optional[str] = None

    @field_validator("conversation_id")
    @classmethod
    def _validate_conversation_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip()
        if token == "":
            return None
        if len(token) > 128:
            raise ValueError("conversation_id too long")
        return token


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
        domain_time_policy_service: Optional[DomainTimePolicyService] = None,
        conversation_store: Optional[PlannerDomainConversationStore] = None,
        conversation_ttl_seconds: Optional[int] = None,
    ) -> None:
        self._capabilities = capabilities_service or DomainCapabilitiesService()
        self._domain_vector = domain_vector_service or DomainVectorIndexService()
        self._llm = llm_client or LLMClient(
            endpoint=VLLM_BASE_URL,
            model=SEMANTIC_PLAN_LLM_MODEL,
            timeout_seconds=SEMANTIC_PLAN_LLM_TIMEOUT_SECONDS,
        )
        self._embedding = embedding_model
        self._column_qdrant = column_qdrant
        self._value_alias_resolver_svc = value_alias_resolver
        self._domain_time_policy = domain_time_policy_service or DomainTimePolicyService()
        self._conversation_store = conversation_store or HybridPlannerDomainConversationStore()
        self._conversation_ttl_seconds = max(60, int(conversation_ttl_seconds or default_conversation_ttl_seconds()))

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
        domain_candidates = self._get_domain_candidates(
            workspace_id=req.workspace_id,
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
                "domain_candidates": domain_candidates,
            },
        )

        t_caps = perf_counter()
        selected_domain_id, capabilities, shortlisted_columns, ranking_debug = self._select_domain_and_shortlist_columns(
            workspace_id=req.workspace_id,
            user_id=str(user_id),
            vertical_norm=vertical,
            prompt=normalized_prompt,
            domain_candidates=domain_candidates,
        )
        capabilities_full = self._full_capabilities_for_execution(capabilities)
        semester_indicator_columns = self._resolve_semester_indicator_columns(
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
        semantic_value_alias_constraints = self._semantic_value_alias_constraints(
            prompt=normalized_prompt,
            vertical_norm=vertical,
        )
        unified_trace: Dict[str, Any] = {}
        schema = plan_v2_json_schema()

        def _run_legacy_llm_path() -> Tuple[SlotExtractionResult, Dict[str, Any], Dict[str, Any], LLMPlanResult]:
            t_slots_local = perf_counter()
            slots_local = self._call_llm_slots(
                normalized_prompt=normalized_prompt,
                workspace_id=req.workspace_id,
                vertical_norm=vertical,
                base_domain_id=selected_domain_id,
                conversation_context=context,
                fast_mode=fast_mode,
            )
            slot_hints_local = self._merge_slot_hints(
                prompt=normalized_prompt,
                slot_payload=slots_local.payload,
                semantic_constraints=semantic_value_alias_constraints,
            )
            timings["llm_slots"] = _add_pipeline_step(
                profile_steps=pipeline_profile_steps,
                enabled=profile_enabled,
                step="llm_slots",
                label="Extract intent/constraints slot hints via LLM",
                started_at=t_slots_local,
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="llm_slots",
                data={
                    "slot_hints": slot_hints_local,
                    "slot_raw_json": slots_local.raw_content,
                    "slot_attempts": slots_local.attempts,
                    "slot_repaired": slots_local.repaired,
                },
            )
            t_caps_compact_local = perf_counter()
            capabilities_llm_local = self._compact_capabilities_for_llm(
                capabilities=capabilities,
                shortlisted_columns=shortlisted_columns,
                prompt=normalized_prompt,
                slot_hints=slot_hints_local,
                fast_mode=fast_mode,
            )
            _add_pipeline_step(
                profile_steps=pipeline_profile_steps,
                enabled=profile_enabled,
                step="capabilities_compaction",
                label="Compact capabilities payload for plan generation",
                started_at=t_caps_compact_local,
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="capabilities_compaction",
                data={
                    "capabilities_llm_summary": _capabilities_summary(capabilities_llm_local),
                    "capabilities_llm": capabilities_llm_local,
                },
            )
            t_llm_local = perf_counter()
            llm_local = self._call_llm_plan(
                normalized_prompt=normalized_prompt,
                workspace_id=req.workspace_id,
                vertical_norm=vertical,
                base_domain_id=selected_domain_id,
                capabilities=capabilities_llm_local,
                schema=schema,
                slot_hints=slot_hints_local,
                conversation_context=context,
                fast_mode=fast_mode,
            )
            timings["llm"] = _add_pipeline_step(
                profile_steps=pipeline_profile_steps,
                enabled=profile_enabled,
                step="llm_plan",
                label="Generate PlanV2 with LLM",
                started_at=t_llm_local,
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="llm_plan",
                data={
                    "llm_raw_json": llm_local.raw_content,
                    "llm_attempts": llm_local.attempts,
                    "llm_repaired": llm_local.repaired,
                },
            )
            return slots_local, slot_hints_local, capabilities_llm_local, llm_local

        if PLANNER_UNIFIED_LLM:
            t_caps_compact = perf_counter()
            capabilities_llm = self._compact_capabilities_for_llm(
                capabilities=capabilities,
                shortlisted_columns=shortlisted_columns,
                prompt=normalized_prompt,
                slot_hints=None,
                fast_mode=fast_mode,
            )
            _add_pipeline_step(
                profile_steps=pipeline_profile_steps,
                enabled=profile_enabled,
                step="capabilities_compaction",
                label="Compact capabilities payload for plan generation",
                started_at=t_caps_compact,
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="capabilities_compaction",
                data={
                    "capabilities_llm_summary": _capabilities_summary(capabilities_llm),
                    "capabilities_llm": capabilities_llm,
                },
            )
            t_llm = perf_counter()
            try:
                unified_result = self._call_llm_unified(
                    prompt=req.prompt,
                    normalized_prompt=normalized_prompt,
                    workspace_id=req.workspace_id,
                    vertical_norm=vertical,
                    base_domain_id=selected_domain_id,
                    domain_name=selected_domain_name,
                    capabilities=capabilities_llm,
                    conversation_context=context,
                    trace_id=trace_id,
                    fast_mode=fast_mode,
                )
                slot_hints = self._merge_slot_hints(
                    prompt=normalized_prompt,
                    slot_payload=unified_result.get("slot_hints") if isinstance(unified_result.get("slot_hints"), Mapping) else {},
                    semantic_constraints=semantic_value_alias_constraints,
                )
                llm_result = LLMPlanResult(
                    plan_json=dict(unified_result.get("plan_json_v2") or {}),
                    raw_content=str(unified_result.get("llm_raw_json") or ""),
                    attempts=max(1, _to_int(unified_result.get("attempts")) or 1),
                    repaired=bool(unified_result.get("repaired")),
                )
                slots_result = SlotExtractionResult(
                    payload=dict(unified_result.get("slot_hints") or {}),
                    raw_content=str(unified_result.get("llm_raw_json") or ""),
                    attempts=max(1, _to_int(unified_result.get("attempts")) or 1),
                    repaired=bool(unified_result.get("repaired")),
                )
                unified_trace = {
                    "llm_model": str(unified_result.get("llm_model") or ""),
                    "llm_tokens": dict(unified_result.get("llm_tokens") or {}),
                }
                if str(unified_result.get("planner_mode") or "").strip():
                    unified_trace["planner_mode"] = str(unified_result.get("planner_mode") or "").strip()
                if "finish_reason" in unified_result:
                    unified_trace["finish_reason"] = unified_result.get("finish_reason")
                if "candidate_summary" in unified_result:
                    unified_trace["candidate_summary"] = unified_result.get("candidate_summary")
                if "validation_warnings" in unified_result:
                    unified_trace["validation_warnings"] = unified_result.get("validation_warnings")
                if "llm_prompt_trace" in unified_result:
                    unified_trace["llm_prompt_trace"] = unified_result.get("llm_prompt_trace")
                if "needs_clarification" in unified_result:
                    unified_trace["needs_clarification"] = bool(unified_result.get("needs_clarification"))
                    unified_trace["clarification_question"] = unified_result.get("clarification_question")
                    unified_trace["confidence"] = unified_result.get("confidence")
                if "explanation_draft" in unified_result:
                    unified_trace["explanation_draft"] = unified_result.get("explanation_draft")
                timings["llm"] = _add_pipeline_step(
                    profile_steps=pipeline_profile_steps,
                    enabled=profile_enabled,
                    step="llm_unified",
                    label="Generate slots+plan with LLM (unified)",
                    started_at=t_llm,
                )
                _append_pipeline_trace_step(
                    trace=pipeline_trace,
                    enabled=trace_capture_enabled,
                    step="llm_unified",
                    data={
                        "slot_hints": dict(unified_result.get("slot_hints") or {}),
                        "llm_model": str(unified_result.get("llm_model") or ""),
                        "llm_tokens": dict(unified_result.get("llm_tokens") or {}),
                        "finish_reason": unified_result.get("finish_reason"),
                        "attempts": unified_result.get("attempts"),
                        "repaired": unified_result.get("repaired"),
                        "candidate_summary": unified_result.get("candidate_summary"),
                        "validation_warnings": unified_result.get("validation_warnings"),
                        "llm_prompt_trace": unified_result.get("llm_prompt_trace"),
                    },
                )
            except ForgeError as exc:
                err_msg = str(exc.message or "").strip().lower()
                should_fallback = (
                    "unified invalid model json" in err_msg
                    or "planner_compact_truncation" in err_msg
                    or "planner_compact_invalid_response" in err_msg
                )
                if not should_fallback:
                    raise
                _add_pipeline_step(
                    profile_steps=pipeline_profile_steps,
                    enabled=profile_enabled,
                    step="llm_unified",
                    label="Generate slots+plan with LLM (unified)",
                    started_at=t_llm,
                )
                unified_trace = {
                    "fallback_to_legacy_llm_path": True,
                    "fallback_reason": str(exc.message or "unified_llm_failed"),
                    "fallback_details": dict(exc.details or {}),
                }
                _append_pipeline_trace_step(
                    trace=pipeline_trace,
                    enabled=trace_capture_enabled,
                    step="llm_unified_fallback",
                    data=unified_trace,
                )
                slots_result, slot_hints, capabilities_llm, llm_result = _run_legacy_llm_path()
        else:
            slots_result, slot_hints, capabilities_llm, llm_result = _run_legacy_llm_path()

        t_plan_normalize = perf_counter()
        llm_plan = self._normalize_llm_plan(
            raw_plan=llm_result.plan_json,
            trace_id=trace_id,
            workspace_id=req.workspace_id,
            vertical_norm=vertical,
            base_domain_id=selected_domain_id,
            base_domain_name=selected_domain_name,
        )
        llm_plan = _merge_followup_plan_with_context(
            prompt=normalized_prompt,
            candidate_plan=llm_plan,
            prior_plan=(context.prior_plan_json_v2 if context is not None and context.followup_mode else None),
            capabilities=capabilities_full,
        )
        llm_plan, country_issues, country_debug = _normalize_country_filters_in_plan(
            plan_json=llm_plan,
            capabilities=capabilities_full,
        )
        llm_plan, school_year_issues, school_year_debug = _normalize_school_year_filters_in_plan(
            plan_json=llm_plan,
            capabilities=capabilities_full,
        )
        llm_plan, year_keyword_issues, year_keyword_debug = _normalize_year_keyword_filters_in_plan(
            plan_json=llm_plan,
            capabilities=capabilities_full,
        )
        _ = year_keyword_debug
        llm_plan, semester_issues, semester_debug = _normalize_semester_filters_in_plan(
            plan_json=llm_plan,
            capabilities=capabilities_full,
            semester_indicator_columns=semester_indicator_columns,
        )
        llm_plan, school_name_issues, school_name_debug = _normalize_school_name_filters_in_plan(
            plan_json=llm_plan,
            capabilities=capabilities_full,
            prompt=normalized_prompt,
        )
        llm_plan, staff_role_issues, staff_role_debug = _normalize_staff_role_filters_in_plan(
            plan_json=llm_plan,
            capabilities=capabilities_full,
            prompt=normalized_prompt,
        )
        llm_plan, adm_default_issues, adm_default_debug = _normalize_adm_default_filters_in_plan(
            plan_json=llm_plan,
            capabilities=capabilities_full,
            prompt=normalized_prompt,
        )
        llm_plan, relative_time_issues, _ = _normalize_relative_time_in_plan(
            plan_json=llm_plan,
            capabilities=capabilities_full,
            prompt=normalized_prompt,
            domain_time_policy=domain_time_policy,
        )
        llm_plan, top_bottom_issues, _ = _normalize_top_bottom_ranking_in_plan(
            plan_json=llm_plan,
            capabilities=capabilities_full,
            prompt=normalized_prompt,
        )
        normalization_issues = (
            country_issues
            + school_year_issues
            + year_keyword_issues
            + semester_issues
            + school_name_issues
            + staff_role_issues
            + adm_default_issues
            + relative_time_issues
            + top_bottom_issues
        )
        _add_pipeline_step(
            profile_steps=pipeline_profile_steps,
            enabled=profile_enabled,
            step="plan_normalization",
            label="Normalize plan and apply deterministic value/filter normalizers",
            started_at=t_plan_normalize,
        )
        _append_pipeline_trace_step(
            trace=pipeline_trace,
            enabled=trace_capture_enabled,
            step="plan_normalization",
            data={
                "normalized_plan_json_v2": llm_plan,
                "normalization_issues": normalization_issues,
            },
        )

        t_validate = perf_counter()
        validated = validate_and_repair_plan_v2(
            plan_json=llm_plan,
            capabilities=capabilities_full,
            prompt=normalized_prompt,
            expected_base_domain_id=selected_domain_id,
            extra_issues=normalization_issues,
        )
        timings["validation"] = _add_pipeline_step(
            profile_steps=pipeline_profile_steps,
            enabled=profile_enabled,
            step="validation",
            label="Validate and repair plan against capabilities",
            started_at=t_validate,
        )
        _append_pipeline_trace_step(
            trace=pipeline_trace,
            enabled=trace_capture_enabled,
            step="validation",
            data={
                "is_valid": validated.is_valid,
                "issues": validated.issues,
                "repairs_applied": validated.repairs_applied,
                "validated_plan_json_v2": validated.plan_json,
            },
        )

        district_county_retry_hint = _district_county_retry_hint(
            normalized_prompt=normalized_prompt,
            plan_json=llm_plan,
            capabilities=capabilities_full,
        )
        retry_needed = (
            (not validated.is_valid and (_should_retry_after_validation(validated.issues) or fast_mode))
            or (not fast_mode and bool(district_county_retry_hint))
        )
        if retry_needed:
            t_llm_retry = perf_counter()
            retry_feedback = _format_validation_feedback(validated.issues)
            llm_retry = self._call_llm_plan(
                normalized_prompt=normalized_prompt,
                workspace_id=req.workspace_id,
                vertical_norm=vertical,
                base_domain_id=selected_domain_id,
                capabilities=capabilities_llm,
                schema=schema,
                slot_hints=slot_hints,
                validation_feedback=retry_feedback,
                retry_hint=district_county_retry_hint or "",
                conversation_context=context,
                fast_mode=fast_mode,
            )
            timings["llm_retry"] = _add_pipeline_step(
                profile_steps=pipeline_profile_steps,
                enabled=profile_enabled,
                step="llm_retry",
                label="Retry PlanV2 generation after validation feedback",
                started_at=t_llm_retry,
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="llm_retry",
                data={
                    "validation_feedback": retry_feedback,
                    "llm_raw_json": llm_retry.raw_content,
                    "llm_attempts": llm_retry.attempts,
                    "llm_repaired": llm_retry.repaired,
                },
            )

            t_retry_normalize = perf_counter()
            retry_plan = self._normalize_llm_plan(
                raw_plan=llm_retry.plan_json,
                trace_id=trace_id,
                workspace_id=req.workspace_id,
                vertical_norm=vertical,
                base_domain_id=selected_domain_id,
                base_domain_name=selected_domain_name,
            )
            retry_plan = _merge_followup_plan_with_context(
                prompt=normalized_prompt,
                candidate_plan=retry_plan,
                prior_plan=(context.prior_plan_json_v2 if context is not None and context.followup_mode else None),
                capabilities=capabilities_full,
            )
            retry_plan, retry_country_issues, retry_country_debug = _normalize_country_filters_in_plan(
                plan_json=retry_plan,
                capabilities=capabilities_full,
            )
            retry_plan, retry_school_year_issues, retry_school_year_debug = _normalize_school_year_filters_in_plan(
                plan_json=retry_plan,
                capabilities=capabilities_full,
            )
            retry_plan, retry_year_keyword_issues, retry_year_keyword_debug = _normalize_year_keyword_filters_in_plan(
                plan_json=retry_plan,
                capabilities=capabilities_full,
            )
            retry_plan, retry_semester_issues, retry_semester_debug = _normalize_semester_filters_in_plan(
                plan_json=retry_plan,
                capabilities=capabilities_full,
                semester_indicator_columns=semester_indicator_columns,
            )
            retry_plan, retry_school_name_issues, retry_school_name_debug = _normalize_school_name_filters_in_plan(
                plan_json=retry_plan,
                capabilities=capabilities_full,
                prompt=normalized_prompt,
            )
            retry_plan, retry_staff_role_issues, retry_staff_role_debug = _normalize_staff_role_filters_in_plan(
                plan_json=retry_plan,
                capabilities=capabilities_full,
                prompt=normalized_prompt,
            )
            retry_plan, retry_adm_default_issues, retry_adm_default_debug = _normalize_adm_default_filters_in_plan(
                plan_json=retry_plan,
                capabilities=capabilities_full,
                prompt=normalized_prompt,
            )
            retry_plan, retry_relative_time_issues, _ = _normalize_relative_time_in_plan(
                plan_json=retry_plan,
                capabilities=capabilities_full,
                prompt=normalized_prompt,
                domain_time_policy=domain_time_policy,
            )
            retry_plan, retry_top_bottom_issues, _ = _normalize_top_bottom_ranking_in_plan(
                plan_json=retry_plan,
                capabilities=capabilities_full,
                prompt=normalized_prompt,
            )
            retry_normalization_issues = (
                retry_country_issues
                + retry_school_year_issues
                + retry_year_keyword_issues
                + retry_semester_issues
                + retry_school_name_issues
                + retry_staff_role_issues
                + retry_adm_default_issues
                + retry_relative_time_issues
                + retry_top_bottom_issues
            )
            _add_pipeline_step(
                profile_steps=pipeline_profile_steps,
                enabled=profile_enabled,
                step="retry_plan_normalization",
                label="Normalize retry plan and re-apply deterministic normalizers",
                started_at=t_retry_normalize,
            )
            t_validate_retry = perf_counter()
            validated = validate_and_repair_plan_v2(
                plan_json=retry_plan,
                capabilities=capabilities_full,
                prompt=normalized_prompt,
                expected_base_domain_id=selected_domain_id,
                extra_issues=retry_normalization_issues,
            )
            timings["validation_retry"] = _add_pipeline_step(
                profile_steps=pipeline_profile_steps,
                enabled=profile_enabled,
                step="validation_retry",
                label="Validate and repair retry plan",
                started_at=t_validate_retry,
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="validation_retry",
                data={
                    "is_valid": validated.is_valid,
                    "issues": validated.issues,
                    "repairs_applied": validated.repairs_applied,
                    "validated_plan_json_v2": validated.plan_json,
                },
            )
            llm_result = llm_retry
            country_debug = retry_country_debug
            school_year_debug = retry_school_year_debug
            _ = retry_year_keyword_debug
            semester_debug = retry_semester_debug
            school_name_debug = retry_school_name_debug
            staff_role_debug = retry_staff_role_debug
            adm_default_debug = retry_adm_default_debug

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

        t_explanation = perf_counter()
        explanation = _build_plan_explanation(
            selected_domain_id=selected_domain_id,
            plan_json=validated.plan_json,
            capabilities=capabilities_full,
            domain_candidates=domain_candidates,
            ranking_debug=ranking_debug,
            shortlisted_columns=shortlisted_columns,
            country_debug=country_debug,
            school_year_debug=school_year_debug,
            semester_debug=semester_debug,
        )
        _add_pipeline_step(
            profile_steps=pipeline_profile_steps,
            enabled=profile_enabled,
            step="explanation_build",
            label="Build deterministic explanation object",
            started_at=t_explanation,
        )
        t_explanation_polish = perf_counter()
        explanation, explanation_summary_trace = self._maybe_polish_explanation_summary(
            prompt=normalized_prompt,
            explanation=explanation,
        )
        _add_pipeline_step(
            profile_steps=pipeline_profile_steps,
            enabled=profile_enabled,
            step="explanation_polish",
            label="Optionally polish explanation summary with LLM",
            started_at=t_explanation_polish,
        )
        _append_pipeline_trace_step(
            trace=pipeline_trace,
            enabled=trace_capture_enabled,
            step="explanation",
            data={
                "explanation": explanation,
                "explanation_summary_trace": explanation_summary_trace,
            },
        )
        next_actions_async = (
            bool(req.next_actions_async)
            if req.next_actions_async is not None
            else bool(QF_PLAN_DOMAIN_NEXT_ACTIONS_ASYNC_DEFAULT)
        )
        if next_actions_async:
            next_actions = []
            next_actions_trace = {"enabled": True, "used": False, "deferred": True}
            _add_pipeline_step(
                profile_steps=pipeline_profile_steps,
                enabled=profile_enabled,
                step="next_actions",
                label="Defer next action generation (async)",
                started_at=perf_counter(),
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="next_actions",
                data={"status": "deferred"},
            )
        else:
            t_next_actions = perf_counter()
            next_actions, next_actions_trace = self._maybe_generate_next_actions(
                prompt=normalized_prompt,
                selected_domain_id=selected_domain_id,
                selected_domain_name=str(validated.plan_json.get("domain_name") or "").strip()
                or selected_domain_name,
                plan_json=validated.plan_json,
                capabilities=capabilities_full,
            )
            _add_pipeline_step(
                profile_steps=pipeline_profile_steps,
                enabled=profile_enabled,
                step="next_actions",
                label="Generate in-domain next action suggestions",
                started_at=t_next_actions,
            )
            _append_pipeline_trace_step(
                trace=pipeline_trace,
                enabled=trace_capture_enabled,
                step="next_actions",
                data={
                    "status": "ready",
                    "next_actions": next_actions,
                    "next_actions_trace": next_actions_trace,
                },
            )

        response: Dict[str, Any] = {
            "plan_json_v2": validated.plan_json,
            "sql_json": sql_json,
            "validation": {
                "is_valid": validated.is_valid,
                "errors": validated.issues,
                "repairs_applied": validated.repairs_applied,
            },
            "explanation": explanation,
            "next_actions": next_actions,
            "next_actions_status": "deferred" if next_actions_async else "ready",
            "trace_id": trace_id,
            "conversation_id": conversation_id,
            "technical_details": {
                "trace_id": trace_id,
                "conversation_id": conversation_id,
                "fast_mode": fast_mode,
                "planner_unified_llm": bool(PLANNER_UNIFIED_LLM),
            },
            "timings_ms": timings,
        }
        if bool(unified_trace.get("needs_clarification")):
            response["needs_clarification"] = True
            response["clarification_question"] = str(unified_trace.get("clarification_question") or "").strip() or None
            response["planner_confidence"] = float(unified_trace.get("confidence") or 0.0)
        if req.profile_pipeline:
            response["pipeline_profile"] = pipeline_profile_steps
        if req.debug:
            response["debug"] = {
                "normalized_prompt": normalized_prompt,
                "conversation_id": conversation_id,
                "conversation_context_used": context is not None,
                "followup_mode": bool(context and context.followup_mode),
                "conversation_seeded_from_client": seeded_from_client,
                "selected_domain_id": selected_domain_id,
                "capabilities": capabilities,
                "capabilities_llm": capabilities_llm,
                "domain_candidates": domain_candidates,
                "domain_ranking": ranking_debug,
                "column_shortlist_count": len(shortlisted_columns),
                "slot_hints": slot_hints,
                "semantic_assist_enabled": QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED,
                "semantic_value_alias_constraints": semantic_value_alias_constraints,
                "semester_indicator_columns": semester_indicator_columns,
                "slot_raw_json": slots_result.raw_content,
                "slot_attempts": slots_result.attempts,
                "slot_repaired": slots_result.repaired,
                "country_value_normalization": country_debug,
                "school_year_value_normalization": school_year_debug,
                "semester_value_normalization": semester_debug,
                "school_name_filter_normalization": school_name_debug,
                "staff_role_filter_normalization": staff_role_debug,
                "adm_filter_normalization": adm_default_debug,
                "district_county_retry_hint": district_county_retry_hint,
                "llm_raw_json": llm_result.raw_content,
                "llm_attempts": llm_result.attempts,
                "llm_repaired": llm_result.repaired,
                "planner_unified_llm": bool(PLANNER_UNIFIED_LLM),
                "unified_llm_trace": unified_trace,
                "explanation_summary_trace": explanation_summary_trace,
                "next_actions_trace": next_actions_trace,
                "technical_details": {
                    "trace_id": trace_id,
                    "conversation_id": conversation_id,
                    "fast_mode": fast_mode,
                    "planner_unified_llm": bool(PLANNER_UNIFIED_LLM),
                },
            }
            if profile_enabled:
                response["debug"]["pipeline_profile"] = pipeline_profile_steps
            if trace_capture_enabled:
                response["debug"]["pipeline_trace"] = _sanitize_pipeline_trace_value(pipeline_trace)
        state = build_conversation_state(
            workspace_id=req.workspace_id,
            user_id=str(user_id),
            vertical_norm=vertical,
            prompt=normalized_prompt,
            trace_id=trace_id,
            plan_json_v2=validated.plan_json,
            sql_json=sql_json,
        )
        t_state_save = perf_counter()
        try:
            self._conversation_store.save_state(
                workspace_id=req.workspace_id,
                user_id=str(user_id),
                conversation_id=conversation_id,
                state=state,
                qf_ttl_seconds=self._conversation_ttl_seconds,
            )
        except Exception as exc:
            logger.warning("planner_domain conversation save failed conversation_id=%s err=%s", conversation_id, exc)

        _add_pipeline_step(
            profile_steps=pipeline_profile_steps,
            enabled=profile_enabled,
            step="conversation_state_save",
            label="Persist conversation state for follow-up context",
            started_at=t_state_save,
        )
        timings["total"] = _elapsed_ms(t0)
        _emit_pipeline_profile_log(
            enabled=profile_enabled,
            trace_id=trace_id,
            workspace_id=req.workspace_id,
            user_id=str(user_id),
            conversation_id=conversation_id,
            prompt=normalized_prompt,
            total_ms=int(timings.get("total") or 0),
            steps=pipeline_profile_steps,
        )
        _emit_pipeline_trace_log(
            enabled=trace_capture_enabled,
            trace_payload={
                **pipeline_trace,
                "timings_ms": dict(timings),
                "technical_details": {
                    "trace_id": trace_id,
                    "conversation_id": conversation_id,
                    "fast_mode": fast_mode,
                    "planner_unified_llm": bool(PLANNER_UNIFIED_LLM),
                },
            },
        )
        if trace_capture_enabled:
            response["technical_details"]["pipeline_trace_enabled"] = True
            response["technical_details"]["pipeline_trace_log_file"] = _resolve_plan_domain_log_path(
                str(QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE or ""),
                "logs/plan_domain_pipeline_trace.jsonl",
            )
        return response

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
        profile = _read_pipeline_profile_from_log(
            trace_id=token,
            workspace_id=str(workspace_id or "").strip(),
            user_id=str(user_id or "").strip(),
        )
        pipeline_trace = _read_pipeline_trace_from_log(
            trace_id=token,
            workspace_id=str(workspace_id or "").strip(),
            user_id=str(user_id or "").strip(),
        )
        if pipeline_trace is not None:
            profile["pipeline_trace"] = pipeline_trace
        return profile

    def list_pipeline_profiles(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        return _list_pipeline_profiles_from_log(limit=limit)

    def emit_failed_plan_trace(
        self,
        *,
        payload: Mapping[str, Any] | None,
        user_id: str,
        error: Exception,
    ) -> Optional[str]:
        body = dict(payload or {}) if isinstance(payload, Mapping) else {}
        enabled = bool(
            QF_PLAN_DOMAIN_PIPELINE_TRACE_ENABLED
            or bool(body.get("profile_pipeline_data"))
            or bool(body.get("profile_pipeline"))
        )
        if not enabled:
            return None

        error_details: Dict[str, Any] = {}
        status_code = 500
        error_message = str(error)
        if isinstance(error, ForgeError):
            status_code = int(error.status_code or 500)
            error_message = str(error.message or error_message or "plan_domain failed")
            if isinstance(error.details, Mapping):
                error_details = dict(error.details)

        trace_id = str(error_details.get("trace_id") or uuid.uuid4())
        trace_payload: Dict[str, Any] = {
            "trace_id": trace_id,
            "workspace_id": str(body.get("workspace_id") or ""),
            "user_id": str(user_id or ""),
            "conversation_id": str(body.get("conversation_id") or ""),
            "prompt": str(body.get("prompt") or ""),
            "fast_mode": bool(body.get("fast_mode")) if body.get("fast_mode") is not None else bool(QF_PLAN_DOMAIN_FAST_MODE_DEFAULT),
            "planner_unified_llm": bool(PLANNER_UNIFIED_LLM),
            "failed": True,
            "steps": [
                {
                    "step": "plan_failed",
                    "data": {
                        "error_type": error.__class__.__name__,
                        "error_message": error_message,
                        "status_code": status_code,
                        "error_details": error_details,
                        "request_context": {
                            "workspace_id": str(body.get("workspace_id") or ""),
                            "conversation_id": str(body.get("conversation_id") or ""),
                            "vertical_norm": str(body.get("vertical_norm") or ""),
                            "base_domain_id": body.get("base_domain_id"),
                            "profile_pipeline": bool(body.get("profile_pipeline")),
                            "profile_pipeline_data": bool(body.get("profile_pipeline_data")),
                            "next_actions_async": bool(body.get("next_actions_async")),
                        },
                    },
                }
            ],
        }
        _emit_pipeline_trace_log(enabled=True, trace_payload=trace_payload)
        return trace_id

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
        capabilities_full = self._full_capabilities_for_execution(capabilities=capabilities)
        selected_domain_name = str(plan_json.get("domain_name") or f"domain_{domain_id}").strip() or f"domain_{domain_id}"
        next_actions, next_actions_trace = self._maybe_generate_next_actions(
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
            },
            "timings_ms": {"next_actions": timing_ms},
            "debug": {"next_actions_trace": next_actions_trace} if next_actions_trace else {},
        }

    def _get_domain_candidates(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        prompt: str,
        provided_domain_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        provided = _to_int(provided_domain_id)
        if provided is not None and provided > 0:
            return [{"domain_id": provided, "name": f"domain_{provided}", "score": 1.0, "source": "provided"}]

        query_texts = _build_domain_query_texts(prompt)
        rows: List[Dict[str, Any]] = []
        for query_text in query_texts:
            result = self._domain_vector.search_domains(
                workspace_id=workspace_id,
                query=query_text,
                vertical_norm=vertical_norm,
                limit=6,
                score_threshold=0.0,
                include_payload=False,
            )
            rows.extend(row for row in list(result.get("results") or []) if isinstance(row, dict))
        out: List[Dict[str, Any]] = []
        by_domain: Dict[int, Dict[str, Any]] = {}
        seen: set[int] = set()
        for row in rows:
            domain_id = _to_int(row.get("domain_id"))
            if domain_id is None:
                continue
            current_score = float(row.get("score") or 0.0)
            existing = by_domain.get(domain_id)
            if existing is None:
                by_domain[domain_id] = {
                    "domain_id": domain_id,
                    "name": str(row.get("name") or f"domain_{domain_id}"),
                    "score": current_score,
                    "reason": list(row.get("reason") or []),
                    "source": "vector",
                }
                continue
            existing_reasons = list(existing.get("reason") or [])
            new_reasons = list(row.get("reason") or [])
            existing["reason"] = _dedupe_text_items(existing_reasons + new_reasons)
            if current_score > float(existing.get("score") or 0.0):
                existing["score"] = current_score
                existing["name"] = str(row.get("name") or existing.get("name") or f"domain_{domain_id}")
        for domain_id, row in by_domain.items():
            if domain_id in seen:
                continue
            seen.add(domain_id)
            out.append(dict(row))
        out.sort(key=lambda item: (-float(item.get("score") or 0.0), int(item.get("domain_id") or 0)))
        out = out[:6]
        if not out:
            raise ForgeError("No candidate domain found for prompt", status_code=404)
        return out

    def _select_domain_and_shortlist_columns(
        self,
        *,
        workspace_id: str,
        user_id: str,
        vertical_norm: str,
        prompt: str,
        domain_candidates: Sequence[Mapping[str, Any]],
    ) -> Tuple[int, Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        ranking: List[Dict[str, Any]] = []
        best_row: Optional[Dict[str, Any]] = None
        first_error: Optional[ForgeError] = None

        for candidate in list(domain_candidates or [])[:3]:
            domain_id = _to_int(candidate.get("domain_id"))
            if domain_id is None:
                continue
            try:
                capabilities = self._capabilities.get_domain_capabilities(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    domain_id=domain_id,
                    vertical_norm=vertical_norm,
                )
            except ForgeError as exc:
                if first_error is None:
                    first_error = exc
                ranking.append({"domain_id": domain_id, "status": "error", "error": str(exc), "score": 0.0})
                continue

            shortlist = self._shortlist_columns_for_domain(
                prompt=prompt,
                workspace_id=workspace_id,
                capabilities=capabilities,
            )
            score = self._score_domain_candidate(
                prompt=prompt,
                candidate=candidate,
                capabilities=capabilities,
                shortlisted_columns=shortlist,
            )
            row = {
                "domain_id": domain_id,
                "score": score,
                "vector_score": float(candidate.get("score") or 0.0),
                "column_shortlist_count": len(shortlist),
                "dimension_count": len(list(capabilities.get("dimensions") or [])),
                "source": str(candidate.get("source") or "vector"),
                "capabilities": capabilities,
                "shortlisted_columns": shortlist,
            }
            ranking.append({k: v for k, v in row.items() if k not in {"capabilities", "shortlisted_columns"}})
            if best_row is None or float(row["score"]) > float(best_row["score"]):
                best_row = row

        if best_row is None:
            if first_error is not None:
                raise first_error
            raise ForgeError("No accessible domain candidates found", status_code=404)

        return (
            int(best_row["domain_id"]),
            dict(best_row["capabilities"]),
            list(best_row["shortlisted_columns"]),
            ranking,
        )

    def _score_domain_candidate(
        self,
        *,
        prompt: str,
        candidate: Mapping[str, Any],
        capabilities: Mapping[str, Any],
        shortlisted_columns: Sequence[Mapping[str, Any]],
    ) -> float:
        vector_score = max(0.0, float(candidate.get("score") or 0.0))
        dimension_count = max(1, len(list(capabilities.get("dimensions") or [])))
        shortlist_ratio = min(1.0, len(list(shortlisted_columns)) / float(min(70, dimension_count)))
        score = (vector_score * 0.65) + (shortlist_ratio * 0.35)

        if _prompt_has_subgroup(prompt) and _has_subgroup_column(shortlisted_columns):
            score += 0.15
        if _looks_like_list_students_prompt(prompt) and _has_student_identity_column(shortlisted_columns):
            score += 0.08
        if _prompt_implies_staff_work_context(prompt) and _has_staff_identity_column(shortlisted_columns):
            score += 0.14
        if _prompt_implies_student_school_context(prompt) and _has_student_identity_column(shortlisted_columns):
            score += 0.12
        if _prompt_has_adm_intent(prompt):
            if _has_adm_signal_columns(shortlisted_columns):
                score += 0.2
            if _has_adm_metric(capabilities):
                score += 0.12
        score += _domain_name_intent_bias(prompt=prompt, candidate=candidate)
        if len(shortlisted_columns) < 5:
            score -= 0.1
        return round(score, 5)

    def _shortlist_columns_for_domain(
        self,
        *,
        prompt: str,
        workspace_id: str,
        capabilities: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        all_rows = _merge_dimension_rows(
            dimensions=list(capabilities.get("dimensions") or []),
            time_columns=list(capabilities.get("time_columns") or []),
        )
        if not all_rows:
            return []

        by_key = {_norm_key(row.get("column_key")): row for row in all_rows if _norm_key(row.get("column_key"))}
        table_ids = sorted(
            {
                int(wtid)
                for wtid in (_to_int(row.get("workspace_table_id")) for row in all_rows)
                if wtid is not None
            }
        )
        if not table_ids:
            return all_rows[:40]

        query_texts = _build_column_query_texts(prompt)
        try:
            vectors = self._embedding_model().encode(query_texts, normalize=True)
        except Exception:
            return _cap_columns_per_table(all_rows, max_columns=50, per_table_cap=12)
        query_filter = qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(
                    key="kind",
                    match=qdrant_models.MatchValue(value="column"),
                ),
                qdrant_models.FieldCondition(
                    key="workspace_id",
                    match=qdrant_models.MatchValue(value=str(workspace_id)),
                ),
                qdrant_models.FieldCondition(
                    key="workspace_table_id",
                    match=qdrant_models.MatchAny(any=table_ids),
                ),
            ]
        )

        by_score: Dict[str, float] = {}
        limit = min(max(len(all_rows), 80), 220)
        try:
            for vector in vectors:
                hits = self._column_vector_client().search(
                    vector=vector,
                    limit=limit,
                    query_filter=query_filter,
                    with_payload=True,
                )
                for hit in hits:
                    payload = hit.payload or {}
                    wtid = _to_int(payload.get("workspace_table_id"))
                    col = str(payload.get("column_name") or "").strip().lower()
                    if wtid is None or col == "":
                        continue
                    key = f"wt{wtid}.{col}"
                    if key not in by_key:
                        continue
                    score = float(hit.score or 0.0)
                    if score > float(by_score.get(key) or 0.0):
                        by_score[key] = score
        except Exception:
            return _cap_columns_per_table(all_rows, max_columns=50, per_table_cap=12)

        if not by_score:
            return _cap_columns_per_table(all_rows, max_columns=50, per_table_cap=12)

        for key, row in by_key.items():
            score = float(by_score.get(key) or 0.0)
            by_score[key] = score + _column_heuristic_boost(prompt=prompt, row=row)

        required_keys = _required_column_keys(prompt=prompt, rows=all_rows)
        ordered = sorted(by_score.items(), key=lambda item: item[1], reverse=True)
        selected_keys = _select_keys_with_table_cap(
            ordered_keys=[key for key, _ in ordered],
            row_by_key=by_key,
            max_columns=min(max(35, len(required_keys) + 25), 70),
            per_table_cap=12,
        )
        for key in required_keys:
            if key not in selected_keys and key in by_key:
                selected_keys.append(key)
        selected_keys = selected_keys[:70]
        return [dict(by_key[key]) for key in selected_keys if key in by_key]

    def _compact_capabilities_for_llm(
        self,
        *,
        capabilities: Mapping[str, Any],
        shortlisted_columns: Sequence[Mapping[str, Any]],
        prompt: str,
        slot_hints: Optional[Mapping[str, Any]] = None,
        fast_mode: bool = False,
    ) -> Dict[str, Any]:
        full_dims = [dict(row) for row in list(capabilities.get("dimensions") or []) if isinstance(row, dict)]
        full_time = [dict(row) for row in list(capabilities.get("time_columns") or []) if isinstance(row, dict)]
        full_filter_candidates = _merge_dimension_rows(dimensions=full_dims, time_columns=full_time)
        dim_by_key = {_norm_key(row.get("column_key")): row for row in full_dims if _norm_key(row.get("column_key"))}
        is_school_listing = _looks_like_list_schools_prompt(prompt) or _slot_implies_school_listing(slot_hints)
        prompt_mentions_students = _prompt_mentions_students(prompt) or _slot_mentions_students(slot_hints)
        prompt_mentions_school_district = _prompt_mentions_school_or_district(prompt)
        city_state_pattern = _prompt_has_city_state_pattern(prompt)
        has_preferred_state = _has_preferred_state_column(rows=full_dims)
        prefer_human_school_filter = (
            _prompt_prefers_human_school_name_filter(prompt)
            and _has_school_name_column(rows=full_filter_candidates)
            and not _prompt_explicitly_requests_school_key(prompt)
        )
        prefer_staff_role_title_filter = (
            _prompt_prefers_staff_role_title_filter(prompt)
            and _has_staff_role_title_column(rows=full_filter_candidates)
        )
        prefer_canonical_name_columns = (
            _prompt_prefers_canonical_name_columns(prompt)
            and _has_canonical_name_columns(rows=full_filter_candidates)
        )

        selected_dims: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in shortlisted_columns:
            key = _norm_key(row.get("column_key"))
            if key == "" or key in seen:
                continue
            base = dim_by_key.get(key) or dict(row)
            selected_dims.append(base)
            seen.add(key)

        if not selected_dims:
            selected_dims = full_dims[:40]
            seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}

        if _prompt_has_subgroup(prompt):
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if any(token in col_name for token in ("race", "ethnicity", "hispanic", "latino")):
                    selected_dims.append(row)
                    seen.add(key)

        if prompt_mentions_students:
            selected_dims = _prepend_student_identity_dimensions(selected_dims=selected_dims, full_dims=full_dims)
            seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if _is_student_identity_column_name(col_name):
                    selected_dims.append(row)
                    seen.add(key)
                    if len(selected_dims) >= 55:
                        break
        if prompt_mentions_school_district:
            lea_dim = _find_dimension_by_column_name_candidates(
                full_dims=full_dims,
                targets=("lea_name", "district_name", "district"),
            )
            if lea_dim is not None:
                lea_key = _norm_key(lea_dim.get("column_key"))
                if lea_key and lea_key not in seen:
                    selected_dims.append(dict(lea_dim))
                    seen.add(lea_key)
        if is_school_listing:
            selected_dims = _prepend_school_listing_dimensions(selected_dims=selected_dims, full_dims=full_dims)
            seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            if city_state_pattern and has_preferred_state:
                selected_dims = [
                    dict(row)
                    for row in selected_dims
                    if not _is_state_school_code_name(str(row.get("column_name") or "").strip().lower())
                ]
                seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            if prefer_human_school_filter:
                selected_dims = [
                    dict(row)
                    for row in selected_dims
                    if not _is_technical_school_key_name(str(row.get("column_name") or "").strip().lower())
                ]
                seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if city_state_pattern and has_preferred_state and _is_state_school_code_name(col_name):
                    continue
                if prefer_human_school_filter and _is_technical_school_key_name(col_name):
                    continue
                if any(token in col_name for token in ("school_name", "lea_name", "school_number", "city", "state")):
                    selected_dims.append(row)
                    seen.add(key)
                    if len(selected_dims) >= 55:
                        break
        if prefer_human_school_filter:
            seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if _is_technical_school_key_name(col_name):
                    continue
                if col_name in {"school_name", "lea_name"}:
                    selected_dims.append(row)
                    seen.add(key)
            if selected_dims:
                selected_dims = _prepend_school_name_for_filter_context(selected_dims=selected_dims, full_dims=full_dims)

        if prefer_staff_role_title_filter:
            selected_dims = [
                dict(row)
                for row in selected_dims
                if not _is_staff_classification_column_name(str(row.get("column_name") or "").strip().lower())
            ]
            seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if _is_staff_role_title_column_name(col_name):
                    selected_dims.append(row)
                    seen.add(key)

        if prefer_canonical_name_columns:
            selected_dims = [
                dict(row)
                for row in selected_dims
                if not _is_preferred_name_column_name(str(row.get("column_name") or "").strip().lower())
            ]
            seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if _is_canonical_name_column_name(col_name):
                    selected_dims.append(row)
                    seen.add(key)

        if _prompt_has_name_constraint(prompt):
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if _is_name_column_needed_for_prompt(prompt=prompt, column_name=col_name):
                    selected_dims.append(row)
                    seen.add(key)

        max_columns = max(12, int(QF_PLAN_DOMAIN_FAST_MODE_MAX_DIMENSIONS)) if fast_mode else 70
        per_table_cap = 8 if fast_mode else 14
        selected_dims = _cap_columns_per_table(selected_dims, max_columns=max_columns, per_table_cap=per_table_cap)
        selected_time = [dict(row) for row in full_time[: (8 if fast_mode else 12)]]

        filter_columns: List[Dict[str, Any]] = []
        filter_seen: set[str] = set()

        def _add_filter_row(row: Mapping[str, Any]) -> None:
            key = _norm_key(row.get("column_key"))
            if key == "" or key in filter_seen:
                return
            if row.get("filterable") is False:
                return
            col_name = str(row.get("column_name") or "").strip().lower()
            if prefer_human_school_filter and _is_technical_school_key_name(col_name):
                return
            if prefer_staff_role_title_filter and _is_staff_classification_column_name(col_name):
                return
            if prefer_canonical_name_columns and _is_preferred_name_column_name(col_name):
                return
            filter_columns.append(dict(row))
            filter_seen.add(key)

        for row in selected_dims:
            _add_filter_row(row)
        for row in selected_time:
            _add_filter_row(row)

        if _prompt_has_nativity(prompt):
            nativity_names = {"birth_country", "country_of_birth", "date_entered_us"}
            for row in full_filter_candidates:
                col_name = str(row.get("column_name") or "").strip().lower()
                if col_name in nativity_names:
                    _add_filter_row(row)

        if _prompt_has_name_constraint(prompt):
            for row in full_filter_candidates:
                col_name = str(row.get("column_name") or "").strip().lower()
                if _is_name_column_needed_for_prompt(prompt=prompt, column_name=col_name):
                    _add_filter_row(row)

        max_filter_columns = max(12, int(QF_PLAN_DOMAIN_FAST_MODE_MAX_FILTER_COLUMNS)) if fast_mode else len(filter_columns)
        if len(filter_columns) > max_filter_columns:
            filter_columns = filter_columns[:max_filter_columns]

        return {
            "domain_id": _to_int(capabilities.get("domain_id")) or 0,
            "domain_version": _to_int(capabilities.get("domain_version")) or 0,
            "dimensions": selected_dims,
            "time_columns": selected_time,
            "filter_columns": filter_columns,
            "domain_metrics": [dict(row) for row in list(capabilities.get("domain_metrics") or []) if isinstance(row, dict)],
            "user_metrics": [dict(row) for row in list(capabilities.get("user_metrics") or []) if isinstance(row, dict)],
            "overlay_metrics": [dict(row) for row in list(capabilities.get("overlay_metrics") or []) if isinstance(row, dict)],
        }

    @staticmethod
    def _full_capabilities_for_execution(capabilities: Mapping[str, Any]) -> Dict[str, Any]:
        dimensions = [dict(row) for row in list(capabilities.get("dimensions") or []) if isinstance(row, dict)]
        time_columns = [dict(row) for row in list(capabilities.get("time_columns") or []) if isinstance(row, dict)]
        filter_columns = [
            dict(row)
            for row in _merge_dimension_rows(dimensions=dimensions, time_columns=time_columns)
            if row.get("filterable") is not False
        ]
        return {
            "domain_id": _to_int(capabilities.get("domain_id")) or 0,
            "domain_version": _to_int(capabilities.get("domain_version")) or 0,
            "dimensions": dimensions,
            "time_columns": time_columns,
            "filter_columns": filter_columns,
            "domain_metrics": [dict(row) for row in list(capabilities.get("domain_metrics") or []) if isinstance(row, dict)],
            "user_metrics": [dict(row) for row in list(capabilities.get("user_metrics") or []) if isinstance(row, dict)],
            "overlay_metrics": [dict(row) for row in list(capabilities.get("overlay_metrics") or []) if isinstance(row, dict)],
        }

    def _call_llm_slots(
        self,
        *,
        normalized_prompt: str,
        workspace_id: str,
        vertical_norm: str,
        base_domain_id: int,
        conversation_context: Optional[PlanConversationContext] = None,
        fast_mode: bool = False,
    ) -> SlotExtractionResult:
        system_prompt = build_system_prompt()
        composed_user = (
            f"{build_slot_developer_prompt()}\n\n"
            f"{build_slot_user_prompt(normalized_prompt=normalized_prompt, workspace_id=workspace_id, vertical_norm=vertical_norm, base_domain_id=base_domain_id)}"
        )
        if conversation_context is not None and conversation_context.followup_mode:
            composed_user = (
                f"{composed_user}\n"
                "Conversation context for follow-up turn:\n"
                f"{json.dumps(_conversation_context_payload(conversation_context), ensure_ascii=True)}\n"
                "If current prompt is an edit/follow-up, use prior plan to retain unchanged filters/selections."
            )

        attempts = 0
        last_raw = ""
        max_attempts = 1 if fast_mode else 2
        slot_max_tokens = (
            max(80, min(int(QF_PLAN_DOMAIN_FAST_MODE_SLOT_MAX_TOKENS), int(SEMANTIC_PLAN_LLM_MAX_TOKENS)))
            if fast_mode
            else min(800, SEMANTIC_PLAN_LLM_MAX_TOKENS)
        )
        for _ in range(max_attempts):
            attempts += 1
            trace = self._llm.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=composed_user,
                response_format=True,
                max_tokens=slot_max_tokens,
            )
            parsed = trace.get("parsed") if isinstance(trace.get("parsed"), dict) else None
            raw_content = str(trace.get("content") or trace.get("raw_text") or "")
            last_raw = raw_content
            if parsed is not None and _looks_like_slot_payload(parsed):
                return SlotExtractionResult(payload=parsed, raw_content=raw_content, attempts=attempts, repaired=False)

        if fast_mode:
            fallback_subgroups = _extract_subgroup_terms(normalized_prompt)
            fallback_intent = "list" if _looks_like_list_students_prompt(normalized_prompt) else "unknown"
            fallback_payload = {
                "intent": fallback_intent,
                "entity": "students" if "student" in normalized_prompt.lower() else "",
                "constraints": [
                    {
                        "kind": "demographic",
                        "text": value,
                        "op": "unknown",
                        "value_hint": value,
                        "notes": None,
                    }
                    for value in fallback_subgroups
                ],
                "time_phrases": _extract_time_phrases(normalized_prompt),
            }
            return SlotExtractionResult(payload=fallback_payload, raw_content=last_raw, attempts=attempts, repaired=False)

        repair_prompt = build_json_repair_prompt(schema=SLOT_JSON_SCHEMA, broken_json=last_raw)
        repair_trace = self._llm.chat_json_with_trace(
            system_prompt=system_prompt,
            user_prompt=repair_prompt,
            response_format=True,
            max_tokens=min(1200, max(900, SEMANTIC_PLAN_LLM_MAX_TOKENS)),
        )
        parsed = repair_trace.get("parsed") if isinstance(repair_trace.get("parsed"), dict) else None
        raw_content = str(repair_trace.get("content") or repair_trace.get("raw_text") or "")
        if parsed is not None and _looks_like_slot_payload(parsed):
            return SlotExtractionResult(payload=parsed, raw_content=raw_content, attempts=3, repaired=True)

        fallback_subgroups = _extract_subgroup_terms(normalized_prompt)
        fallback_intent = "list" if _looks_like_list_students_prompt(normalized_prompt) else "unknown"
        fallback_payload = {
            "intent": fallback_intent,
            "entity": "students" if "student" in normalized_prompt.lower() else "",
            "constraints": [
                {
                    "kind": "demographic",
                    "text": value,
                    "op": "unknown",
                    "value_hint": value,
                    "notes": None,
                }
                for value in fallback_subgroups
            ],
            "time_phrases": _extract_time_phrases(normalized_prompt),
        }
        return SlotExtractionResult(payload=fallback_payload, raw_content=raw_content, attempts=3, repaired=True)

    def _call_llm_unified(
        self,
        *,
        prompt: str,
        normalized_prompt: str,
        workspace_id: str,
        vertical_norm: str,
        base_domain_id: int,
        domain_name: Optional[str],
        capabilities: Mapping[str, Any],
        conversation_context: Optional[PlanConversationContext] = None,
        trace_id: str,
        fast_mode: bool = False,
    ) -> Dict[str, Any]:
        plan_max_tokens = (
            max(120, min(int(QF_PLAN_DOMAIN_FAST_MODE_PLAN_MAX_TOKENS), int(SEMANTIC_PLAN_LLM_MAX_TOKENS)))
            if fast_mode
            else int(SEMANTIC_PLAN_LLM_MAX_TOKENS)
        )
        if fast_mode:
            slot_max_tokens = max(
                80,
                min(int(QF_PLAN_DOMAIN_FAST_MODE_SLOT_MAX_TOKENS), int(SEMANTIC_PLAN_LLM_MAX_TOKENS)),
            )
            unified_max_tokens = min(
                int(SEMANTIC_PLAN_LLM_MAX_TOKENS),
                max(plan_max_tokens + slot_max_tokens, 420),
            )
        else:
            unified_max_tokens = int(SEMANTIC_PLAN_LLM_MAX_TOKENS)
        conversation_payload = (
            _conversation_context_payload(conversation_context)
            if conversation_context is not None and conversation_context.followup_mode
            else {}
        )
        if QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED:
            compact_max_tokens = min(
                int(SEMANTIC_PLAN_LLM_MAX_TOKENS),
                max(
                    160,
                    min(
                        int(QF_PLAN_DOMAIN_COMPACT_MAX_TOKENS),
                        unified_max_tokens,
                    ),
                ),
            )
            return build_compact_plan_and_project(
                prompt=prompt,
                normalized_prompt=normalized_prompt,
                workspace_id=workspace_id,
                vertical_norm=vertical_norm,
                base_domain_id=base_domain_id,
                domain_name=domain_name,
                capabilities_compact=dict(capabilities or {}),
                conversation_context=conversation_payload,
                trace_id=trace_id,
                llm_client=self._llm,
                max_tokens=compact_max_tokens,
                fast_mode=fast_mode,
            )
        return build_plan_and_slots(
            prompt=prompt,
            normalized_prompt=normalized_prompt,
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            base_domain_id=base_domain_id,
            domain_name=domain_name,
            capabilities_compact=dict(capabilities or {}),
            conversation_context=conversation_payload,
            trace_id=trace_id,
            llm_client=self._llm,
            max_tokens=unified_max_tokens,
        )

    def _merge_slot_hints(
        self,
        *,
        prompt: str,
        slot_payload: Mapping[str, Any],
        semantic_constraints: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> Dict[str, Any]:
        slot_intent = str(slot_payload.get("intent") or "unknown").strip().lower() or "unknown"
        constraints = _parse_constraints(slot_payload.get("constraints"))
        semantic_items = _parse_constraints(list(semantic_constraints or []))
        if semantic_items:
            constraints = _dedupe_constraints(constraints + semantic_items)
        subgroups = _parse_text_list(slot_payload.get("subgroups"))
        if constraints:
            constraint_terms = [
                str(item.get("value_hint") or item.get("text") or "").strip()
                for item in constraints
                if str(item.get("value_hint") or item.get("text") or "").strip()
            ]
            subgroups = _dedupe_text_items(subgroups + constraint_terms)
        time_phrases = _parse_text_list(slot_payload.get("time_phrases"))
        entity = str(slot_payload.get("entity") or "").strip().lower()

        if slot_intent == "unknown" and _looks_like_list_students_prompt(prompt):
            slot_intent = "list"
        if _prompt_has_subgroup(prompt):
            subgroups = _dedupe_text_items(subgroups + _extract_subgroup_terms(prompt))
        if not time_phrases:
            time_phrases = _extract_time_phrases(prompt)

        return {
            "intent": slot_intent,
            "entity": entity,
            "subgroups": subgroups,
            "constraints": constraints,
            "time_phrases": time_phrases,
        }

    def _semantic_value_alias_constraints(
        self,
        *,
        prompt: str,
        vertical_norm: str,
    ) -> List[Dict[str, Any]]:
        if not QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED:
            return []
        try:
            rows = self._value_alias_resolver().resolve(prompt=prompt, vertical_norm=vertical_norm)
        except Exception as exc:
            logger.warning("planner_domain semantic alias resolution failed err=%s", exc)
            return []

        constraints: List[Dict[str, Any]] = []
        for row in list(rows or []):
            if not isinstance(row, Mapping):
                continue
            canonical = str(row.get("canonical_value") or "").strip()
            if canonical == "":
                continue
            concept_key = str(row.get("concept_key") or "").strip().upper()
            matched_alias = str(row.get("matched_alias") or "").strip()
            constraints.append(
                {
                    "kind": "unknown",
                    "text": matched_alias or canonical,
                    "op": "eq",
                    "value_hint": canonical,
                    "notes": f"semantic_alias:{concept_key}" if concept_key else "semantic_alias",
                }
            )
        return _dedupe_constraints(constraints)

    def _call_llm_plan(
        self,
        *,
        normalized_prompt: str,
        workspace_id: str,
        vertical_norm: str,
        base_domain_id: int,
        capabilities: Mapping[str, Any],
        schema: Dict[str, Any],
        slot_hints: Mapping[str, Any],
        validation_feedback: str = "",
        retry_hint: str = "",
        conversation_context: Optional[PlanConversationContext] = None,
        fast_mode: bool = False,
    ) -> LLMPlanResult:
        system_prompt = build_system_prompt()
        developer_prompt = build_developer_prompt(
            schema=schema,
            slot_hints=slot_hints,
            validation_feedback=validation_feedback,
            retry_hint=retry_hint,
        )
        user_prompt = build_user_prompt(
            normalized_prompt=normalized_prompt,
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            base_domain={"domain_id": int(base_domain_id)},
            capabilities=capabilities,
            schema=schema,
            slot_hints=slot_hints,
        )
        if conversation_context is not None and conversation_context.followup_mode:
            user_prompt = (
                f"{user_prompt}\n"
                "Conversation context for follow-up turn:\n"
                f"{json.dumps(_conversation_context_payload(conversation_context), ensure_ascii=True)}\n"
                "Apply user edits to the prior plan. Preserve prior filters/dimensions unless user explicitly changes them."
            )
        composed_user = f"{developer_prompt}\n\n{user_prompt}"

        attempts = 0
        last_raw = ""
        plan_max_tokens = (
            max(120, min(int(QF_PLAN_DOMAIN_FAST_MODE_PLAN_MAX_TOKENS), int(SEMANTIC_PLAN_LLM_MAX_TOKENS)))
            if fast_mode
            else int(SEMANTIC_PLAN_LLM_MAX_TOKENS)
        )
        max_attempts = 1 if fast_mode else 2
        for _ in range(max_attempts):
            attempts += 1
            trace = self._llm.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=composed_user,
                response_format=True,
                max_tokens=plan_max_tokens,
            )
            parsed = trace.get("parsed") if isinstance(trace.get("parsed"), dict) else None
            raw_content = str(trace.get("content") or trace.get("raw_text") or "")
            last_raw = raw_content
            if parsed is not None and _looks_like_plan_v2(parsed):
                return LLMPlanResult(plan_json=parsed, raw_content=raw_content, attempts=attempts, repaired=False)

        if fast_mode:
            repair_prompt = build_json_repair_prompt(schema=schema, broken_json=last_raw)
            repair_trace = self._llm.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=repair_prompt,
                response_format=True,
                max_tokens=max(120, min(220, plan_max_tokens)),
            )
            parsed = repair_trace.get("parsed") if isinstance(repair_trace.get("parsed"), dict) else None
            raw_content = str(repair_trace.get("content") or repair_trace.get("raw_text") or "")
            if parsed is not None and _looks_like_plan_v2(parsed):
                return LLMPlanResult(plan_json=parsed, raw_content=raw_content, attempts=attempts + 1, repaired=True)
            raise ForgeError("plan_domain invalid model JSON", status_code=502, details={"raw": raw_content[:4000]})

        repair_prompt = build_json_repair_prompt(schema=schema, broken_json=last_raw)
        repair_trace = self._llm.chat_json_with_trace(
            system_prompt=system_prompt,
            user_prompt=repair_prompt,
            response_format=True,
            max_tokens=max(1800, SEMANTIC_PLAN_LLM_MAX_TOKENS),
        )
        parsed = repair_trace.get("parsed") if isinstance(repair_trace.get("parsed"), dict) else None
        raw_content = str(repair_trace.get("content") or repair_trace.get("raw_text") or "")
        if parsed is not None and _looks_like_plan_v2(parsed):
            return LLMPlanResult(plan_json=parsed, raw_content=raw_content, attempts=3, repaired=True)
        raise ForgeError("plan_domain invalid model JSON", status_code=502, details={"raw": raw_content[:4000]})

    def _embedding_model(self) -> EmbeddingModel:
        if self._embedding is None:
            self._embedding = EmbeddingModel(model_name=EMBEDDING_MODEL_NAME)
        return self._embedding

    def _column_vector_client(self) -> QdrantClientWrapper:
        if self._column_qdrant is None:
            self._column_qdrant = QdrantClientWrapper(collection_name=QDRANT_COLUMN_COLLECTION_V2)
        return self._column_qdrant

    def _value_alias_resolver(self) -> ValueAliasResolutionService:
        if self._value_alias_resolver_svc is None:
            self._value_alias_resolver_svc = ValueAliasResolutionService()
        return self._value_alias_resolver_svc

    def _resolve_semester_indicator_columns(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        capabilities: Mapping[str, Any],
    ) -> Dict[str, str]:
        inferred = _infer_semester_indicator_columns_from_capabilities(capabilities=capabilities)
        semantic = self._resolve_semester_indicator_columns_from_semantic_registry(
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            capabilities=capabilities,
        )
        out = dict(inferred)
        out.update(semantic)
        return out

    def _resolve_semester_indicator_columns_from_semantic_registry(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        capabilities: Mapping[str, Any],
    ) -> Dict[str, str]:
        if not QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED:
            return {}

        cap_rows = list(capabilities.get("filter_columns") or []) + list(capabilities.get("dimensions") or []) + list(
            capabilities.get("time_columns") or []
        )
        model_to_key: Dict[int, str] = {}
        for row in cap_rows:
            if not isinstance(row, Mapping):
                continue
            key = _norm_key(row.get("column_key"))
            mid = _to_int(row.get("model_column_id"))
            if key == "" or mid is None:
                continue
            if row.get("filterable") is False:
                continue
            model_to_key[mid] = key
        if not model_to_key:
            return {}

        params: Dict[str, Any] = {
            "workspace_norm": str(workspace_id or "").strip() or "__global__",
            "vertical_norm": _norm_vertical(vertical_norm),
        }
        placeholders: List[str] = []
        for idx, model_column_id in enumerate(sorted(model_to_key.keys())):
            token = f"mid_{idx}"
            placeholders.append(f":{token}")
            params[token] = int(model_column_id)

        sql = f"""
            SELECT
              scm.model_column_id,
              sr.concept_key,
              sr.semantic_type,
              scm.priority_rank,
              scm.confidence_score
            FROM semantic_column_map scm
            JOIN semantic_registry sr
              ON sr.id = scm.semantic_registry_id
            WHERE scm.workspace_norm IN (:workspace_norm, '__global__')
              AND sr.vertical_norm IN (:vertical_norm, 'generic')
              AND scm.model_column_id IN ({", ".join(placeholders)})
            ORDER BY
              scm.priority_rank DESC,
              scm.confidence_score DESC,
              scm.id DESC
        """
        try:
            rows = ForgeMetaSQL().execute_query_mappings(sql, params)
        except Exception as exc:
            logger.warning("planner_domain semantic semester indicator lookup failed err=%s", exc)
            return {}

        best: Dict[str, Tuple[float, str]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            model_column_id = _to_int(row.get("model_column_id"))
            if model_column_id is None:
                continue
            column_key = model_to_key.get(model_column_id)
            if not column_key:
                continue
            concept_key = str(row.get("concept_key") or "")
            bucket = _semester_bucket_from_text(concept_key)
            if bucket == "":
                continue

            score = float(row.get("priority_rank") or 0) * 10.0 + float(row.get("confidence_score") or 0.0)
            if str(row.get("semantic_type") or "").strip().lower() == "flag":
                score += 1.0

            current = best.get(bucket)
            if current is None or score > current[0]:
                best[bucket] = (score, column_key)

        return {bucket: value for bucket, (_score, value) in best.items() if value}

    def _maybe_polish_explanation_summary(
        self,
        *,
        prompt: str,
        explanation: Mapping[str, Any],
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        out = dict(explanation or {})
        fallback_summary = str(out.get("summary") or "").strip()
        out["summary_source"] = "deterministic"
        if not QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED:
            return out, {"enabled": False, "used": False}
        if fallback_summary == "":
            return out, {"enabled": True, "used": False, "reason": "missing_fallback_summary"}

        payload = {
            "user_question": str(prompt or "").strip(),
            "domain": str(((out.get("domain") or {}).get("selected_domain_name") or "")).strip(),
            "selected_columns": [str(item.get("label") or "").strip() for item in list(out.get("dimensions") or []) if str(item.get("label") or "").strip()],
            "metrics": [str(item.get("label") or "").strip() for item in list(out.get("metrics") or []) if str(item.get("label") or "").strip()],
            "filters": [
                {
                    "field": str(item.get("label") or "").strip(),
                    "operator": str(item.get("op_label") or "").strip(),
                    "value": item.get("value"),
                    "values": item.get("values"),
                }
                for item in list(out.get("filters") or [])
                if isinstance(item, Mapping)
            ],
            "fallback_summary": fallback_summary,
        }

        system_prompt = (
            "You rewrite analytics explanations for educators.\n"
            "Write plain language with no technical jargon, IDs, scores, or internal field keys.\n"
            "Keep it concise: 1-3 sentences.\n"
            "Return strict JSON only: {\"summary\":\"...\"}."
        )
        user_prompt = (
            "Rewrite this explanation into a friendly summary for school staff.\n"
            f"Input JSON:\n{json.dumps(payload, ensure_ascii=True)}"
        )
        try:
            trace = self._llm.chat_json_with_trace(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=True,
                max_tokens=QF_PLAN_DOMAIN_LLM_EXPLANATION_MAX_TOKENS,
            )
        except Exception as exc:
            logger.warning("planner_domain explanation polish failed err=%s", exc)
            return out, {"enabled": True, "used": False, "error": str(exc)}

        parsed = trace.get("parsed") if isinstance(trace.get("parsed"), Mapping) else {}
        candidate = str((parsed or {}).get("summary") or "").strip()
        candidate = _normalize_explanation_summary(candidate)
        if candidate:
            out["summary"] = candidate
            out["summary_source"] = "llm"

        return out, {
            "enabled": True,
            "used": bool(candidate),
            "error": trace.get("error"),
            "finish_reason": trace.get("finish_reason"),
            "content_preview": str(trace.get("content") or "")[:300],
        }

    def _maybe_generate_next_actions(
        self,
        *,
        prompt: str,
        selected_domain_id: int,
        selected_domain_name: str,
        plan_json: Mapping[str, Any],
        capabilities: Mapping[str, Any],
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if not QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED:
            return [], {"enabled": False, "used": False}

        max_items = max(1, min(int(QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_ITEMS or 3), 6))
        capability_payload = _next_action_capability_payload(capabilities=capabilities)
        if not capability_payload.get("allowed_dimensions") and not capability_payload.get("allowed_metric_refs"):
            return [], {"enabled": True, "used": False, "reason": "no_capabilities"}

        input_payload = {
            "user_question": str(prompt or "").strip(),
            "domain": {
                "domain_id": int(selected_domain_id),
                "domain_name": str(selected_domain_name or "").strip(),
                "domain_version": _to_int(capabilities.get("domain_version")) or 0,
            },
            "current_plan": _next_action_plan_context(plan_json=plan_json),
            "capabilities": capability_payload,
            "rules": {
                "stay_in_domain": True,
                "suggestion_count": {"min": 2, "max": max_items},
            },
            "schema": NEXT_ACTIONS_JSON_SCHEMA,
        }
        composed_user = (
            f"{build_next_actions_developer_prompt()}\n\n"
            f"{build_next_actions_user_prompt(payload=input_payload)}"
        )
        try:
            trace = self._llm.chat_json_with_trace(
                system_prompt=build_system_prompt(),
                user_prompt=composed_user,
                response_format=True,
                max_tokens=QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_TOKENS,
            )
        except Exception as exc:
            logger.warning("planner_domain next actions generation failed err=%s", exc)
            return [], {"enabled": True, "used": False, "error": str(exc)}

        parsed = trace.get("parsed") if isinstance(trace.get("parsed"), Mapping) else {}
        raw_actions = list((parsed or {}).get("next_actions") or [])
        normalized = _normalize_next_actions(
            actions=raw_actions,
            original_prompt=prompt,
            capabilities=capabilities,
            max_items=max_items,
        )
        retry_trace: Optional[Dict[str, Any]] = None
        if not normalized:
            retry_user_prompt = (
                f"{composed_user}\n\n"
                "Retry requirements:\n"
                "- Use exact allowed column_key values from capabilities.\n"
                "- If a column is uncertain, omit it.\n"
                "- Return at least 2 safe suggestions that remain inside this domain."
            )
            try:
                retry_trace = self._llm.chat_json_with_trace(
                    system_prompt=build_system_prompt(),
                    user_prompt=retry_user_prompt,
                    response_format=True,
                    max_tokens=QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_TOKENS,
                )
                retry_parsed = retry_trace.get("parsed") if isinstance(retry_trace.get("parsed"), Mapping) else {}
                retry_raw_actions = list((retry_parsed or {}).get("next_actions") or [])
                normalized = _normalize_next_actions(
                    actions=retry_raw_actions,
                    original_prompt=prompt,
                    capabilities=capabilities,
                    max_items=max_items,
                )
                if retry_raw_actions:
                    raw_actions = retry_raw_actions
            except Exception as exc:
                logger.warning("planner_domain next actions retry failed err=%s", exc)

        return normalized, {
            "enabled": True,
            "used": bool(normalized),
            "requested_items": len(raw_actions),
            "returned_items": len(normalized),
            "error": trace.get("error"),
            "finish_reason": trace.get("finish_reason"),
            "content_preview": str(trace.get("content") or "")[:300],
            "retried": retry_trace is not None,
            "retry_error": (retry_trace or {}).get("error") if retry_trace is not None else None,
            "retry_finish_reason": (retry_trace or {}).get("finish_reason") if retry_trace is not None else None,
            "retry_content_preview": str((retry_trace or {}).get("content") or "")[:300] if retry_trace is not None else "",
        }

    @staticmethod
    def _normalize_llm_plan(
        *,
        raw_plan: Mapping[str, Any],
        trace_id: str,
        workspace_id: str,
        vertical_norm: str,
        base_domain_id: int,
        base_domain_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        out = dict(raw_plan or {})
        out["schema_version"] = 2
        out["trace_id"] = str(out.get("trace_id") or trace_id)
        out["workspace_id"] = workspace_id
        out["vertical_norm"] = vertical_norm
        out["base_domain_id"] = int(base_domain_id)
        if str(base_domain_name or "").strip():
            out["domain_name"] = str(base_domain_name).strip()
        out.setdefault("intent", "list")
        out.setdefault("selects", {"dimensions": [], "metrics": []})
        out.setdefault("filters", [])
        out.setdefault("time", {})
        out.setdefault("grouping", {"group_by": [], "limit": None, "order_by": []})

        # Normalize common LLM casing aliases so downstream validation sees canonical PlanV2 keys.
        selects = out.get("selects") if isinstance(out.get("selects"), Mapping) else {}
        raw_dims = list(selects.get("dimensions") or []) if isinstance(selects, Mapping) else []
        normalized_dims: List[Dict[str, Any]] = []
        for row in raw_dims:
            if not isinstance(row, Mapping):
                continue
            column_key = _norm_key(row.get("column_key") or row.get("columnKey"))
            if column_key == "":
                continue
            normalized_dims.append({"column_key": column_key})

        raw_metrics = list(selects.get("metrics") or []) if isinstance(selects, Mapping) else []
        normalized_metrics: List[Dict[str, Any]] = []
        for row in raw_metrics:
            if not isinstance(row, Mapping):
                continue
            metric_ref = _norm_key(
                row.get("metric_ref")
                or row.get("metricRef")
                or row.get("metricref")
            )
            if metric_ref == "":
                continue
            normalized_metrics.append({"metric_ref": metric_ref})

        out["selects"] = {
            "dimensions": normalized_dims,
            "metrics": normalized_metrics,
        }
        return out


def _plan_conversation_context_from_state(
    *,
    conversation_id: str,
    prompt: str,
    state: Optional[Mapping[str, Any]],
    force_followup: bool = False,
    seeded_from_client: bool = False,
) -> Optional[PlanConversationContext]:
    if not isinstance(state, Mapping):
        return None
    prior_plan = dict(state.get("plan_json_v2") or {}) if isinstance(state.get("plan_json_v2"), Mapping) else {}
    if not prior_plan:
        return None
    prior_prompt = str(state.get("last_prompt") or "").strip()
    followup_mode = bool(force_followup) or _prompt_is_followup_edit(prompt=prompt, prior_prompt=prior_prompt)
    return PlanConversationContext(
        conversation_id=str(conversation_id or "").strip(),
        prior_prompt=prior_prompt,
        prior_plan_json_v2=prior_plan,
        prior_vertical_norm=_norm_vertical(str(state.get("vertical_norm") or "generic")),
        followup_mode=followup_mode,
        seeded_from_client=bool(seeded_from_client),
    )


def _prompt_is_followup_edit(*, prompt: str, prior_prompt: str) -> bool:
    text = normalize_plan_prompt(prompt).lower()
    if text == "":
        return False
    if _SORT_ONLY_PROMPT_RE.search(text) is not None:
        return True
    if prior_prompt.strip() == "":
        return False
    if len(text) <= 80 and _FOLLOWUP_EDIT_HINT_RE.search(text) is not None:
        return True
    starter_tokens = ("also ", "now ", "then ", "and ", "only ", "just ")
    return any(text.startswith(token) for token in starter_tokens)


def _bootstrap_conversation_state_from_seed(
    *,
    workspace_id: str,
    user_id: str,
    vertical_norm: str,
    seed_plan_json_v2: Mapping[str, Any],
    seed_last_prompt: str,
) -> Dict[str, Any]:
    plan = dict(seed_plan_json_v2 or {})
    normalized_vertical = _norm_vertical(vertical_norm)
    plan_vertical = _norm_vertical(str(plan.get("vertical_norm") or normalized_vertical))
    prompt = seed_last_prompt
    if prompt == "":
        prompt = str(((plan.get("debug") or {}).get("normalized_prompt") or "")).strip()
    return {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "vertical_norm": plan_vertical,
        "last_prompt": prompt,
        "trace_id": str(plan.get("trace_id") or "").strip(),
        "plan_json_v2": plan,
        "sql_json": {},
    }


def _conversation_context_payload(context: PlanConversationContext) -> Dict[str, Any]:
    plan = dict(context.prior_plan_json_v2 or {})
    scoped_plan = {
        "base_domain_id": plan.get("base_domain_id"),
        "domain_name": plan.get("domain_name"),
        "intent": plan.get("intent"),
        "selects": plan.get("selects"),
        "filters": plan.get("filters"),
        "time": plan.get("time"),
        "grouping": plan.get("grouping"),
    }
    return {
        "conversation_id": context.conversation_id,
        "prior_prompt": context.prior_prompt,
        "prior_plan_v2": scoped_plan,
    }


def _merge_followup_plan_with_context(
    *,
    prompt: str,
    candidate_plan: Mapping[str, Any],
    prior_plan: Optional[Mapping[str, Any]],
    capabilities: Mapping[str, Any],
) -> Dict[str, Any]:
    out = dict(candidate_plan or {})
    if not isinstance(prior_plan, Mapping):
        return out
    prompt_norm = normalize_plan_prompt(prompt).lower()
    if _FOLLOWUP_EDIT_HINT_RE.search(prompt_norm) is None and _SORT_ONLY_PROMPT_RE.search(prompt_norm) is None:
        return out

    prior = dict(prior_plan)

    if _prompt_is_sort_only(prompt_norm):
        out = _merge_sort_only_followup(
            prompt=prompt_norm,
            candidate_plan=out,
            prior_plan=prior,
            capabilities=capabilities,
        )
        return out

    # For generic follow-ups, preserve context when LLM returns an underspecified patch-like plan.
    candidate_filters = [dict(item) for item in list(out.get("filters") or []) if isinstance(item, dict)]
    prior_filters = [dict(item) for item in list(prior.get("filters") or []) if isinstance(item, dict)]
    if len(candidate_filters) == 0 and len(prior_filters) > 0 and not _prompt_requests_filter_removal(prompt_norm):
        out["filters"] = prior_filters

    out_selects = dict(out.get("selects") or {})
    prior_selects = dict(prior.get("selects") or {})
    candidate_dims = [dict(item) for item in list(out_selects.get("dimensions") or []) if isinstance(item, dict)]
    prior_dims = [dict(item) for item in list(prior_selects.get("dimensions") or []) if isinstance(item, dict)]
    if len(candidate_dims) == 0 and len(prior_dims) > 0:
        out_selects["dimensions"] = prior_dims
    out["selects"] = out_selects

    out_grouping = dict(out.get("grouping") or {})
    if len(list(out_grouping.get("group_by") or [])) == 0 and len(prior_dims) > 0:
        out_grouping["group_by"] = [str(item.get("column_key") or "").strip() for item in prior_dims if str(item.get("column_key") or "").strip()]
    out["grouping"] = out_grouping
    return out


def _merge_sort_only_followup(
    *,
    prompt: str,
    candidate_plan: Mapping[str, Any],
    prior_plan: Mapping[str, Any],
    capabilities: Mapping[str, Any],
) -> Dict[str, Any]:
    out = dict(prior_plan or {})
    out["trace_id"] = str(candidate_plan.get("trace_id") or out.get("trace_id") or "")

    candidate_grouping = dict(candidate_plan.get("grouping") or {})
    candidate_order_by = [dict(item) for item in list(candidate_grouping.get("order_by") or []) if isinstance(item, dict)]
    if candidate_order_by:
        grouping = dict(out.get("grouping") or {})
        grouping["order_by"] = candidate_order_by
        out["grouping"] = grouping
        return out

    key, direction = _extract_sort_request_from_prompt(prompt=prompt, capabilities=capabilities, fallback_plan=out)
    if key == "":
        return dict(candidate_plan or out)

    grouping = dict(out.get("grouping") or {})
    grouping["order_by"] = [{"by": key, "dir": direction}]
    dims = [dict(item) for item in list((out.get("selects") or {}).get("dimensions") or []) if isinstance(item, dict)]
    if len(list(grouping.get("group_by") or [])) == 0 and dims:
        grouping["group_by"] = [str(item.get("column_key") or "").strip() for item in dims if str(item.get("column_key") or "").strip()]
    out["grouping"] = grouping
    return out


def _prompt_is_sort_only(prompt: str) -> bool:
    token = normalize_plan_prompt(prompt).lower()
    return _SORT_ONLY_PROMPT_RE.search(token) is not None


def _prompt_requests_filter_removal(prompt: str) -> bool:
    token = f" {normalize_plan_prompt(prompt).lower()} "
    return any(phrase in token for phrase in (" remove filter ", " clear filters ", " without filter ", " no filters "))


def _extract_sort_request_from_prompt(
    *,
    prompt: str,
    capabilities: Mapping[str, Any],
    fallback_plan: Mapping[str, Any],
) -> Tuple[str, str]:
    token = normalize_plan_prompt(prompt).lower()
    match = _SORT_BY_RE.search(token)
    direction = "asc"
    field_hint = ""
    if match is not None:
        field_hint = str(match.group("field") or "").strip().lower()
        dir_hint = str(match.group("dir") or "").strip().lower()
        if dir_hint in {"desc", "descending"}:
            direction = "desc"
    if field_hint == "":
        return "", direction

    column_key = _resolve_sort_column_key_from_hint(field_hint=field_hint, capabilities=capabilities, fallback_plan=fallback_plan)
    return column_key, direction


def _resolve_sort_column_key_from_hint(
    *,
    field_hint: str,
    capabilities: Mapping[str, Any],
    fallback_plan: Mapping[str, Any],
) -> str:
    hint_tokens = [token for token in re.split(r"[^a-z0-9]+", field_hint.lower()) if token and token not in {"the", "a", "an"}]
    if not hint_tokens:
        return ""

    candidate_rows: List[Dict[str, Any]] = []
    for row in (
        list(capabilities.get("dimensions") or [])
        + list(capabilities.get("filter_columns") or [])
        + list(capabilities.get("time_columns") or [])
    ):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "":
            continue
        candidate_rows.append(dict(row))

    selected_keys = {
        _norm_key(item.get("column_key"))
        for item in list((fallback_plan.get("selects") or {}).get("dimensions") or [])
        if isinstance(item, Mapping) and _norm_key(item.get("column_key"))
    }

    best_key = ""
    best_score = -1
    for row in candidate_rows:
        key = _norm_key(row.get("column_key"))
        name = str(row.get("column_name") or "").strip().lower()
        label = str(row.get("label") or "").strip().lower()
        score = sum(2 for token in hint_tokens if token in name or token in label) + sum(1 for token in hint_tokens if token in key)
        if key in selected_keys:
            score += 2
        if score > best_score:
            best_key = key
            best_score = score
    return best_key if best_score > 0 else ""


def normalize_plan_prompt(prompt: str) -> str:
    text = str(prompt or "")
    text = _DANGEROUS_CHAR_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _looks_like_plan_v2(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False

    selects = payload.get("selects")
    if not isinstance(selects, dict):
        return False

    dimensions = selects.get("dimensions")
    metrics = selects.get("metrics")
    if dimensions is not None and not isinstance(dimensions, list):
        return False
    if metrics is not None and not isinstance(metrics, list):
        return False

    filters = payload.get("filters")
    if filters is not None and not isinstance(filters, list):
        return False

    time_block = payload.get("time")
    if time_block is not None and not isinstance(time_block, dict):
        return False

    grouping = payload.get("grouping")
    if grouping is not None and not isinstance(grouping, dict):
        return False

    return True


def _looks_like_slot_payload(payload: Dict[str, Any]) -> bool:
    required = ("intent", "constraints", "time_phrases")
    if not all(key in payload for key in required):
        return False
    constraints = payload.get("constraints")
    if not isinstance(constraints, list):
        return False
    for item in constraints:
        if not isinstance(item, dict):
            return False
        if "kind" not in item or "text" not in item or "op" not in item:
            return False
    if payload.get("subgroups") is not None and not isinstance(payload.get("subgroups"), list):
        return False
    if not isinstance(payload.get("time_phrases"), list):
        return False
    return True


def _norm_vertical(vertical_norm: str) -> str:
    token = str(vertical_norm or "generic").strip().lower()
    if token in {"education", "healthcare", "generic"}:
        return token
    return "generic"


def _capabilities_summary(capabilities: Mapping[str, Any]) -> Dict[str, Any]:
    dims = list(capabilities.get("dimensions") or [])
    filters = list(capabilities.get("filter_columns") or [])
    times = list(capabilities.get("time_columns") or [])
    domain_metrics = list(capabilities.get("domain_metrics") or [])
    user_metrics = list(capabilities.get("user_metrics") or [])
    overlay_metrics = list(capabilities.get("overlay_metrics") or [])
    return {
        "domain_id": _to_int(capabilities.get("domain_id")),
        "domain_version": _to_int(capabilities.get("domain_version")),
        "dimension_count": len(dims),
        "filter_count": len(filters),
        "time_count": len(times),
        "domain_metric_count": len(domain_metrics),
        "user_metric_count": len(user_metrics),
        "overlay_metric_count": len(overlay_metrics),
    }


def _project_root_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _resolve_plan_domain_log_path(configured_path: str, default_path: str) -> str:
    token = str(configured_path or "").strip() or str(default_path or "").strip()
    if token == "":
        token = "logs/plan_domain_pipeline.log"
    if os.path.isabs(token):
        return token
    return os.path.abspath(os.path.join(_project_root_dir(), token))


def _pipeline_profile_logger() -> logging.Logger:
    global _PROFILE_LOGGER_INITIALIZED

    profile_logger = logging.getLogger(_PROFILE_LOGGER_NAME)
    if _PROFILE_LOGGER_INITIALIZED:
        return profile_logger

    profile_logger.setLevel(logging.INFO)
    profile_logger.propagate = False
    try:
        log_path = _resolve_plan_domain_log_path(
            str(QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE or ""),
            "logs/plan_domain_pipeline_timing.log",
        )
        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        handler = WatchedFileHandler(log_path, mode="a", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
        profile_logger.addHandler(handler)
        _PROFILE_LOGGER_INITIALIZED = True
    except Exception as exc:
        logger.warning("planner_domain timing profile logger init failed err=%s", exc)
    return profile_logger


def _pipeline_trace_logger() -> logging.Logger:
    global _TRACE_LOGGER_INITIALIZED

    trace_logger = logging.getLogger(_TRACE_LOGGER_NAME)
    if _TRACE_LOGGER_INITIALIZED:
        return trace_logger

    trace_logger.setLevel(logging.INFO)
    trace_logger.propagate = False
    try:
        log_path = _resolve_plan_domain_log_path(
            str(QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE or ""),
            "logs/plan_domain_pipeline_trace.jsonl",
        )
        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        handler = WatchedFileHandler(log_path, mode="a", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        trace_logger.addHandler(handler)
        _TRACE_LOGGER_INITIALIZED = True
    except Exception as exc:
        logger.warning("planner_domain pipeline trace logger init failed err=%s", exc)
    return trace_logger


def _append_pipeline_trace_step(
    *,
    trace: Dict[str, Any],
    enabled: bool,
    step: str,
    data: Mapping[str, Any],
) -> None:
    if not enabled:
        return
    steps = trace.setdefault("steps", [])
    if not isinstance(steps, list):
        trace["steps"] = []
        steps = trace["steps"]
    steps.append(
        {
            "step": str(step or "").strip(),
            "data": _sanitize_pipeline_trace_value(data),
        }
    )


def _sanitize_pipeline_trace_value(value: Any, *, depth: int = 0) -> Any:
    max_chars = max(200, int(QF_PLAN_DOMAIN_PIPELINE_TRACE_MAX_CHARS or 12000))
    max_items = max(10, int(QF_PLAN_DOMAIN_PIPELINE_TRACE_MAX_ITEMS or 100))
    if depth >= 8:
        return "<max_depth>"
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        token = value.strip()
        return token[:max_chars]
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for idx, (k, v) in enumerate(value.items()):
            if idx >= max_items:
                out["__truncated__"] = f"{len(value) - max_items} more"
                break
            out[str(k)] = _sanitize_pipeline_trace_value(v, depth=depth + 1)
        return out
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items: List[Any] = []
        for idx, item in enumerate(value):
            if idx >= max_items:
                items.append(f"<truncated:{len(value) - max_items} more>")
                break
            items.append(_sanitize_pipeline_trace_value(item, depth=depth + 1))
        return items
    return str(value)[:max_chars]


def _add_pipeline_step(
    *,
    profile_steps: List[Dict[str, Any]],
    enabled: bool,
    step: str,
    label: str,
    started_at: float,
) -> int:
    elapsed = _elapsed_ms(started_at)
    if enabled:
        profile_steps.append(
            {
                "step": step,
                "label": label,
                "ms": elapsed,
            }
        )
    return elapsed


def _emit_pipeline_profile_log(
    *,
    enabled: bool,
    trace_id: str,
    workspace_id: str,
    user_id: str,
    conversation_id: str,
    prompt: str,
    total_ms: int,
    steps: Sequence[Mapping[str, Any]],
) -> None:
    if not enabled:
        return
    try:
        lines = [
            (
                f"plan_domain_pipeline trace_id={trace_id} workspace_id={workspace_id} user_id={user_id} "
                f"conversation_id={conversation_id} total_ms={total_ms}"
            ),
            f"prompt={prompt[:240]}",
        ]
        for idx, row in enumerate(steps, start=1):
            label = str(row.get("label") or row.get("step") or "").strip()
            ms = int(row.get("ms") or 0)
            lines.append(f"{idx}. {label}: {ms}ms")
        _pipeline_profile_logger().info("\n".join(lines))
    except Exception as exc:
        logger.warning("planner_domain timing profile emit failed trace_id=%s err=%s", trace_id, exc)


def _emit_pipeline_trace_log(
    *,
    enabled: bool,
    trace_payload: Mapping[str, Any],
) -> None:
    if not enabled:
        return
    try:
        payload = _sanitize_pipeline_trace_value(trace_payload)
        _pipeline_trace_logger().info(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    except Exception as exc:
        logger.warning("planner_domain pipeline trace emit failed trace_id=%s err=%s", trace_payload.get("trace_id"), exc)


def _read_pipeline_profile_from_log(
    *,
    trace_id: str,
    workspace_id: str,
    user_id: str,
) -> Dict[str, Any]:
    log_path = _resolve_plan_domain_log_path(
        str(QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE or ""),
        "logs/plan_domain_pipeline_timing.log",
    )
    if not os.path.exists(log_path):
        raise ForgeError(
            "Pipeline profile log not found",
            status_code=404,
            details={"trace_id": trace_id, "log_file": log_path},
        )
    try:
        with open(log_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except Exception as exc:
        raise ForgeError(
            "Failed to read pipeline profile log",
            status_code=500,
            details={"trace_id": trace_id, "log_file": log_path, "error": str(exc)},
        ) from exc

    records: List[Tuple[str, List[str]]] = []
    current_header: Optional[str] = None
    current_lines: List[str] = []
    for line in lines:
        if "plan_domain_pipeline trace_id=" in line:
            if current_header is not None:
                records.append((current_header, list(current_lines)))
            current_header = line
            current_lines = []
            continue
        if current_header is not None:
            current_lines.append(line)
    if current_header is not None:
        records.append((current_header, list(current_lines)))

    for header_line, detail_lines in reversed(records):
        parsed = _parse_pipeline_profile_record(header_line=header_line, detail_lines=detail_lines)
        if not parsed:
            continue
        if str(parsed.get("trace_id") or "") != trace_id:
            continue
        if workspace_id and str(parsed.get("workspace_id") or "") != workspace_id:
            continue
        if user_id and str(parsed.get("user_id") or "") != user_id:
            continue
        parsed["log_file"] = log_path
        parsed["profiling_enabled"] = bool(QF_PLAN_DOMAIN_TIMING_PROFILE_ENABLED)
        return parsed

    raise ForgeError(
        "Pipeline profile not found",
        status_code=404,
        details={"trace_id": trace_id, "workspace_id": workspace_id, "user_id": user_id, "log_file": log_path},
    )


def _read_pipeline_trace_from_log(
    *,
    trace_id: str,
    workspace_id: str,
    user_id: str,
) -> Optional[Dict[str, Any]]:
    log_path = _resolve_plan_domain_log_path(
        str(QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE or ""),
        "logs/plan_domain_pipeline_trace.jsonl",
    )
    if not os.path.exists(log_path):
        return None
    try:
        with open(log_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except Exception:
        logger.exception("Failed to read pipeline trace log")
        return None

    for line in reversed(lines):
        text = str(line or "").strip()
        if text == "":
            continue
        try:
            parsed = json.loads(text)
        except Exception:
            continue
        if not isinstance(parsed, dict):
            continue
        if str(parsed.get("trace_id") or "").strip() != trace_id:
            continue
        if workspace_id and str(parsed.get("workspace_id") or "").strip() != workspace_id:
            continue
        if user_id and str(parsed.get("user_id") or "").strip() != user_id:
            continue
        parsed["log_file"] = log_path
        parsed["trace_enabled"] = bool(QF_PLAN_DOMAIN_PIPELINE_TRACE_ENABLED)
        return parsed
    return None


def _list_pipeline_profiles_from_log(*, limit: int = 50) -> List[Dict[str, Any]]:
    log_path = _resolve_plan_domain_log_path(
        str(QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE or ""),
        "logs/plan_domain_pipeline_timing.log",
    )
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except Exception:
        logger.exception("Failed to read pipeline profile log for listing")
        return []

    records: List[Tuple[str, List[str]]] = []
    current_header: Optional[str] = None
    current_lines: List[str] = []
    for line in lines:
        if "plan_domain_pipeline trace_id=" in line:
            if current_header is not None:
                records.append((current_header, list(current_lines)))
            current_header = line
            current_lines = []
            continue
        if current_header is not None:
            current_lines.append(line)
    if current_header is not None:
        records.append((current_header, list(current_lines)))

    profiles: List[Dict[str, Any]] = []
    for header_line, detail_lines in reversed(records):
        parsed = _parse_pipeline_profile_record(header_line=header_line, detail_lines=detail_lines)
        if parsed:
            profiles.append(parsed)
        if len(profiles) >= limit:
            break
    return profiles


def _parse_pipeline_profile_record(*, header_line: str, detail_lines: Sequence[str]) -> Optional[Dict[str, Any]]:
    header_match = _PIPELINE_PROFILE_HEADER_RE.search(str(header_line or ""))
    if header_match is None:
        return None

    total_ms = _to_int(header_match.group("total_ms")) or 0
    timestamp_match = _PIPELINE_PROFILE_TIMESTAMP_RE.search(str(header_line or ""))
    timestamp = str((timestamp_match.group("timestamp") if timestamp_match else "") or "").strip()

    prompt = ""
    steps: List[Dict[str, Any]] = []
    for raw in detail_lines:
        text = str(raw or "").strip()
        if text == "":
            continue
        if text.startswith("prompt="):
            prompt = text.removeprefix("prompt=").strip()
            continue
        step_match = _PIPELINE_PROFILE_STEP_RE.match(text)
        if step_match is None:
            continue
        steps.append(
            {
                "index": _to_int(step_match.group("index")) or 0,
                "label": str(step_match.group("label") or "").strip(),
                "ms": _to_int(step_match.group("ms")) or 0,
            }
        )

    return {
        "trace_id": str(header_match.group("trace_id") or "").strip(),
        "workspace_id": str(header_match.group("workspace_id") or "").strip(),
        "user_id": str(header_match.group("user_id") or "").strip(),
        "conversation_id": str(header_match.group("conversation_id") or "").strip(),
        "total_ms": total_ms,
        "timestamp": timestamp,
        "prompt": prompt,
        "steps": steps,
    }


def _elapsed_ms(start: float) -> int:
    return int((perf_counter() - start) * 1000)


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_text_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    items = [str(item).strip() for item in value if str(item).strip()]
    return _dedupe_text_items(items)


def _parse_constraints(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "unknown").strip().lower() or "unknown"
        text = str(item.get("text") or "").strip()
        op = str(item.get("op") or "unknown").strip().lower() or "unknown"
        value_hint_raw = item.get("value_hint")
        notes_raw = item.get("notes")
        value_hint = str(value_hint_raw).strip() if value_hint_raw not in (None, "") else None
        notes = str(notes_raw).strip() if notes_raw not in (None, "") else None
        if text == "" and value_hint is None:
            continue
        out.append(
            {
                "kind": kind,
                "text": text or str(value_hint or ""),
                "op": op,
                "value_hint": value_hint,
                "notes": notes,
            }
        )
    return out


def _dedupe_text_items(values: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for value in values:
        token = " ".join(str(value).strip().split())
        if token == "":
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _dedupe_constraints(values: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in values:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "unknown").strip().lower() or "unknown"
        text = " ".join(str(item.get("text") or "").strip().split())
        op = str(item.get("op") or "unknown").strip().lower() or "unknown"
        value_hint = " ".join(str(item.get("value_hint") or "").strip().split()) if item.get("value_hint") not in (None, "") else ""
        notes = " ".join(str(item.get("notes") or "").strip().split()) if item.get("notes") not in (None, "") else ""
        if text == "" and value_hint == "":
            continue
        key = (kind, text.lower(), op, value_hint.lower(), notes.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "kind": kind,
                "text": text or value_hint,
                "op": op,
                "value_hint": value_hint or None,
                "notes": notes or None,
            }
        )
    return out


def _looks_like_list_students_prompt(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if text == "":
        return False
    if _AGGREGATE_STUDENTS_RE.search(text) is not None:
        return False
    if _LIST_STUDENTS_RE.search(text) is not None:
        return True
    return re.search(r"\b(student|students)\b", text, flags=re.IGNORECASE) is not None


def _looks_like_list_schools_prompt(prompt: str) -> bool:
    text = str(prompt or "").strip()
    if text == "":
        return False
    if _AGGREGATE_SCHOOLS_RE.search(text) is not None:
        return False
    if _LIST_SCHOOLS_RE.search(text) is not None:
        return True
    return re.search(r"\b(school|schools)\b", text, flags=re.IGNORECASE) is not None


def _prompt_mentions_students(prompt: str) -> bool:
    return re.search(r"\b(student|students|kid|kids)\b", str(prompt or ""), flags=re.IGNORECASE) is not None


def _slot_mentions_students(slot_hints: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(slot_hints, Mapping):
        return False
    entity = str(slot_hints.get("entity") or "").strip().lower()
    return entity in {"student", "students", "kid", "kids"}


def _prompt_mentions_school_or_district(prompt: str) -> bool:
    text = str(prompt or "")
    if re.search(r"\b(school|schools)\b", text, flags=re.IGNORECASE) is not None:
        return True
    return _DISTRICT_LEA_TERM_RE.search(text) is not None


def _selected_domain_name(*, domain_candidates: Sequence[Mapping[str, Any]], selected_domain_id: int) -> Optional[str]:
    selected = int(selected_domain_id)
    for row in domain_candidates:
        if _to_int(row.get("domain_id")) != selected:
            continue
        name = str(row.get("name") or "").strip()
        if name:
            return name
    return None


def _prompt_has_subgroup(prompt: str) -> bool:
    return _SUBGROUP_HINT_RE.search(str(prompt or "")) is not None


def _prompt_has_nativity(prompt: str) -> bool:
    text = str(prompt or "").lower()
    nativity_terms = (
        "born",
        "birth",
        "birth country",
        "not born",
        "entered the us",
        "date entered us",
    )
    return any(term in text for term in nativity_terms)


def _prompt_has_name_constraint(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return ("first name" in text) or ("last name" in text) or ("named " in text) or ("name of " in text)


def _prompt_explicitly_requests_preferred_name(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    explicit_phrases = (
        " preferred name ",
        " preferred first name ",
        " preferred last name ",
        " preferred names ",
    )
    return any(phrase in text for phrase in explicit_phrases)


def _prompt_prefers_canonical_name_columns(prompt: str) -> bool:
    text = str(prompt or "")
    if text.strip() == "":
        return False
    if _prompt_explicitly_requests_preferred_name(text):
        return False
    return (
        _prompt_has_name_constraint(text)
        or _prompt_implies_staff_work_context(text)
        or _prompt_implies_student_school_context(text)
        or _looks_like_list_students_prompt(text)
    )


def _is_preferred_name_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token in {"preferred_first_name", "preferred_last_name"} or (
        token.startswith("preferred_") and token.endswith("_name")
    )


def _is_canonical_name_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    return token in {"first_name", "last_name"}


def _has_canonical_name_columns(*, rows: Sequence[Mapping[str, Any]]) -> bool:
    names = {str(row.get("column_name") or "").strip().lower() for row in rows}
    return "first_name" in names or "last_name" in names


def _is_student_identity_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    if _is_preferred_name_column_name(token):
        return False
    if token in {"first_name", "last_name", "display_name", "safe_display_name"}:
        return True
    if token.startswith("k_student"):
        return True
    if "student_id" in token:
        return True
    return False


def _is_name_column_needed_for_prompt(*, prompt: str, column_name: str) -> bool:
    text = str(prompt or "").lower()
    col = str(column_name or "").strip().lower()
    if col == "":
        return False
    wants_preferred = _prompt_explicitly_requests_preferred_name(text)
    if "first name" in text and ((wants_preferred and col == "preferred_first_name") or (not wants_preferred and col == "first_name")):
        return True
    if "last name" in text and ((wants_preferred and col == "preferred_last_name") or (not wants_preferred and col == "last_name")):
        return True
    if ("named " in text or "name of " in text) and (
        (wants_preferred and col in {"preferred_first_name", "preferred_last_name"})
        or (not wants_preferred and col in {"first_name", "last_name", "display_name", "safe_display_name"})
    ):
        return True
    return False


def _extract_subgroup_terms(prompt: str) -> List[str]:
    text = str(prompt or "")
    matches = [match.group(0) for match in _SUBGROUP_HINT_RE.finditer(text)]
    return _dedupe_text_items(matches)


def _extract_time_phrases(prompt: str) -> List[str]:
    text = str(prompt or "").lower()
    phrases: List[str] = []
    if "this year" in text:
        phrases.append("this year")
    if "last year" in text:
        phrases.append("last year")
    if "current school year" in text:
        phrases.append("current school year")
    if "school year" in text and not phrases:
        phrases.append("school year")
    return _dedupe_text_items(phrases)


def _merge_dimension_rows(*, dimensions: Sequence[Mapping[str, Any]], time_columns: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in list(dimensions) + list(time_columns):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "" or key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _build_column_query_texts(prompt: str) -> List[str]:
    text = str(prompt or "").strip()
    out = [text]
    text_l = text.lower()
    group_entities = _extract_group_entities_for_shortlist(text_l)
    if _has_group_entity(group_entities, "account"):
        out.extend(["account name", "customer account"])
    if _has_group_entity(group_entities, "territory"):
        out.extend(["territory name", "sales territory"])
    if _has_group_entity(group_entities, "region"):
        out.extend(["region name"])
    if _prompt_has_subgroup(text):
        out.extend(["student race ethnicity", "student subgroup"])
    if _looks_like_list_students_prompt(text):
        out.extend(["student list", "student roster", "student demographics"])
    if _prompt_implies_staff_work_context(text):
        out.extend(["staff roster", "staff assignments", "teacher workplace", "employee school"])
    if _prompt_prefers_staff_role_title_filter(text):
        out.extend(["staff position title", "staff role title", "principal position"])
    if _prompt_implies_student_school_context(text):
        out.extend(["student enrollment", "student attends school", "student school"])
    if "county" in text_l:
        out.append("county district")
    if "district" in text_l:
        out.append("district lea")
    if "school year" in text_l or "this year" in text_l or "last year" in text_l:
        out.append("school year date")
    if _prompt_has_adm_intent(text):
        out.extend(
            [
                "average daily membership adm base adm",
                "normalized_adm report_period school_year",
                "is_primary_school grade_level_adm",
            ]
        )
    return _dedupe_text_items(out)


def _build_domain_query_texts(prompt: str) -> List[str]:
    text = str(prompt or "").strip()
    if text == "":
        return []
    out = [text]
    text_l = text.lower()
    if _prompt_implies_staff_work_context(text):
        out.extend(["staff assignments", "staff workplace", "teacher employment", "employee roster"])
    if _prompt_implies_student_school_context(text):
        out.extend(["student enrollment", "student demographics", "student profile"])
    if _DISCIPLINE_HINT_RE.search(text) is not None:
        out.extend(["discipline incidents", "student behavior"])
    if "district" in text_l or "lea" in text_l:
        out.append("school district lea")
    if _prompt_has_adm_intent(text):
        out.extend(
            [
                "average daily membership adm base adm",
                "student base adm attendance membership",
                "enrollment adm report period school year",
            ]
        )
    return _dedupe_text_items(out)


def _required_column_keys(*, prompt: str, rows: Sequence[Mapping[str, Any]]) -> List[str]:
    required: List[str] = []
    text = str(prompt or "").lower()
    group_entities = _extract_group_entities_for_shortlist(text)
    city_state_pattern = _prompt_has_city_state_pattern(text)
    prefer_human_school_filter = (
        _prompt_prefers_human_school_name_filter(text)
        and _has_school_name_column(rows=rows)
        and not _prompt_explicitly_requests_school_key(text)
    )
    prefer_staff_role_title_filter = (
        _prompt_prefers_staff_role_title_filter(text)
        and _has_staff_role_title_column(rows=rows)
    )
    prefer_canonical_name_columns = (
        _prompt_prefers_canonical_name_columns(text)
        and _has_canonical_name_columns(rows=rows)
    )
    prompt_has_adm_intent = _prompt_has_adm_intent(text)
    for row in rows:
        key = _norm_key(row.get("column_key"))
        col_name = str(row.get("column_name") or "").strip().lower()
        if key == "":
            continue
        if _matches_group_entity_column(col_name=col_name, entities=group_entities):
            required.append(key)
            continue
        if prompt_has_adm_intent and _is_adm_signal_column_name(col_name):
            required.append(key)
            continue
        if city_state_pattern:
            if _is_city_column_name(col_name):
                required.append(key)
                continue
            if _is_preferred_state_column_name(col_name):
                required.append(key)
                continue
            if _is_state_school_code_name(col_name):
                continue
        if prefer_human_school_filter:
            if col_name == "school_name":
                required.append(key)
                continue
            if _is_technical_school_key_name(col_name):
                continue
        if prefer_staff_role_title_filter:
            if _is_staff_role_title_column_name(col_name):
                required.append(key)
                continue
            if _is_staff_classification_column_name(col_name):
                continue
        if prefer_canonical_name_columns:
            if _is_canonical_name_column_name(col_name):
                required.append(key)
                continue
            if _is_preferred_name_column_name(col_name):
                continue
        if _prompt_has_subgroup(text) and any(token in col_name for token in ("race", "ethnicity", "hispanic", "latino")):
            required.append(key)
            continue
        if "county" in text and ("county" in col_name or "county" in key):
            required.append(key)
            continue
        if "district" in text and any(token in col_name for token in ("district", "lea_name", "lea")):
            required.append(key)
            continue
        if _looks_like_list_students_prompt(text) and _is_student_identity_column_name(col_name):
            required.append(key)
    return _dedupe_text_items(required)[:10]


def _column_heuristic_boost(*, prompt: str, row: Mapping[str, Any]) -> float:
    col_name = str(row.get("column_name") or "").strip().lower()
    key = _norm_key(row.get("column_key"))
    score = 0.0
    text = str(prompt or "").lower()
    group_entities = _extract_group_entities_for_shortlist(text)
    city_state_pattern = _prompt_has_city_state_pattern(text)
    prefer_human_school_filter = (
        _prompt_prefers_human_school_name_filter(text)
        and not _prompt_explicitly_requests_school_key(text)
    )
    prefer_staff_role_title_filter = _prompt_prefers_staff_role_title_filter(text)
    prefer_canonical_name_columns = _prompt_prefers_canonical_name_columns(text)
    prompt_has_adm_intent = _prompt_has_adm_intent(text)
    if _has_group_entity(group_entities, "account"):
        if col_name == "account_name":
            score += 0.42
        elif col_name in {"account_id", "account_type"}:
            score -= 0.22
    if _has_group_entity(group_entities, "territory"):
        if col_name == "territory_name":
            score += 0.4
        elif col_name == "territory_id":
            score -= 0.16
    if _has_group_entity(group_entities, "region"):
        if col_name == "region_name":
            score += 0.3
        elif col_name == "region_code":
            score -= 0.12
    if prompt_has_adm_intent:
        if _is_adm_signal_column_name(col_name):
            score += 0.42
        elif any(token in col_name for token in ("calendar", "term", "semester", "grading_period")):
            score -= 0.18
    if city_state_pattern:
        if _is_city_column_name(col_name):
            score += 0.36
        elif _is_preferred_state_column_name(col_name):
            score += 0.34
        if _is_state_school_code_name(col_name):
            score -= 0.45
        if "county" in col_name or "county" in key:
            score -= 0.22
    if prefer_human_school_filter:
        if col_name == "school_name":
            score += 0.34
        if col_name in {"lea_name", "district_name"}:
            score += 0.18
        if _is_technical_school_key_name(col_name):
            score -= 0.42
    if prefer_staff_role_title_filter:
        if _is_staff_role_title_column_name(col_name):
            score += 0.44
        if _is_staff_classification_column_name(col_name):
            score -= 0.4
    if prefer_canonical_name_columns:
        if _is_canonical_name_column_name(col_name):
            score += 0.28
        if _is_preferred_name_column_name(col_name):
            score -= 0.34
    if _prompt_has_subgroup(text) and any(token in col_name for token in ("race", "ethnicity", "hispanic", "latino")):
        score += 0.45
    if _looks_like_list_students_prompt(text) and _is_student_identity_column_name(col_name):
        score += 0.22
    if "county" in text and ("county" in key or "county" in col_name):
        score += 0.16
    if "district" in text and any(token in col_name for token in ("district", "lea_name", "lea")):
        score += 0.16
    return score


def _extract_group_entities_for_shortlist(prompt_text: str) -> set[str]:
    text = f" {str(prompt_text or '').strip().lower()} "
    if " by " not in text:
        return set()
    segment = text.split(" by ", 1)[1]
    segment = re.split(r"\b(where|for|with|during|in|on|from)\b", segment, maxsplit=1)[0]
    parts = [part.strip() for part in re.split(r"\band\b|,", segment) if part.strip()]
    out: set[str] = set()
    for part in parts:
        token = re.sub(r"\s+", " ", part).strip().lower()
        if token == "":
            continue
        if "account" in token:
            out.add("account")
        if "territory" in token:
            out.add("territory")
        if "region" in token:
            out.add("region")
        if "district" in token:
            out.add("district")
        if "school" in token:
            out.add("school")
    return out


def _has_group_entity(entities: set[str], name: str) -> bool:
    return str(name or "").strip().lower() in entities


def _matches_group_entity_column(*, col_name: str, entities: set[str]) -> bool:
    col = str(col_name or "").strip().lower()
    if col == "":
        return False
    if _has_group_entity(entities, "account"):
        if col == "account_name":
            return True
        if col.startswith("account_") and col.endswith("_name"):
            return True
    if _has_group_entity(entities, "territory"):
        if col == "territory_name":
            return True
        if col.startswith("territory_") and col.endswith("_name"):
            return True
    if _has_group_entity(entities, "region"):
        if col == "region_name":
            return True
    if _has_group_entity(entities, "district"):
        if col in {"district_name", "lea_name"}:
            return True
    if _has_group_entity(entities, "school"):
        if col == "school_name":
            return True
    return False


def _select_keys_with_table_cap(
    *,
    ordered_keys: Sequence[str],
    row_by_key: Mapping[str, Mapping[str, Any]],
    max_columns: int,
    per_table_cap: int,
) -> List[str]:
    out: List[str] = []
    per_table: Dict[int, int] = {}
    for key in ordered_keys:
        row = row_by_key.get(key)
        if row is None:
            continue
        wtid = _to_int(row.get("workspace_table_id"))
        if wtid is None:
            continue
        count = per_table.get(wtid, 0)
        if count >= per_table_cap:
            continue
        out.append(key)
        per_table[wtid] = count + 1
        if len(out) >= max_columns:
            break
    return out


def _cap_columns_per_table(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_columns: int,
    per_table_cap: int,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    per_table: Dict[int, int] = {}
    seen: set[str] = set()
    for row in rows:
        key = _norm_key(row.get("column_key"))
        if key == "" or key in seen:
            continue
        wtid = _to_int(row.get("workspace_table_id"))
        if wtid is None:
            continue
        count = per_table.get(wtid, 0)
        if count >= per_table_cap:
            continue
        out.append(dict(row))
        per_table[wtid] = count + 1
        seen.add(key)
        if len(out) >= max_columns:
            break
    return out


def _has_subgroup_column(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if any(token in col_name for token in ("race", "ethnicity", "hispanic", "latino")):
            return True
    return False


def _has_student_identity_column(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if _is_student_identity_column_name(col_name):
            return True
    return False


def _has_staff_identity_column(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if any(
            token in col_name
            for token in (
                "staff_unique_id",
                "local_staff_id",
                "staff_classification",
                "position_title",
                "classroom_position",
                "email_address",
            )
        ):
            return True
    return False


def _prompt_has_adm_intent(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    return _ADM_HINT_RE.search(text) is not None


def _is_adm_signal_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    if token in {"normalized_adm", "report_period", "school_year", "grade_level_adm", "is_primary_school"}:
        return True
    if "adm" in token:
        return True
    return False


def _has_adm_signal_columns(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if _is_adm_signal_column_name(col_name):
            return True
    return False


def _has_adm_metric(capabilities: Mapping[str, Any]) -> bool:
    for row in list(capabilities.get("domain_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("metric_key") or "").strip().lower()
        label = str(row.get("label") or "").strip().lower()
        if "adm" in key or "average daily membership" in label or "adm" in label:
            return True
    return False


def _prompt_implies_staff_work_context(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    if _STUDENT_ATTEND_HINT_RE.search(text) is not None and _STAFF_WORK_HINT_RE.search(text) is None:
        return False
    return _STAFF_WORK_HINT_RE.search(text) is not None


def _prompt_implies_student_school_context(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    if _STAFF_WORK_HINT_RE.search(text) is not None and _STUDENT_ATTEND_HINT_RE.search(text) is None:
        return False
    return _STUDENT_ATTEND_HINT_RE.search(text) is not None


def _domain_name_intent_bias(*, prompt: str, candidate: Mapping[str, Any]) -> float:
    name = str(candidate.get("name") or "").strip().lower()
    if name == "":
        return 0.0
    prompt_text = str(prompt or "").strip().lower()
    bias = 0.0

    if _prompt_implies_staff_work_context(prompt_text):
        if any(token in name for token in ("staff", "assignment", "employee", "teacher", "workforce")):
            bias += 0.18
        if "student" in name and _DISCIPLINE_HINT_RE.search(prompt_text) is None:
            bias -= 0.24
        if "discipline" in name and _DISCIPLINE_HINT_RE.search(prompt_text) is None:
            bias -= 0.28

    if _prompt_implies_student_school_context(prompt_text):
        if any(token in name for token in ("student", "demographic", "profile", "enrollment", "enrolment")):
            bias += 0.14
        if "discipline" in name and _DISCIPLINE_HINT_RE.search(prompt_text) is None:
            bias -= 0.12

    if _DISCIPLINE_HINT_RE.search(prompt_text) is not None and "discipline" in name:
        bias += 0.2

    if _prompt_has_adm_intent(prompt_text):
        if any(token in name for token in ("adm", "average daily membership", "membership", "enrollment", "attendance")):
            bias += 0.22
        if any(token in name for token in ("calendar", "academic time", "term", "semester")):
            bias -= 0.24

    return bias


def _prompt_has_city_state_pattern(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    match = _CITY_STATE_ABBR_RE.search(text)
    if match is None:
        return False
    token = str(match.group(1) or "").strip().lower()
    return token in _US_STATE_ABBR


def _is_city_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token == "city" or token.endswith("_city") or "city_name" in token


def _is_state_school_code_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    return "state_school_code" in token


def _is_technical_school_key_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    if token in {"k_school", "school_key", "nces_school_code"}:
        return True
    if token.startswith("k_") and "school" in token:
        return True
    return False


def _is_preferred_state_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "" or _is_state_school_code_name(token):
        return False
    if token in {"state_code", "state_abbr", "state_name"}:
        return True
    if token.endswith("_state_code") or token.endswith("_state_abbr") or token.endswith("_state_name"):
        return True
    return False


def _has_preferred_state_column(*, rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if _is_preferred_state_column_name(col_name):
            return True
    return False


def _has_school_name_column(*, rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if col_name == "school_name":
            return True
    return False


def _prompt_prefers_human_school_name_filter(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    has_school_context = any(
        token in text
        for token in (
            " school ",
            " schools ",
            " staff ",
            " teacher ",
            " teachers ",
            " principal ",
            " assistant principal ",
            " counselor ",
            " counsellor ",
        )
    )
    if not has_school_context and _SCHOOL_NAME_HINT_RE.search(text) is not None:
        has_school_context = True
    has_lookup_phrase = any(token in text for token in (" for ", " at ", " in "))
    return has_school_context and has_lookup_phrase


def _prompt_prefers_staff_role_title_filter(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    if _prompt_explicitly_requests_staff_classification(text):
        return False
    return _STAFF_ROLE_TITLE_HINT_RE.search(text) is not None


def _prompt_explicitly_requests_staff_classification(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    explicit_phrases = (
        " staff classification ",
        " classification code ",
        " classification ",
        " staff class ",
        " class code ",
    )
    return any(phrase in text for phrase in explicit_phrases)


def _prompt_explicitly_requests_school_key(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    explicit_phrases = (
        " k_school ",
        " school key ",
        " school keys ",
        " school id ",
        " school ids ",
        " school code ",
        " school codes ",
        " nces ",
    )
    return any(phrase in text for phrase in explicit_phrases)


def _is_staff_role_title_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token in {"position_title", "classroom_position", "job_title", "role_title", "staff_role"}


def _is_staff_classification_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    return token == "staff_classification" or token.endswith("_classification")


def _has_staff_role_title_column(*, rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if _is_staff_role_title_column_name(col_name):
            return True
    return False


def _slot_implies_student_listing(slot_hints: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(slot_hints, Mapping):
        return False
    intent = str(slot_hints.get("intent") or "").strip().lower()
    entity = str(slot_hints.get("entity") or "").strip().lower()
    return intent == "list" and entity in {"student", "students"}


def _slot_implies_school_listing(slot_hints: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(slot_hints, Mapping):
        return False
    intent = str(slot_hints.get("intent") or "").strip().lower()
    entity = str(slot_hints.get("entity") or "").strip().lower()
    return intent == "list" and entity in {"school", "schools"}


def _prepend_student_identity_dimensions(
    *,
    selected_dims: Sequence[Mapping[str, Any]],
    full_dims: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    by_key: Dict[str, Dict[str, Any]] = {}
    for row in full_dims:
        key = _norm_key(row.get("column_key"))
        if key == "":
            continue
        by_key[key] = dict(row)

    identity_prefix: List[Dict[str, Any]] = []
    prefix_seen: set[str] = set()
    for target in ("student_unique_id", "first_name", "last_name"):
        matched = _find_dimension_by_column_name(full_dims=full_dims, target=target)
        if matched is None:
            continue
        key = _norm_key(matched.get("column_key"))
        if key == "" or key in prefix_seen:
            continue
        identity_prefix.append(dict(matched))
        prefix_seen.add(key)

    if not identity_prefix:
        return [dict(row) for row in selected_dims if isinstance(row, Mapping)]

    out: List[Dict[str, Any]] = list(identity_prefix)
    for row in selected_dims:
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "" or key in prefix_seen:
            continue
        base = by_key.get(key) or dict(row)
        out.append(dict(base))
        prefix_seen.add(key)
    return out


def _prepend_school_listing_dimensions(
    *,
    selected_dims: Sequence[Mapping[str, Any]],
    full_dims: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    by_key: Dict[str, Dict[str, Any]] = {}
    for row in full_dims:
        key = _norm_key(row.get("column_key"))
        if key == "":
            continue
        by_key[key] = dict(row)

    school_prefix: List[Dict[str, Any]] = []
    prefix_seen: set[str] = set()
    for candidates in (
        ("school_name",),
        ("lea_name", "district_name", "district"),
        ("school_number", "school_num", "school_no"),
    ):
        matched = _find_dimension_by_column_name_candidates(full_dims=full_dims, targets=candidates)
        if matched is None:
            continue
        key = _norm_key(matched.get("column_key"))
        if key == "" or key in prefix_seen:
            continue
        school_prefix.append(dict(matched))
        prefix_seen.add(key)

    if not school_prefix:
        return [dict(row) for row in selected_dims if isinstance(row, Mapping)]

    out: List[Dict[str, Any]] = list(school_prefix)
    for row in selected_dims:
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "" or key in prefix_seen:
            continue
        base = by_key.get(key) or dict(row)
        out.append(dict(base))
        prefix_seen.add(key)
    return out


def _prepend_school_name_for_filter_context(
    *,
    selected_dims: Sequence[Mapping[str, Any]],
    full_dims: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    school_name = _find_dimension_by_column_name(full_dims=full_dims, target="school_name")
    if school_name is None:
        return [dict(row) for row in selected_dims if isinstance(row, Mapping)]

    school_key = _norm_key(school_name.get("column_key"))
    out: List[Dict[str, Any]] = [dict(school_name)]
    seen: set[str] = {school_key}

    by_key: Dict[str, Dict[str, Any]] = {}
    for row in full_dims:
        key = _norm_key(row.get("column_key"))
        if key:
            by_key[key] = dict(row)

    for row in selected_dims:
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "" or key in seen:
            continue
        out.append(dict(by_key.get(key) or dict(row)))
        seen.add(key)
    return out


def _find_dimension_by_column_name(*, full_dims: Sequence[Mapping[str, Any]], target: str) -> Optional[Dict[str, Any]]:
    needle = str(target or "").strip().lower()
    if needle == "":
        return None
    for row in full_dims:
        col_name = str(row.get("column_name") or "").strip().lower()
        if col_name == needle:
            return dict(row)
    return None


def _find_dimension_by_column_name_candidates(
    *,
    full_dims: Sequence[Mapping[str, Any]],
    targets: Sequence[str],
) -> Optional[Dict[str, Any]]:
    normalized_targets = [str(target or "").strip().lower() for target in targets if str(target or "").strip()]
    if not normalized_targets:
        return None
    for target in normalized_targets:
        matched = _find_dimension_by_column_name(full_dims=full_dims, target=target)
        if matched is not None:
            return matched
    for row in full_dims:
        col_name = str(row.get("column_name") or "").strip().lower()
        if col_name == "":
            continue
        if any(target in col_name for target in normalized_targets):
            return dict(row)
    return None


def _should_retry_after_validation(issues: Sequence[Mapping[str, Any]]) -> bool:
    retryable_codes = {
        "empty_plan",
        "invalid_filter_value_prompt_echo",
        "invalid_dimension_column",
        "invalid_filter_column",
        "unknown_metric_ref",
        "invalid_order_by_dimension",
        "invalid_order_by_metric",
    }
    for issue in issues:
        code = str(issue.get("code") or "").strip().lower()
        if code in retryable_codes:
            return True
    return False


def _format_validation_feedback(issues: Sequence[Mapping[str, Any]]) -> str:
    if not issues:
        return ""
    lines: List[str] = []
    for issue in issues[:8]:
        code = str(issue.get("code") or "unknown").strip()
        path = str(issue.get("path") or "").strip()
        message = str(issue.get("message") or "").strip()
        if path:
            lines.append(f"{code} at {path}: {message}")
        else:
            lines.append(f"{code}: {message}")
    return "; ".join(lines)


def _district_county_retry_hint(
    *,
    normalized_prompt: str,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
) -> Optional[str]:
    prompt = str(normalized_prompt or "").strip()
    if prompt == "" or _DISTRICT_LEA_TERM_RE.search(prompt) is None:
        return None

    prompt_norm = _normalize_text_for_match(prompt)
    district_positions = _district_term_positions(prompt_norm)
    if not district_positions:
        return None

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }
    filters = [dict(item) for item in list(plan_json.get("filters") or []) if isinstance(item, dict)]
    for row in filters:
        key = _norm_key(row.get("column_key"))
        meta = col_lookup.get(key) or {}
        column_name = str(meta.get("column_name") or key).strip().lower()
        if not (key.endswith(".name_of_county") or "county" in column_name):
            continue
        values = _extract_filter_values(row)
        if not values:
            continue
        for value in values:
            if not _looks_like_proper_noun_value(value):
                continue
            if _appears_near_district(prompt_norm, _normalize_text_for_match(value), district_positions):
                return (
                    "You likely mapped a district name to a geographic county column. "
                    "If the user meant a district/LEA, use lea_name for the proper noun "
                    "and reserve county columns for geography."
                )
    return None


def _normalize_text_for_match(value: str) -> str:
    text = str(value or "").strip().lower()
    text = _NON_WORD_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _district_term_positions(prompt_norm: str) -> List[int]:
    positions: List[int] = []
    for term in ("school district", "local education agency", "district", "lea"):
        start = 0
        while True:
            idx = prompt_norm.find(term, start)
            if idx < 0:
                break
            positions.append(idx)
            start = idx + len(term)
    positions.sort()
    return positions


def _appears_near_district(prompt_norm: str, value_norm: str, district_positions: Sequence[int]) -> bool:
    if prompt_norm == "" or value_norm == "":
        return False
    value_idx = prompt_norm.find(value_norm)
    if value_idx < 0:
        return False
    for pos in district_positions:
        if abs(pos - value_idx) <= 48:
            return True
    return False


def _looks_like_proper_noun_value(value: str) -> bool:
    text = str(value or "").strip()
    if text == "":
        return False
    if text.isdigit():
        return False
    return any(ch.isalpha() for ch in text)


def _normalize_country_filters_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, dict)]
    if not filters:
        return plan, [], []

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }

    issues: List[Dict[str, str]] = []
    debug_rows: List[Dict[str, Any]] = []
    normalized_filters: List[Dict[str, Any]] = []
    for idx, row in enumerate(filters):
        key = _norm_key(row.get("column_key"))
        col_meta = col_lookup.get(key) or {}
        if not is_country_iso2_column(col_meta):
            normalized_filters.append(row)
            continue

        raw_values = _extract_filter_values(row)
        codes = normalize_country_values(raw_values)
        debug_rows.append(
            {
                "column_key": key,
                "original": raw_values,
                "normalized": codes,
            }
        )
        if not codes:
            original_preview = ", ".join(raw_values)[:120]
            issues.append(
                {
                    "code": "unresolved_filter_value",
                    "path": f"filters[{idx}]",
                    "message": f"Could not resolve country value '{original_preview}' to ISO2",
                }
            )
            logger.debug("country_normalizer unresolved column=%s values=%s", key, raw_values)
            continue

        op_norm = str(row.get("op") or "").strip().lower()
        normalized = dict(row)
        if op_norm in {"in", "not_in"}:
            normalized["values"] = codes
            normalized.pop("value", None)
        elif op_norm in {"eq", "equals", "="}:
            normalized["op"] = "eq"
            if len(codes) == 1:
                normalized["value"] = codes[0]
                normalized.pop("values", None)
            else:
                normalized["op"] = "in"
                normalized["values"] = codes
                normalized.pop("value", None)
        elif op_norm in {"ne", "!=", "not_equals"}:
            normalized["op"] = "ne"
            if len(codes) == 1:
                normalized["value"] = codes[0]
                normalized.pop("values", None)
            else:
                normalized["op"] = "not_in"
                normalized["values"] = codes
                normalized.pop("value", None)
        else:
            if "values" in normalized:
                normalized["values"] = codes
                normalized.pop("value", None)
            else:
                normalized["value"] = codes[0]
        normalized_filters.append(normalized)

    plan["filters"] = normalized_filters
    return plan, issues, debug_rows


def _extract_filter_values(filter_row: Mapping[str, Any]) -> List[str]:
    if isinstance(filter_row.get("values"), list):
        return [str(v).strip() for v in list(filter_row.get("values") or []) if str(v).strip()]
    if filter_row.get("value") is None:
        return []
    value = str(filter_row.get("value") or "").strip()
    return [value] if value else []


def _looks_like_human_school_name_value(value: Any) -> bool:
    text = str(value or "").strip()
    if text == "":
        return False
    if text.isdigit():
        return False
    if not any(ch.isalpha() for ch in text):
        return False
    if re.fullmatch(r"[A-Z0-9_\-]{2,16}", text):
        return False
    return True


def _normalize_school_name_filters_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, dict)]
    if not filters:
        return plan, [], []
    if _prompt_explicitly_requests_school_key(prompt):
        return plan, [], []

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }

    school_name_key = ""
    for row in col_lookup.values():
        col_name = str(row.get("column_name") or "").strip().lower()
        if col_name == "school_name":
            school_name_key = _norm_key(row.get("column_key"))
            break
    if school_name_key == "":
        return plan, [], []

    debug_rows: List[Dict[str, Any]] = []
    normalized_filters: List[Dict[str, Any]] = []
    for row in filters:
        key = _norm_key(row.get("column_key"))
        meta = col_lookup.get(key) or {}
        col_name = str(meta.get("column_name") or "").strip().lower()
        if not _is_technical_school_key_name(col_name):
            normalized_filters.append(row)
            continue

        raw_values = _extract_filter_values(row)
        should_rewrite = len(raw_values) > 0 and all(_looks_like_human_school_name_value(v) for v in raw_values)
        debug_item: Dict[str, Any] = {
            "column_key": key,
            "column_name": col_name,
            "values": raw_values,
            "rewritten": False,
        }
        if not should_rewrite:
            normalized_filters.append(row)
            debug_rows.append(debug_item)
            continue

        rewritten = dict(row)
        rewritten["column_key"] = school_name_key
        normalized_filters.append(rewritten)
        debug_item["rewritten"] = True
        debug_item["rewritten_to_column_key"] = school_name_key
        debug_rows.append(debug_item)

    plan["filters"] = normalized_filters
    return plan, [], debug_rows


def _extract_staff_role_value_from_prompt(prompt: str) -> Optional[str]:
    text = str(prompt or "").strip()
    if text == "":
        return None

    matches: List[str] = []
    for match in _STAFF_ROLE_VALUE_RE.finditer(text):
        token = " ".join(str(match.group(1) or "").strip().lower().split())
        canonical = _STAFF_ROLE_CANONICAL.get(token)
        if canonical:
            matches.append(canonical)
    if not matches:
        return None

    unique_matches = list(dict.fromkeys(matches))
    if len(unique_matches) != 1:
        return None
    return unique_matches[0]


def _normalize_staff_role_filters_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    if _prompt_explicitly_requests_staff_classification(prompt):
        return plan, [], []

    role_value = _extract_staff_role_value_from_prompt(prompt)
    if role_value is None:
        return plan, [], []

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }
    if not col_lookup:
        return plan, [], []

    role_title_candidates: List[Tuple[int, str]] = []
    for key, row in col_lookup.items():
        col_name = str(row.get("column_name") or "").strip().lower()
        if not _is_staff_role_title_column_name(col_name):
            continue
        if row.get("filterable") is False:
            continue
        # Prefer canonical role-title columns when multiple are available.
        priority = 100 if col_name == "position_title" else 90 if col_name == "classroom_position" else 80
        role_title_candidates.append((priority, key))
    if not role_title_candidates:
        return plan, [], []

    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, dict)]
    debug_rows: List[Dict[str, Any]] = []
    for row in filters:
        key = _norm_key(row.get("column_key"))
        meta = col_lookup.get(key) or {}
        col_name = str(meta.get("column_name") or "").strip().lower()
        if _is_staff_role_title_column_name(col_name):
            debug_rows.append(
                {
                    "action": "skip_existing_role_filter",
                    "column_key": key,
                    "column_name": col_name,
                    "value": row.get("value"),
                }
            )
            return plan, [], debug_rows

    role_title_candidates.sort(key=lambda item: item[0], reverse=True)
    target_key = role_title_candidates[0][1]
    appended = {"column_key": target_key, "op": "=", "value": role_value}
    filters.append(appended)
    plan["filters"] = filters
    debug_rows.append({"action": "appended_role_filter", "column_key": target_key, "value": role_value})
    return plan, [], debug_rows


def _prompt_mentions_primary_school(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    return any(
        token in text
        for token in (
            "primary school",
            "primary-school",
            "is primary school",
            "primary flag",
        )
    )


def _prompt_mentions_grade_level_constraint(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    return any(
        token in text
        for token in (
            "grade level",
            "grades",
            "grade ",
            "pre-k",
            "prek",
            "prekindergarten",
            "p3",
            "p4",
        )
    )


def _normalize_adm_default_filters_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, dict)]
    if not filters:
        return plan, [], []
    if not _prompt_has_adm_intent(prompt):
        return plan, [], []

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }
    if not col_lookup:
        return plan, [], []

    has_person_name_filter = False
    for row in filters:
        key = _norm_key(row.get("column_key"))
        col_name = str((col_lookup.get(key) or {}).get("column_name") or "").strip().lower()
        if col_name in {"first_name", "last_name"}:
            has_person_name_filter = True
            break
    if not has_person_name_filter:
        return plan, [], []

    preserve_primary_filter = _prompt_mentions_primary_school(prompt)
    preserve_grade_level_filter = _prompt_mentions_grade_level_constraint(prompt)
    debug_rows: List[Dict[str, Any]] = []
    normalized_filters: List[Dict[str, Any]] = []

    for row in filters:
        key = _norm_key(row.get("column_key"))
        col_name = str((col_lookup.get(key) or {}).get("column_name") or "").strip().lower()
        if col_name == "is_primary_school" and not preserve_primary_filter:
            debug_rows.append(
                {
                    "action": "dropped_default_filter",
                    "column_key": key,
                    "column_name": col_name,
                    "reason": "person_specific_adm_prompt",
                }
            )
            continue
        if col_name == "grade_level_adm" and not preserve_grade_level_filter:
            debug_rows.append(
                {
                    "action": "dropped_default_filter",
                    "column_key": key,
                    "column_name": col_name,
                    "reason": "person_specific_adm_prompt",
                }
            )
            continue
        normalized_filters.append(row)

    plan["filters"] = normalized_filters
    return plan, [], debug_rows


def _normalize_relative_time_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str,
    domain_time_policy: Optional[Mapping[str, Any]] = None,
    today: Optional[date] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    time_block = dict(plan.get("time") or {}) if isinstance(plan.get("time"), dict) else {}
    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, Mapping)]
    prompt_norm = normalize_plan_prompt(prompt)
    policy = _normalize_domain_time_policy(domain_time_policy)
    if not bool(policy.get("allow_relative_ranges", True)):
        return plan, [], []

    relative_token = _resolve_relative_time_token(
        prompt_norm=prompt_norm,
        time_block=time_block,
        filters=filters,
        relative_map=policy.get("relative_map") if isinstance(policy.get("relative_map"), Mapping) else {},
    )
    if relative_token == "":
        return plan, [], []

    anchor = _policy_anchor_date(today=today, timezone_name=str(policy.get("timezone") or ""))
    start_date, end_date, relative_phrase = _compute_relative_range(
        token=relative_token,
        anchor=anchor,
        policy=policy,
    )

    if start_date is None or end_date is None:
        return plan, [], []

    time_column_key = _resolve_time_column_key_for_relative_range(
        explicit_time_column_key=time_block.get("time_column_key"),
        policy_default_time_column_key=policy.get("default_time_concept_key"),
        capabilities=capabilities,
    )
    if time_column_key == "":
        return plan, [], [{"action": "relative_time_skipped", "reason": "no_time_column_available"}]

    time_block["time_range"] = "custom"
    time_block["start_date"] = start_date.isoformat()
    time_block["end_date"] = end_date.isoformat()
    time_block["time_column_key"] = time_column_key
    if _norm_key(time_block.get("time_grain")) == "":
        default_grain = _norm_key(policy.get("default_grain"))
        if default_grain in {"day", "week", "month", "quarter", "year"}:
            time_block["time_grain"] = default_grain
        else:
            time_block["time_grain"] = _relative_time_grain(relative_token)
    plan["time"] = time_block

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, Mapping) and _norm_key(row.get("column_key"))
    }
    dropped_keys: List[str] = []
    normalized_filters: List[Dict[str, Any]] = []
    for row in filters:
        key = _norm_key(row.get("column_key"))
        column_name = str((col_lookup.get(key) or {}).get("column_name") or "").strip().lower()
        if _is_time_period_filter_value(row):
            dropped_keys.append(key or "(time_period)")
            continue
        if (
            _is_generic_month_column_name(column_name)
            or _is_generic_year_column_name(column_name)
            or _is_generic_quarter_column_name(column_name)
        ):
            dropped_keys.append(key)
            continue
        normalized_filters.append(row)
    plan["filters"] = normalized_filters

    debug_rows: List[Dict[str, Any]] = [
        {
            "action": "normalized_relative_time",
            "relative_token": relative_token,
            "relative_phrase": relative_phrase,
            "policy_calendar_mode": policy.get("calendar_mode"),
            "policy_timezone": policy.get("timezone"),
            "time_column_key": time_column_key,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "dropped_time_filters": dropped_keys,
        }
    ]
    return plan, [], debug_rows


def _normalize_year_keyword_filters_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    today: Optional[date] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, dict)]
    if not filters:
        return plan, [], []

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, Mapping) and _norm_key(row.get("column_key"))
    }
    if not col_lookup:
        return plan, [], []

    year_now = int((today or date.today()).year)
    debug_rows: List[Dict[str, Any]] = []
    normalized_filters: List[Dict[str, Any]] = []
    for row in filters:
        key = _norm_key(row.get("column_key"))
        col_name = str((col_lookup.get(key) or {}).get("column_name") or "").strip().lower()
        if not _is_generic_year_column_name(col_name):
            normalized_filters.append(row)
            continue
        if col_name == "school_year":
            normalized_filters.append(row)
            continue

        values = _extract_filter_values(row)
        if not values:
            normalized_filters.append(row)
            continue

        normalized_vals: List[int] = []
        changed = False
        for raw in values:
            token = _norm_key(raw)
            if token in {"current_year", "current year", "this_year", "this year"}:
                normalized_vals.append(year_now)
                changed = True
                continue
            if token in {"last_year", "last year", "previous_year", "previous year"}:
                normalized_vals.append(year_now - 1)
                changed = True
                continue
            if token.isdigit() and len(token) == 4:
                normalized_vals.append(int(token))
                changed = True
                continue
            normalized_vals = []
            changed = False
            break

        if not changed or not normalized_vals:
            normalized_filters.append(row)
            continue

        out_row = dict(row)
        op_norm = _norm_key(out_row.get("op"))
        if op_norm in {"in", "not_in"} or len(normalized_vals) > 1:
            out_row["op"] = "in" if op_norm in {"in", "eq", "equals", "="} else "not_in"
            out_row["values"] = normalized_vals
            out_row.pop("value", None)
        else:
            out_row["op"] = "eq" if op_norm in {"eq", "equals", "="} else out_row.get("op") or "eq"
            out_row["value"] = normalized_vals[0]
            out_row.pop("values", None)
        normalized_filters.append(out_row)
        debug_rows.append(
            {
                "action": "normalized_year_keyword",
                "column_key": key,
                "column_name": col_name,
                "original_values": values,
                "normalized_values": normalized_vals,
            }
        )

    plan["filters"] = normalized_filters
    return plan, [], debug_rows


def _is_generic_year_column_name(column_name: str) -> bool:
    token = str(column_name or "").strip().lower()
    if token == "":
        return False
    return token in {"year", "year_num", "calendar_year", "fiscal_year"} or token.endswith("_year")


def _is_generic_quarter_column_name(column_name: str) -> bool:
    token = str(column_name or "").strip().lower()
    if token == "":
        return False
    return token in {"quarter", "quarter_num", "fiscal_quarter", "calendar_quarter"} or token.endswith("_quarter")


def _normalize_top_bottom_ranking_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    prompt: str,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    prompt_norm = normalize_plan_prompt(prompt).lower()
    match = _TOP_BOTTOM_LIMIT_RE.search(prompt_norm)
    if match is None:
        return plan, [], []

    ranking_kind = str(match.group("kind") or "").strip().lower()
    try:
        requested_limit = int(match.group("limit") or 0)
    except Exception:
        requested_limit = 0
    if requested_limit <= 0:
        return plan, [], []
    requested_limit = min(requested_limit, 1000)

    grouping = dict(plan.get("grouping") or {}) if isinstance(plan.get("grouping"), Mapping) else {}
    grouping["limit"] = requested_limit

    selects = dict(plan.get("selects") or {}) if isinstance(plan.get("selects"), Mapping) else {}
    dimensions = [dict(item) for item in list(selects.get("dimensions") or []) if isinstance(item, Mapping)]
    metrics = [dict(item) for item in list(selects.get("metrics") or []) if isinstance(item, Mapping)]

    metric_ref = ""
    if metrics:
        metric_ref = _norm_key(metrics[0].get("metric_ref"))
    else:
        metric_ref = _pick_metric_ref_for_top_bottom(prompt_norm=prompt_norm, capabilities=capabilities)
        if metric_ref:
            metrics = [{"metric_ref": metric_ref}]
            selects["metrics"] = metrics
            plan["selects"] = selects

    if metrics and _norm_key(plan.get("intent")) != "aggregate":
        plan["intent"] = "aggregate"

    if len(list(grouping.get("group_by") or [])) == 0 and dimensions:
        grouping["group_by"] = [
            str(item.get("column_key") or "").strip()
            for item in dimensions
            if str(item.get("column_key") or "").strip()
        ]

    if metric_ref:
        metric_direction = "desc" if ranking_kind == "top" else "asc"
        grouping["order_by"] = [{"by": f"metric:{metric_ref}", "dir": metric_direction}]

    plan["grouping"] = grouping
    debug_rows = [
        {
            "action": "normalized_top_bottom_ranking",
            "kind": ranking_kind,
            "limit": requested_limit,
            "metric_ref": metric_ref,
        }
    ]
    return plan, [], debug_rows


def _pick_metric_ref_for_top_bottom(*, prompt_norm: str, capabilities: Mapping[str, Any]) -> str:
    domain_metrics = [dict(row) for row in list(capabilities.get("domain_metrics") or []) if isinstance(row, Mapping)]
    user_metrics = [dict(row) for row in list(capabilities.get("user_metrics") or []) if isinstance(row, Mapping)]
    overlay_metrics = [dict(row) for row in list(capabilities.get("overlay_metrics") or []) if isinstance(row, Mapping)]

    ranked: List[Tuple[int, str]] = []
    for row in domain_metrics:
        metric_key = _norm_key(row.get("metric_key"))
        if metric_key == "":
            continue
        metric_ref = f"domain_metric:{metric_key}"
        score = _score_metric_for_prompt(prompt_norm=prompt_norm, metric_key=metric_key, metric_label=row.get("label"))
        ranked.append((score, metric_ref))
    for row in user_metrics:
        metric_id = _norm_key(row.get("metric_id") or row.get("id"))
        if metric_id == "":
            continue
        metric_ref = f"user_metric:{metric_id}"
        score = _score_metric_for_prompt(prompt_norm=prompt_norm, metric_key=metric_id, metric_label=row.get("label"))
        ranked.append((score, metric_ref))
    for row in overlay_metrics:
        overlay_key = _norm_key(row.get("overlay_key"))
        if overlay_key == "":
            continue
        metric_ref = f"overlay:{overlay_key}"
        score = _score_metric_for_prompt(prompt_norm=prompt_norm, metric_key=overlay_key, metric_label=row.get("label"))
        ranked.append((score, metric_ref))

    if not ranked:
        return ""
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _score_metric_for_prompt(*, prompt_norm: str, metric_key: str, metric_label: Any) -> int:
    key = _norm_key(metric_key)
    label = _norm_key(metric_label)
    score = 0
    if "sales" in prompt_norm:
        if "sales_revenue" in key:
            score += 120
        if "sales" in key:
            score += 50
        if "revenue" in key:
            score += 60
    if "revenue" in prompt_norm and "revenue" in key:
        score += 60
    if "quota" in prompt_norm and "quota" in key:
        score += 60
    if "profit" in prompt_norm and "profit" in key:
        score += 60
    if "count" in prompt_norm and "count" in key:
        score += 40

    prompt_tokens = {tok for tok in re.split(r"[^a-z0-9]+", prompt_norm) if tok}
    key_tokens = {tok for tok in re.split(r"[^a-z0-9]+", key) if tok}
    label_tokens = {tok for tok in re.split(r"[^a-z0-9]+", label) if tok}
    overlap = len(prompt_tokens & (key_tokens | label_tokens))
    score += overlap * 5

    # If no signal is available, still allow deterministic fallback to first metric.
    if score == 0:
        score = 1
    return score


def _prompt_relative_month_phrase(prompt_norm: str) -> str:
    text = str(prompt_norm or "").strip().lower()
    if re.search(r"\b(last|previous)\s+month\b", text) is not None:
        return "last_month"
    if re.search(r"\b(this|current)\s+month\b", text) is not None:
        return "this_month"
    return ""


def _prompt_relative_year_phrase(prompt_norm: str) -> str:
    text = str(prompt_norm or "").strip().lower()
    if re.search(r"\b(last|previous)\s+year\b", text) is not None:
        return "last_year"
    if re.search(r"\b(this|current)\s+year\b", text) is not None:
        return "this_year"
    return ""


def _prompt_relative_quarter_phrase(prompt_norm: str) -> str:
    text = str(prompt_norm or "").strip().lower()
    if re.search(r"\b(last|previous)\s+fiscal\s+quarter\b", text) is not None:
        return "fiscal_last_quarter"
    if re.search(r"\b(this|current)\s+fiscal\s+quarter\b", text) is not None:
        return "fiscal_this_quarter"
    if re.search(r"\b(last|previous)\s+quarter\b", text) is not None:
        return "last_quarter"
    if re.search(r"\b(this|current)\s+quarter\b", text) is not None:
        return "this_quarter"
    return ""


def _canonical_relative_time_token(raw: Any) -> str:
    token = _norm_key(raw).replace("-", "_").replace(" ", "_")
    aliases = {
        "this_month": "this_month",
        "current_month": "this_month",
        "last_month": "last_month",
        "previous_month": "last_month",
        "this_year": "this_year",
        "current_year": "this_year",
        "last_year": "last_year",
        "previous_year": "last_year",
        "this_quarter": "this_quarter",
        "current_quarter": "this_quarter",
        "last_quarter": "last_quarter",
        "previous_quarter": "last_quarter",
        "fiscal_this_quarter": "fiscal_this_quarter",
        "this_fiscal_quarter": "fiscal_this_quarter",
        "current_fiscal_quarter": "fiscal_this_quarter",
        "fiscal_last_quarter": "fiscal_last_quarter",
        "last_fiscal_quarter": "fiscal_last_quarter",
        "previous_fiscal_quarter": "fiscal_last_quarter",
    }
    return aliases.get(token, "")


def _resolve_relative_time_token(
    *,
    prompt_norm: str,
    time_block: Mapping[str, Any],
    filters: Sequence[Mapping[str, Any]],
    relative_map: Mapping[str, Any],
) -> str:
    direct = _prompt_relative_quarter_phrase(prompt_norm)
    if direct == "":
        direct = _prompt_relative_month_phrase(prompt_norm)
    if direct == "":
        direct = _prompt_relative_year_phrase(prompt_norm)

    mapped = _resolve_relative_token_from_map(prompt_norm=prompt_norm, relative_map=relative_map)
    if mapped != "":
        return mapped
    if direct != "":
        return direct

    block_token = _canonical_relative_time_token(time_block.get("time_range"))
    if block_token != "":
        return block_token

    return _resolve_relative_token_from_filters(filters)


def _resolve_relative_token_from_map(*, prompt_norm: str, relative_map: Mapping[str, Any]) -> str:
    text = _norm_key(prompt_norm)
    if text == "" or not isinstance(relative_map, Mapping):
        return ""

    items: List[Tuple[str, str]] = []
    for raw_key, raw_value in dict(relative_map).items():
        key = _norm_key(raw_key)
        value = _canonical_relative_time_token(raw_value)
        if key == "" or value == "":
            continue
        items.append((key, value))
    if not items:
        return ""
    items.sort(key=lambda item: len(item[0]), reverse=True)
    for key, value in items:
        if text == key:
            return value
        pattern = rf"(^|[^a-z0-9]){re.escape(key)}($|[^a-z0-9])"
        if re.search(pattern, text) is not None:
            return value
    return ""


def _resolve_relative_token_from_filters(filters: Sequence[Mapping[str, Any]]) -> str:
    for row in filters:
        if not isinstance(row, Mapping):
            continue
        value = row.get("value")
        if isinstance(value, Mapping):
            token = _canonical_relative_time_token(value.get("time_range"))
            if token != "":
                return token
            period = _norm_key(value.get("time_period"))
            if period == "quarter":
                return "this_quarter"
            if period == "month":
                return "this_month"
            if period == "year":
                return "this_year"
        token = _canonical_relative_time_token(row.get("value"))
        if token != "":
            return token
        for item in list(row.get("values") or []):
            token = _canonical_relative_time_token(item)
            if token != "":
                return token
    return ""


def _relative_time_grain(relative_token: str) -> str:
    token = _canonical_relative_time_token(relative_token)
    if token.endswith("_quarter"):
        return "quarter"
    if token.endswith("_year"):
        return "year"
    return "month"


def _normalize_domain_time_policy(policy: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "calendar_mode": "calendar",
        "fiscal_year_start_month": None,
        "timezone": None,
        "default_time_concept_key": None,
        "allow_relative_ranges": True,
        "default_grain": None,
        "relative_map": {},
    }
    if not isinstance(policy, Mapping):
        return out
    calendar_mode = _norm_key(policy.get("calendar_mode"))
    if calendar_mode in {"calendar", "fiscal"}:
        out["calendar_mode"] = calendar_mode
    fiscal_month = _to_int(policy.get("fiscal_year_start_month"))
    if fiscal_month is not None and 1 <= fiscal_month <= 12:
        out["fiscal_year_start_month"] = fiscal_month
    timezone_name = str(policy.get("timezone") or "").strip()
    out["timezone"] = timezone_name or None
    default_time_key = _norm_key(policy.get("default_time_concept_key"))
    out["default_time_concept_key"] = default_time_key or None
    if "allow_relative_ranges" in policy:
        out["allow_relative_ranges"] = bool(policy.get("allow_relative_ranges"))
    default_grain = _norm_key(policy.get("default_grain"))
    if default_grain in {"day", "week", "month", "quarter", "year"}:
        out["default_grain"] = default_grain
    rel = policy.get("relative_map")
    if isinstance(rel, Mapping):
        out["relative_map"] = {str(k): str(v) for k, v in dict(rel).items()}
    return out


def _policy_anchor_date(*, today: Optional[date], timezone_name: str) -> date:
    if today is not None:
        return today
    tz = str(timezone_name or "").strip()
    if tz:
        try:
            return datetime.now(ZoneInfo(tz)).date()
        except Exception:
            pass
    return date.today()


def _compute_relative_range(
    *,
    token: str,
    anchor: date,
    policy: Mapping[str, Any],
) -> Tuple[Optional[date], Optional[date], str]:
    canonical_token = _canonical_relative_time_token(token)
    if canonical_token == "":
        return None, None, ""

    if canonical_token == "last_month":
        this_month_start = date(anchor.year, anchor.month, 1)
        end_date = this_month_start - timedelta(days=1)
        start_date = date(end_date.year, end_date.month, 1)
        return start_date, end_date, "last month"
    if canonical_token == "this_month":
        start_date = date(anchor.year, anchor.month, 1)
        return start_date, anchor, "this month"

    calendar_mode = _norm_key(policy.get("calendar_mode"))
    fiscal_start = _to_int(policy.get("fiscal_year_start_month"))
    use_fiscal_quarter = canonical_token in {"fiscal_this_quarter", "fiscal_last_quarter"} or (
        canonical_token in {"this_quarter", "last_quarter"}
        and calendar_mode == "fiscal"
        and fiscal_start is not None
        and 1 <= fiscal_start <= 12
    )

    if canonical_token in {"this_quarter", "fiscal_this_quarter"}:
        start_date, quarter_end = _current_quarter_range(anchor=anchor, use_fiscal=use_fiscal_quarter, fiscal_start_month=fiscal_start)
        del quarter_end
        return start_date, anchor, "this quarter"
    if canonical_token in {"last_quarter", "fiscal_last_quarter"}:
        start_date, end_date = _last_quarter_range(anchor=anchor, use_fiscal=use_fiscal_quarter, fiscal_start_month=fiscal_start)
        return start_date, end_date, "last quarter"

    use_fiscal_year = calendar_mode == "fiscal" and fiscal_start is not None and 1 <= fiscal_start <= 12
    if canonical_token == "this_year":
        if use_fiscal_year:
            start_date = _fiscal_year_start_for_date(anchor=anchor, fiscal_start_month=int(fiscal_start))
            return start_date, anchor, "this year"
        return date(anchor.year, 1, 1), anchor, "this year"
    if canonical_token == "last_year":
        if use_fiscal_year:
            fy_start = _fiscal_year_start_for_date(anchor=anchor, fiscal_start_month=int(fiscal_start))
            start_date = _add_months(fy_start, -12)
            end_date = fy_start - timedelta(days=1)
            return start_date, end_date, "last year"
        return date(anchor.year - 1, 1, 1), date(anchor.year - 1, 12, 31), "last year"

    return None, None, ""


def _fiscal_year_start_for_date(*, anchor: date, fiscal_start_month: int) -> date:
    if anchor.month >= fiscal_start_month:
        return date(anchor.year, fiscal_start_month, 1)
    return date(anchor.year - 1, fiscal_start_month, 1)


def _current_quarter_range(
    *,
    anchor: date,
    use_fiscal: bool,
    fiscal_start_month: Optional[int],
) -> Tuple[date, date]:
    if use_fiscal and fiscal_start_month is not None and 1 <= fiscal_start_month <= 12:
        fy_start = _fiscal_year_start_for_date(anchor=anchor, fiscal_start_month=fiscal_start_month)
        months_since_fy = (anchor.year - fy_start.year) * 12 + (anchor.month - fy_start.month)
        quarter_index = max(0, months_since_fy // 3)
        quarter_start = _add_months(fy_start, quarter_index * 3)
        quarter_end = _add_months(quarter_start, 3) - timedelta(days=1)
        return quarter_start, quarter_end

    quarter_start_month = ((anchor.month - 1) // 3) * 3 + 1
    quarter_start = date(anchor.year, quarter_start_month, 1)
    quarter_end = _add_months(quarter_start, 3) - timedelta(days=1)
    return quarter_start, quarter_end


def _last_quarter_range(
    *,
    anchor: date,
    use_fiscal: bool,
    fiscal_start_month: Optional[int],
) -> Tuple[date, date]:
    current_q_start, _ = _current_quarter_range(
        anchor=anchor,
        use_fiscal=use_fiscal,
        fiscal_start_month=fiscal_start_month,
    )
    last_q_start = _add_months(current_q_start, -3)
    last_q_end = current_q_start - timedelta(days=1)
    return last_q_start, last_q_end


def _add_months(base: date, months: int) -> date:
    month_index = (base.month - 1) + int(months)
    year = base.year + (month_index // 12)
    month = (month_index % 12) + 1
    return date(year, month, 1)


def _is_generic_month_column_name(column_name: str) -> bool:
    token = str(column_name or "").strip().lower()
    if token == "":
        return False
    return token in {"month", "month_num", "month_number", "report_month", "calendar_month_num"} or token.endswith("_month")


def _best_time_column_key_for_relative_range(*, capabilities: Mapping[str, Any]) -> str:
    best_key = ""
    best_score = -1
    rows: List[Tuple[int, Mapping[str, Any]]] = []
    for row in list(capabilities.get("time_columns") or []):
        if isinstance(row, Mapping):
            rows.append((3, row))
    for row in list(capabilities.get("filter_columns") or []):
        if isinstance(row, Mapping):
            rows.append((2, row))
    for row in list(capabilities.get("dimensions") or []):
        if isinstance(row, Mapping):
            rows.append((1, row))

    for source_weight, row in rows:
        key = _norm_key(row.get("column_key"))
        if key == "":
            continue
        column_name = str(row.get("column_name") or "").strip().lower()
        data_type = str(row.get("data_type") or "").strip().lower()
        score = source_weight * 100
        if column_name in {"date_key", "date", "order_date", "transaction_date", "sales_date", "invoice_date"}:
            score += 200
        if "date" in column_name:
            score += 80
        if "time" in column_name or column_name.endswith("_at"):
            score += 40
        if data_type in {"date", "datetime", "timestamp"}:
            score += 50
        if score > best_score:
            best_score = score
            best_key = key
    return best_key


def _resolve_time_column_key_for_relative_range(
    *,
    explicit_time_column_key: Any,
    policy_default_time_column_key: Any,
    capabilities: Mapping[str, Any],
) -> str:
    valid_keys = {
        _norm_key(row.get("column_key"))
        for row in (
            list(capabilities.get("time_columns") or [])
            + list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
        )
        if isinstance(row, Mapping) and _norm_key(row.get("column_key"))
    }

    explicit_key = _norm_key(explicit_time_column_key)
    if explicit_key and explicit_key in valid_keys:
        return explicit_key

    policy_key = _norm_key(policy_default_time_column_key)
    if policy_key and policy_key in valid_keys:
        return policy_key

    return _best_time_column_key_for_relative_range(capabilities=capabilities)


def _is_time_period_filter_value(filter_row: Mapping[str, Any]) -> bool:
    value = filter_row.get("value")
    if isinstance(value, Mapping):
        if _norm_key(value.get("type")) == "time_period":
            return True
        if _canonical_relative_time_token(value.get("time_range")) != "":
            return True
    for item in list(filter_row.get("values") or []):
        if _canonical_relative_time_token(item) != "":
            return True
    return False


def _normalize_school_year_filters_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    today: Optional[date] = None,
    school_year_start_month: int = QF_SCHOOL_YEAR_START_MONTH,
    school_year_end_month: int = QF_SCHOOL_YEAR_END_MONTH,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, dict)]
    if not filters:
        return plan, [], []

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }

    debug_rows: List[Dict[str, Any]] = []
    normalized_filters: List[Dict[str, Any]] = []
    for row in filters:
        key = _norm_key(row.get("column_key"))
        col_meta = col_lookup.get(key) or {}
        if not is_school_year_column(col_meta):
            normalized_filters.append(row)
            continue

        raw_values = _extract_filter_values(row)
        years = normalize_school_year_values(
            raw_values,
            today=today,
            school_year_start_month=school_year_start_month,
            school_year_end_month=school_year_end_month,
        )
        debug_rows.append(
            {
                "column_key": key,
                "original": raw_values,
                "normalized": years,
            }
        )
        if not years:
            normalized_filters.append(row)
            continue

        op_norm = str(row.get("op") or "").strip().lower()
        normalized = dict(row)
        if op_norm in {"in", "not_in"}:
            normalized["values"] = years
            normalized.pop("value", None)
        elif op_norm in {"eq", "equals", "="}:
            normalized["op"] = "eq"
            if len(years) == 1:
                normalized["value"] = years[0]
                normalized.pop("values", None)
            else:
                normalized["op"] = "in"
                normalized["values"] = years
                normalized.pop("value", None)
        elif op_norm in {"ne", "!=", "not_equals"}:
            normalized["op"] = "ne"
            if len(years) == 1:
                normalized["value"] = years[0]
                normalized.pop("values", None)
            else:
                normalized["op"] = "not_in"
                normalized["values"] = years
                normalized.pop("value", None)
        else:
            if "values" in normalized:
                normalized["values"] = years
                normalized.pop("value", None)
            else:
                normalized["value"] = years[0]
        normalized_filters.append(normalized)

    plan["filters"] = normalized_filters
    return plan, [], debug_rows


def _normalize_semester_filters_in_plan(
    *,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    today: Optional[date] = None,
    semester_indicator_columns: Optional[Mapping[str, str]] = None,
    spring_label: str = QF_SEMESTER_SPRING_LABEL,
    fall_label: str = QF_SEMESTER_FALL_LABEL,
    year_round_label: str = QF_SEMESTER_YEAR_ROUND_LABEL,
    spring_month_range: Tuple[int, int] = (QF_SEMESTER_SPRING_START_MONTH, QF_SEMESTER_SPRING_END_MONTH),
    fall_month_range: Tuple[int, int] = (QF_SEMESTER_FALL_START_MONTH, QF_SEMESTER_FALL_END_MONTH),
    year_round_month_range: Tuple[int, int] = (QF_SEMESTER_YEAR_ROUND_START_MONTH, QF_SEMESTER_YEAR_ROUND_END_MONTH),
) -> Tuple[Dict[str, Any], List[Dict[str, str]], List[Dict[str, Any]]]:
    plan = dict(plan_json or {})
    filters = [dict(item) for item in list(plan.get("filters") or []) if isinstance(item, dict)]
    if not filters:
        return plan, [], []

    col_lookup = {
        _norm_key(row.get("column_key")): dict(row)
        for row in (
            list(capabilities.get("filter_columns") or [])
            + list(capabilities.get("dimensions") or [])
            + list(capabilities.get("time_columns") or [])
        )
        if isinstance(row, dict) and _norm_key(row.get("column_key"))
    }

    debug_rows: List[Dict[str, Any]] = []
    indicator_lookup = {
        str(bucket or "").strip().lower(): _norm_key(column_key)
        for bucket, column_key in dict(semester_indicator_columns or {}).items()
        if str(bucket or "").strip() and _norm_key(column_key)
    }
    if not indicator_lookup:
        indicator_lookup = _infer_semester_indicator_columns_from_capabilities(capabilities=capabilities)

    normalized_filters: List[Dict[str, Any]] = []
    for row in filters:
        key = _norm_key(row.get("column_key"))
        col_meta = col_lookup.get(key) or {}
        if not is_semester_column(col_meta):
            normalized_filters.append(row)
            continue

        raw_values = _extract_filter_values(row)
        terms = normalize_semester_values(
            raw_values,
            today=today,
            spring_label=spring_label,
            fall_label=fall_label,
            year_round_label=year_round_label,
            spring_month_range=spring_month_range,
            fall_month_range=fall_month_range,
            year_round_month_range=year_round_month_range,
        )
        debug_rows.append(
            {
                "column_key": key,
                "original": raw_values,
                "normalized": terms,
                "rewritten_to_indicator": False,
            }
        )
        if not terms:
            normalized_filters.append(row)
            continue

        op_norm = str(row.get("op") or "").strip().lower()
        normalized = dict(row)
        if len(terms) == 1:
            bucket = _semester_bucket_from_text(terms[0])
            indicator_key = indicator_lookup.get(bucket or "")
            if indicator_key and op_norm in {"in", "not_in", "eq", "equals", "=", "ne", "!=", "not_equals"}:
                normalized["column_key"] = indicator_key
                if op_norm in {"not_in", "ne", "!=", "not_equals"}:
                    normalized["op"] = "ne"
                else:
                    normalized["op"] = "eq"
                normalized["value"] = True
                normalized.pop("values", None)
                debug_rows[-1]["rewritten_to_indicator"] = True
                debug_rows[-1]["indicator_column_key"] = indicator_key
                debug_rows[-1]["indicator_bucket"] = bucket
                normalized_filters.append(normalized)
                continue

        if op_norm in {"in", "not_in"}:
            normalized["values"] = terms
            normalized.pop("value", None)
        elif op_norm in {"eq", "equals", "="}:
            normalized["op"] = "eq"
            if len(terms) == 1:
                normalized["value"] = terms[0]
                normalized.pop("values", None)
            else:
                normalized["op"] = "in"
                normalized["values"] = terms
                normalized.pop("value", None)
        elif op_norm in {"ne", "!=", "not_equals"}:
            normalized["op"] = "ne"
            if len(terms) == 1:
                normalized["value"] = terms[0]
                normalized.pop("values", None)
            else:
                normalized["op"] = "not_in"
                normalized["values"] = terms
                normalized.pop("value", None)
        else:
            if "values" in normalized:
                normalized["values"] = terms
                normalized.pop("value", None)
            else:
                normalized["value"] = terms[0]
        normalized_filters.append(normalized)

    plan["filters"] = normalized_filters
    return plan, [], debug_rows


def _infer_semester_indicator_columns_from_capabilities(
    *,
    capabilities: Mapping[str, Any],
) -> Dict[str, str]:
    rows = list(capabilities.get("filter_columns") or []) + list(capabilities.get("dimensions") or []) + list(
        capabilities.get("time_columns") or []
    )
    best: Dict[str, Tuple[float, str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("filterable") is False:
            continue
        column_key = _norm_key(row.get("column_key"))
        column_name = str(row.get("column_name") or "").strip().lower()
        if column_key == "" or column_name == "":
            continue

        bucket = _semester_bucket_from_text(column_name)
        if bucket == "":
            continue

        score = 0.0
        if column_name.startswith("is_"):
            score += 3.0
        if "block" in column_name:
            score += 1.5
        if "semester" in column_name or "term" in column_name:
            score += 1.0
        semantic_type = str(row.get("semantic_type") or "").strip().lower()
        if semantic_type in {"flag", "boolean"}:
            score += 1.0
        data_type = str(row.get("data_type") or "").strip().lower()
        if any(token in data_type for token in ("bool", "bit", "tinyint")):
            score += 0.5

        current = best.get(bucket)
        if current is None or score > current[0]:
            best[bucket] = (score, column_key)
    return {bucket: value for bucket, (_score, value) in best.items() if value}


def _semester_bucket_from_text(value: Any) -> str:
    raw = str(value or "").strip()
    if raw == "":
        return ""
    upper = raw.upper().replace("-", "_").replace(" ", "_")
    for bucket, concept_keys in _SEMESTER_BUCKET_CONCEPT_KEYS.items():
        if upper in concept_keys:
            return bucket

    token = raw.lower()
    if token == "":
        return ""
    normalized = token.replace("-", "_").replace(" ", "_")
    if any(marker in normalized for marker in ("year_round", "yearround", "yr_round", "yrround")):
        return "year_round"
    if "spring" in normalized or "sping" in normalized:
        return "spring"
    if "fall" in normalized or "autumn" in normalized:
        return "fall"
    return ""


def _build_plan_explanation(
    *,
    selected_domain_id: int,
    plan_json: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    domain_candidates: Sequence[Mapping[str, Any]],
    ranking_debug: Sequence[Mapping[str, Any]],
    shortlisted_columns: Sequence[Mapping[str, Any]],
    country_debug: Sequence[Mapping[str, Any]],
    school_year_debug: Sequence[Mapping[str, Any]],
    semester_debug: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    selected_domain_name = str(plan_json.get("domain_name") or "").strip()
    if selected_domain_name == "":
        selected_domain_name = _selected_domain_name(
            domain_candidates=domain_candidates,
            selected_domain_id=selected_domain_id,
        )

    selected_ranking = None
    for row in ranking_debug:
        if _to_int((row or {}).get("domain_id")) == int(selected_domain_id):
            selected_ranking = dict(row)
            break

    score = float((selected_ranking or {}).get("score") or 0.0)
    vector_score = float((selected_ranking or {}).get("vector_score") or 0.0)
    shortlist_count = int((selected_ranking or {}).get("column_shortlist_count") or len(list(shortlisted_columns or [])))

    dim_rows = list((plan_json.get("selects") or {}).get("dimensions") or [])
    metric_rows = list((plan_json.get("selects") or {}).get("metrics") or [])
    filter_rows = list(plan_json.get("filters") or [])
    col_lookup = _explanation_column_lookup(capabilities=capabilities)

    shortlist_keys = {
        _norm_key(row.get("column_key")) for row in list(shortlisted_columns or []) if isinstance(row, Mapping)
    }
    dim_details: List[Dict[str, Any]] = []
    for item in dim_rows:
        key = _norm_key((item or {}).get("column_key"))
        if key == "":
            continue
        dim_details.append(
            {
                "column_key": key,
                "label": _column_label_for_explanation(column_key=key, col_lookup=col_lookup),
                "reason": (
                    "This field closely matched the wording in your question."
                    if key in shortlist_keys
                    else "This field helps answer your question and is available for this dataset."
                ),
            }
        )

    metric_details: List[Dict[str, Any]] = []
    domain_metric_lookup = {
        _norm_key(row.get("metric_key")): dict(row)
        for row in list(capabilities.get("domain_metrics") or [])
        if isinstance(row, Mapping) and _norm_key(row.get("metric_key"))
    }
    for item in metric_rows:
        metric_ref = _norm_key((item or {}).get("metric_ref"))
        if metric_ref == "":
            continue
        label = str(item.get("label") or "").strip()
        detail: Dict[str, Any] = {"metric_ref": metric_ref, "label": label or metric_ref}
        if metric_ref.startswith("domain_metric:"):
            key = metric_ref.split(":", 1)[1].strip()
            metric_meta = domain_metric_lookup.get(key) or {}
            detail["label"] = str(metric_meta.get("label") or detail["label"]).strip() or detail["label"]
            detail["reason"] = "This metric matches a summary/count style question."
        elif metric_ref.startswith("overlay:"):
            detail["reason"] = "This metric is a derived measure that best fits your request."
        elif metric_ref.startswith("user_metric:"):
            detail["reason"] = "This metric comes from your workspace-defined metric library."
        else:
            detail["reason"] = "This metric was selected because it best fits your question."
        metric_details.append(detail)

    filter_details: List[Dict[str, Any]] = []
    for item in filter_rows:
        if not isinstance(item, Mapping):
            continue
        key = _norm_key(item.get("column_key"))
        if key == "":
            continue
        op = str(item.get("op") or "").strip().lower()
        detail: Dict[str, Any] = {
            "column_key": key,
            "label": _column_label_for_explanation(column_key=key, col_lookup=col_lookup),
            "op": op,
            "op_label": _friendly_filter_op(op),
            "reason": "This condition came directly from your question.",
        }
        if "value" in item:
            detail["value"] = item.get("value")
        if "values" in item:
            detail["values"] = item.get("values")
        filter_details.append(detail)

    normalization_notes: List[str] = []
    if list(country_debug or []):
        normalization_notes.append("Country values were standardized (for example, US to United States).")
    if list(school_year_debug or []):
        normalization_notes.append("School-year phrases were converted to the actual school year.")
    if list(semester_debug or []):
        rewrite_count = sum(1 for row in semester_debug if bool((row or {}).get("rewritten_to_indicator")))
        if rewrite_count > 0:
            normalization_notes.append("Semester terms were mapped to your semester indicator fields.")
        else:
            normalization_notes.append("Semester terms were standardized to your configured semester labels.")

    summary_parts = [
        f"I used the '{selected_domain_name}' area because it was the best match for your question.",
    ]
    dim_labels = [str(item.get("label") or "").strip() for item in dim_details if str(item.get("label") or "").strip()]
    if dim_labels:
        summary_parts.append(f"I selected {_human_list(dim_labels)} for the output columns.")
    metric_labels = [str(item.get("label") or "").strip() for item in metric_details if str(item.get("label") or "").strip()]
    if metric_labels:
        summary_parts.append(f"I used {_human_list(metric_labels)} as the metric calculation.")
    filter_phrases = [_friendly_filter_clause(item) for item in filter_details]
    filter_phrases = [item for item in filter_phrases if item]
    if filter_phrases:
        summary_parts.append(f"I applied these conditions: {_human_list(filter_phrases)}.")
    if normalization_notes:
        summary_parts.extend(normalization_notes)

    return {
        "summary": " ".join(summary_parts),
        "domain": {
            "selected_domain_id": int(selected_domain_id),
            "selected_domain_name": selected_domain_name,
            "score": round(score, 5),
            "vector_score": round(vector_score, 5),
            "column_shortlist_count": shortlist_count,
            "reason": "Best overall match to your request, based on intent, wording, and available fields.",
        },
        "dimensions": dim_details,
        "metrics": metric_details,
        "filters": filter_details,
    }


def _explanation_column_lookup(*, capabilities: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    rows = list(capabilities.get("dimensions") or []) + list(capabilities.get("filter_columns") or []) + list(
        capabilities.get("time_columns") or []
    )
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "":
            continue
        out[key] = dict(row)
    return out


def _column_label_for_explanation(*, column_key: str, col_lookup: Mapping[str, Mapping[str, Any]]) -> str:
    row = dict(col_lookup.get(_norm_key(column_key)) or {})
    label = str(row.get("label") or "").strip()
    if label:
        return label
    column_name = str(row.get("column_name") or "").strip()
    if column_name:
        return _humanize_token(column_name)
    token = str(column_key or "").strip()
    if "." in token:
        token = token.split(".", 1)[1]
    return _humanize_token(token or "field")


def _friendly_filter_op(op: str) -> str:
    mapping = {
        "=": "is",
        "==": "is",
        "eq": "is",
        "equals": "is",
        "!=": "is not",
        "<>": "is not",
        "ne": "is not",
        "not_equals": "is not",
        "in": "is one of",
        "not_in": "is not one of",
        "contains": "contains",
        "like": "contains",
        "starts_with": "starts with",
        "ends_with": "ends with",
        "gt": "is greater than",
        "gte": "is at least",
        "lt": "is less than",
        "lte": "is at most",
        "is_null": "is blank",
        "is_not_null": "is filled in",
    }
    return mapping.get(str(op or "").strip().lower(), "matches")


def _friendly_filter_clause(item: Mapping[str, Any]) -> str:
    label = str(item.get("label") or "").strip() or "field"
    op_label = str(item.get("op_label") or "").strip() or "matches"
    op = str(item.get("op") or "").strip().lower()
    if op in {"is_null", "is_not_null"}:
        return f"{label} {op_label}"

    if isinstance(item.get("values"), list):
        values = [str(v).strip() for v in list(item.get("values") or []) if str(v).strip()]
        if values:
            return f"{label} {op_label} {_human_list(values)}"
    if "value" in item and item.get("value") is not None:
        value = str(item.get("value")).strip()
        if value:
            return f"{label} {op_label} {value}"
    return f"{label} {op_label}"


def _humanize_token(value: str) -> str:
    words = [tok for tok in str(value or "").replace("_", " ").split() if tok]
    if not words:
        return ""
    return " ".join(word.capitalize() for word in words)


def _human_list(values: Sequence[str]) -> str:
    items = [str(v).strip() for v in list(values or []) if str(v).strip()]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _normalize_explanation_summary(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    if text == "":
        return ""
    if len(text) > 600:
        text = text[:600].rstrip()
    return text


def _next_action_capability_payload(*, capabilities: Mapping[str, Any]) -> Dict[str, Any]:
    dims = [dict(row) for row in list(capabilities.get("dimensions") or []) if isinstance(row, Mapping)]
    time_columns = [dict(row) for row in list(capabilities.get("time_columns") or []) if isinstance(row, Mapping)]
    filter_columns = [dict(row) for row in list(capabilities.get("filter_columns") or []) if isinstance(row, Mapping)]

    dim_rows: List[Dict[str, Any]] = []
    seen_dim_keys: set[str] = set()
    for row in dims + time_columns:
        key = _norm_key(row.get("column_key"))
        if key == "" or key in seen_dim_keys:
            continue
        seen_dim_keys.add(key)
        dim_rows.append(
            {
                "column_key": key,
                "label": str(row.get("label") or "").strip(),
                "data_type": str(row.get("data_type") or "").strip().lower(),
            }
        )

    filter_rows: List[Dict[str, Any]] = []
    seen_filter_keys: set[str] = set()
    for row in filter_columns:
        if row.get("filterable") is False:
            continue
        key = _norm_key(row.get("column_key"))
        if key == "" or key in seen_filter_keys:
            continue
        seen_filter_keys.add(key)
        filter_rows.append(
            {
                "column_key": key,
                "label": str(row.get("label") or "").strip(),
                "data_type": str(row.get("data_type") or "").strip().lower(),
            }
        )

    metric_catalog: List[Dict[str, Any]] = []
    for row in list(capabilities.get("domain_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("metric_key"))
        if key:
            metric_catalog.append(
                {
                    "metric_ref": f"domain_metric:{key}",
                    "label": str(row.get("label") or "").strip(),
                }
            )
    for row in list(capabilities.get("user_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("metric_id") or row.get("id"))
        if key:
            metric_catalog.append(
                {
                    "metric_ref": f"user_metric:{key}",
                    "label": str(row.get("label") or "").strip(),
                }
            )
    for row in list(capabilities.get("overlay_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("overlay_key"))
        if key:
            metric_catalog.append(
                {
                    "metric_ref": f"overlay:{key}",
                    "label": str(row.get("label") or "").strip(),
                }
            )

    return {
        "allowed_dimensions": dim_rows[:80],
        "allowed_filter_columns": filter_rows[:80],
        "allowed_metric_refs": [str(row.get("metric_ref") or "") for row in metric_catalog],
        "metric_catalog": metric_catalog,
    }


def _next_action_plan_context(*, plan_json: Mapping[str, Any]) -> Dict[str, Any]:
    selects = plan_json.get("selects") or {}
    return {
        "intent": str(plan_json.get("intent") or "").strip().lower() or "list",
        "dimensions": [
            _norm_key((row or {}).get("column_key"))
            for row in list(selects.get("dimensions") or [])
            if isinstance(row, Mapping) and _norm_key((row or {}).get("column_key"))
        ],
        "metrics": [
            _norm_key((row or {}).get("metric_ref"))
            for row in list(selects.get("metrics") or [])
            if isinstance(row, Mapping) and _norm_key((row or {}).get("metric_ref"))
        ],
        "filters": [
            {
                "column_key": _norm_key(row.get("column_key")),
                "op": str(row.get("op") or "").strip().lower(),
                "value": row.get("value"),
                "values": row.get("values"),
            }
            for row in list(plan_json.get("filters") or [])
            if isinstance(row, Mapping) and _norm_key(row.get("column_key"))
        ],
    }


def _allowed_metric_refs_from_capabilities(*, capabilities: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for row in list(capabilities.get("domain_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("metric_key"))
        if key:
            out.add(f"domain_metric:{key}")
    for row in list(capabilities.get("user_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("metric_id") or row.get("id"))
        if key:
            out.add(f"user_metric:{key}")
    for row in list(capabilities.get("overlay_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("overlay_key"))
        if key:
            out.add(f"overlay:{key}")
    return out


def _normalize_next_actions(
    *,
    actions: Sequence[Any],
    original_prompt: str,
    capabilities: Mapping[str, Any],
    max_items: int,
) -> List[Dict[str, Any]]:
    allowed_dim_keys = {
        _norm_key(row.get("column_key"))
        for row in list(capabilities.get("dimensions") or []) + list(capabilities.get("time_columns") or [])
        if isinstance(row, Mapping) and _norm_key(row.get("column_key"))
    }
    allowed_filter_keys = {
        _norm_key(row.get("column_key"))
        for row in list(capabilities.get("filter_columns") or [])
        if isinstance(row, Mapping) and row.get("filterable") is not False and _norm_key(row.get("column_key"))
    }
    dim_key_by_column_name = _unique_allowed_key_by_column_name(allowed_dim_keys)
    filter_key_by_column_name = _unique_allowed_key_by_column_name(allowed_filter_keys)
    allowed_metric_refs = _allowed_metric_refs_from_capabilities(capabilities=capabilities)

    out: List[Dict[str, Any]] = []
    seen_prompts: set[str] = set()
    source_prompt = " ".join(str(original_prompt or "").strip().lower().split())
    for raw in list(actions or []):
        normalized = _normalize_next_action_item(
            item=raw,
            allowed_dim_keys=allowed_dim_keys,
            dim_key_by_column_name=dim_key_by_column_name,
            allowed_filter_keys=allowed_filter_keys,
            filter_key_by_column_name=filter_key_by_column_name,
            allowed_metric_refs=allowed_metric_refs,
        )
        if normalized is None:
            continue
        prompt_key = " ".join(str(normalized.get("prompt") or "").strip().lower().split())
        if prompt_key == "" or prompt_key in seen_prompts or prompt_key == source_prompt:
            continue
        seen_prompts.add(prompt_key)
        out.append(normalized)
        if len(out) >= max_items:
            break
    return out


def _normalize_next_action_item(
    *,
    item: Any,
    allowed_dim_keys: set[str],
    dim_key_by_column_name: Mapping[str, str],
    allowed_filter_keys: set[str],
    filter_key_by_column_name: Mapping[str, str],
    allowed_metric_refs: set[str],
) -> Optional[Dict[str, Any]]:
    if not isinstance(item, Mapping):
        return None

    label = _normalize_next_action_text(item.get("label"), max_len=80)
    prompt = _normalize_next_action_text(item.get("prompt"), max_len=220)
    reason = _normalize_next_action_text(item.get("reason"), max_len=220)
    if not label or not prompt or not reason:
        return None

    intent = _normalize_next_action_intent(item.get("intent"))
    confidence = _normalize_next_action_confidence(item.get("confidence"))

    dimensions: List[str] = []
    for raw in list(item.get("dimensions") or []):
        key = _repair_allowed_key(
            key=_norm_key(raw),
            allowed_keys=allowed_dim_keys,
            unique_key_by_column_name=dim_key_by_column_name,
        )
        if key == "":
            continue
        if key not in dimensions:
            dimensions.append(key)

    metrics: List[str] = []
    for raw in list(item.get("metrics") or []):
        if isinstance(raw, Mapping):
            token = _norm_key(raw.get("metric_ref"))
        else:
            token = _norm_key(raw)
        if token == "":
            continue
        if token not in allowed_metric_refs:
            continue
        if token not in metrics:
            metrics.append(token)

    filters: List[Dict[str, Any]] = []
    for raw in list(item.get("filters") or []):
        if not isinstance(raw, Mapping):
            continue
        key = _repair_allowed_key(
            key=_norm_key(raw.get("column_key")),
            allowed_keys=allowed_filter_keys,
            unique_key_by_column_name=filter_key_by_column_name,
        )
        if key == "":
            continue
        op = _normalize_next_action_filter_op(raw.get("op"))
        if op == "":
            continue
        row: Dict[str, Any] = {"column_key": key, "op": op}
        values = raw.get("values")
        value = raw.get("value")
        if op in {"in", "not_in"}:
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                cleaned = [v for v in list(values) if v is not None]
            elif value is not None:
                cleaned = [value]
            else:
                cleaned = []
            if not cleaned:
                continue
            row["values"] = cleaned[:20]
        elif op in {"is_null", "is_not_null"}:
            pass
        elif value is not None:
            row["value"] = value
        elif isinstance(values, Sequence) and not isinstance(values, (str, bytes)) and list(values):
            row["value"] = list(values)[0]
        else:
            continue
        filters.append(row)

    if intent == "aggregate" and not metrics:
        return None
    if not dimensions and not metrics and not filters:
        return None

    return {
        "label": label,
        "prompt": prompt,
        "reason": reason,
        "intent": intent,
        "confidence": confidence,
        "dimensions": dimensions,
        "metrics": metrics,
        "filters": filters,
    }


def _column_name_from_key(key: Any) -> str:
    token = _norm_key(key)
    if token == "" or "." not in token:
        return ""
    return token.split(".", 1)[1]


def _unique_allowed_key_by_column_name(allowed_keys: Sequence[str]) -> Dict[str, str]:
    by_name: Dict[str, set[str]] = {}
    for raw_key in allowed_keys:
        key = _norm_key(raw_key)
        col_name = _column_name_from_key(key)
        if key == "" or col_name == "":
            continue
        by_name.setdefault(col_name, set()).add(key)
    return {
        col_name: sorted(keys)[0]
        for col_name, keys in by_name.items()
        if len(keys) == 1
    }


def _repair_allowed_key(
    *,
    key: str,
    allowed_keys: set[str],
    unique_key_by_column_name: Mapping[str, str],
) -> str:
    if key == "":
        return ""
    if key in allowed_keys:
        return key
    col_name = _column_name_from_key(key)
    if col_name == "":
        return ""
    return _norm_key(unique_key_by_column_name.get(col_name))


def _normalize_next_action_text(value: Any, *, max_len: int) -> str:
    text = " ".join(str(value or "").strip().split())
    if text == "":
        return ""
    if len(text) > max_len:
        text = text[:max_len].rstrip()
    return text


def _normalize_next_action_intent(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"aggregate", "agg", "summary"}:
        return "aggregate"
    if token in {"trend", "timeseries", "time_series", "time-series"}:
        return "trend"
    return "list"


def _normalize_next_action_confidence(value: Any) -> float:
    try:
        number = float(value)
    except Exception:
        number = 0.7
    if number < 0.0:
        number = 0.0
    if number > 1.0:
        number = 1.0
    return round(number, 2)


def _normalize_next_action_filter_op(value: Any) -> str:
    token = str(value or "").strip().lower().replace(" ", "_")
    alias = {
        "not_equals": "ne",
        "equals": "eq",
        "notin": "not_in",
        "isnull": "is_null",
        "isnotnull": "is_not_null",
    }.get(token, token)
    if alias not in _NEXT_ACTION_ALLOWED_FILTER_OPS:
        return ""
    return alias


__all__ = ["PlannerDomainService", "normalize_plan_prompt"]
