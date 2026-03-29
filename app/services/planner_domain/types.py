"""Shared data types for the planner domain service."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    llm_id: Optional[int] = None

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
class LLMExecutionResult:
    slots_result: SlotExtractionResult
    slot_hints: Dict[str, Any]
    capabilities_llm: Dict[str, Any]
    llm_result: LLMPlanResult
    unified_trace: Dict[str, Any]
    timings: Dict[str, int]


@dataclass(frozen=True)
class PlanPostprocessResult:
    validated: Any
    llm_result: LLMPlanResult
    semantic_alias_debug: Any
    country_debug: List[Any]
    school_year_debug: List[Any]
    semester_debug: List[Any]
    school_name_debug: List[Any]
    staff_role_debug: List[Any]
    adm_default_debug: List[Any]
    district_county_retry_hint: str | None
    timings: Dict[str, int]


@dataclass(frozen=True)
class PlanEnrichmentResult:
    explanation: Dict[str, Any]
    explanation_summary_trace: Any
    next_actions: List[Any]
    next_actions_trace: Any
    next_actions_status: str


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
    llm_id: Optional[int] = None

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
