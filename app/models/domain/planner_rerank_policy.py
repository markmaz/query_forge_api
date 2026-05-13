from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, Index, text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase

PLANNER_RERANK_SCOPE_TYPES = frozenset(
    {
        "global",
        "workspace",
        "global_domain",
        "workspace_domain",
    }
)

PLANNER_RERANK_SIGNAL_KEYS = frozenset(
    {
        "student_listing",
        "school_listing",
        "student_aggregate",
        "staff_listing",
        "staff_aggregate",
        "school_aggregate",
        "staff_work_context_prompt",
        "student_school_context_prompt",
        "adm_prompt",
        "age_extreme_prompt",
        "birth_month_prompt",
        "calendar_days_off_prompt",
        "workflow_intelligence_prompt",
        "workflow_run_count_prompt",
        "school_literal_present",
        "school_or_district_prompt",
        "city_state_prompt",
        "nativity_prompt",
        "name_constraint_prompt",
        "canonical_name_preference_prompt",
        "explicit_preferred_name_request",
        "explicit_school_key_request",
        "explicit_staff_classification_request",
        "district_literal_present",
        "time_constraint_present",
        "status_enrolled",
        "status_active",
        "subgroup_prompt",
        "program_prompt",
        "staff_role_prompt",
        "needs_student_identity",
        "needs_school_filter",
        "needs_enrollment_status",
        "needs_attendance_metric",
        "needs_grade_metric",
        "needs_program_membership",
        "listing_intent",
        "aggregate_intent",
        "grouped_aggregate",
    }
)

PLANNER_RERANK_CAPABILITY_KEYS = frozenset(
    {
        "STUDENT_IDENTITY",
        "BIRTH_DATE",
        "AGE",
        "STAFF_IDENTITY",
        "SCHOOL_IDENTITY",
        "SCHOOL_NAME",
        "CALENDAR_DATE",
        "SCHOOL_DAY_FLAG",
        "NON_INSTRUCTIONAL_DAY",
        "DISTRICT_NAME",
        "ENROLLMENT_STATUS",
        "PROGRAM_MEMBERSHIP",
        "STAFF_ROLE",
        "GRADE_LEVEL",
        "RACE_ETHNICITY",
        "GENDER",
        "STUDENT_COUNT",
        "ENROLLMENT_COUNT",
        "ATTENDANCE_RATE",
        "COURSE_GRADE",
        "DISCIPLINE_INCIDENT_COUNT",
    }
)

PLANNER_DOMAIN_CAPABILITY_SOURCE_TYPES = frozenset(
    {
        "semantic_concept",
        "metric",
        "dimension",
        "filter",
        "derived_condition",
        "heuristic_inference",
    }
)

PLANNER_DOMAIN_CAPABILITY_SUPPORT_LEVELS = frozenset({"direct", "derived", "partial"})
PLANNER_RERANK_CANDIDATE_SOURCE_TYPES = frozenset({"ai_recommendation", "manual", "trace_review"})
PLANNER_RERANK_CANDIDATE_REVIEW_STATUSES = frozenset({"pending", "approved", "rejected"})


def _validate_known_signal_keys(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip()
        if token == "":
            continue
        if token not in PLANNER_RERANK_SIGNAL_KEYS:
            raise ValueError(f"Unknown planner rerank signal: {token}")
        if token not in out:
            out.append(token)
    return out


def _validate_known_capability_keys(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip().upper()
        if token == "":
            continue
        if token not in PLANNER_RERANK_CAPABILITY_KEYS:
            raise ValueError(f"Unknown planner rerank capability: {token}")
        if token not in out:
            out.append(token)
    return out


class PlannerRerankPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    when_signals_all: list[str] = Field(default_factory=list)
    when_signals_any: list[str] = Field(default_factory=list)
    exclude_signals_any: list[str] = Field(default_factory=list)
    prefer_capabilities: list[str] = Field(default_factory=list)
    penalize_missing: list[str] = Field(default_factory=list)
    require_for_bonus: list[str] = Field(default_factory=list)
    boost: float = Field(default=0.0, ge=0.0, le=1.0)
    penalty: float = Field(default=0.0, ge=0.0, le=1.0)
    max_effect: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("when_signals_all", "when_signals_any", "exclude_signals_any", mode="before")
    @classmethod
    def _normalize_signal_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Signal fields must be lists")
        return _validate_known_signal_keys([str(item) for item in value])

    @field_validator("prefer_capabilities", "penalize_missing", "require_for_bonus", mode="before")
    @classmethod
    def _normalize_capability_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Capability fields must be lists")
        return _validate_known_capability_keys([str(item) for item in value])

    @model_validator(mode="after")
    def _validate_rule_shape(self) -> "PlannerRerankPolicyRule":
        if not self.when_signals_all and not self.when_signals_any:
            raise ValueError("At least one signal matcher is required")
        if self.boost == 0.0 and self.penalty == 0.0:
            raise ValueError("Policy must define a boost and/or penalty")
        return self


class PlannerRerankPolicyUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = Field(default=None, ge=1)
    policy_key: str = Field(min_length=1, max_length=150)
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    scope_type: str = Field(min_length=1, max_length=32)
    scope_workspace_id: Optional[str] = Field(default=None, max_length=128)
    scope_base_domain_id: Optional[int] = Field(default=None, ge=1)
    priority: int = Field(default=100)
    is_active: bool = True
    stop_on_match: bool = False
    policy_json: PlannerRerankPolicyRule

    @field_validator("policy_key", "name", "description", "scope_workspace_id", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text_value = str(value).strip()
        return text_value or None

    @field_validator("scope_type", mode="before")
    @classmethod
    def _normalize_scope_type(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if token not in PLANNER_RERANK_SCOPE_TYPES:
            raise ValueError(f"Invalid scope_type: {value}")
        return token


class PlannerDomainCapabilityUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = Field(default=None, ge=1)
    scope_type: str = Field(min_length=1, max_length=32)
    scope_workspace_id: Optional[str] = Field(default=None, max_length=128)
    base_domain_id: int = Field(ge=1)
    capability_key: str = Field(min_length=1, max_length=100)
    support_level: str = Field(default="direct", min_length=1, max_length=32)
    source_type: str = Field(default="semantic_concept", min_length=1, max_length=32)
    source_ref: Optional[str] = Field(default=None, max_length=255)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    notes: Optional[str] = None
    is_active: bool = True

    @field_validator("scope_workspace_id", "source_ref", "notes", mode="before")
    @classmethod
    def _clean_optional_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip()
        return token or None

    @field_validator("scope_type", mode="before")
    @classmethod
    def _normalize_capability_scope_type(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if token not in PLANNER_RERANK_SCOPE_TYPES:
            raise ValueError(f"Invalid scope_type: {value}")
        return token

    @field_validator("capability_key", mode="before")
    @classmethod
    def _normalize_capability_key_field(cls, value: Any) -> str:
        token = str(value or "").strip().upper()
        if token not in PLANNER_RERANK_CAPABILITY_KEYS:
            raise ValueError(f"Unknown planner rerank capability: {token}")
        return token

    @field_validator("support_level", mode="before")
    @classmethod
    def _normalize_support_level_field(cls, value: Any) -> str:
        token = str(value or "direct").strip().lower()
        if token not in PLANNER_DOMAIN_CAPABILITY_SUPPORT_LEVELS:
            raise ValueError(f"Invalid support_level: {value}")
        return token

    @field_validator("source_type", mode="before")
    @classmethod
    def _normalize_source_type_field(cls, value: Any) -> str:
        token = str(value or "semantic_concept").strip().lower()
        if token not in PLANNER_DOMAIN_CAPABILITY_SOURCE_TYPES:
            raise ValueError(f"Invalid source_type: {value}")
        return token


class PlannerRerankPolicyCandidateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = Field(default=None, ge=1)
    candidate_key: str = Field(min_length=1, max_length=150)
    source_type: str = Field(default="ai_recommendation", min_length=1, max_length=50)
    workspace_id: Optional[str] = Field(default=None, max_length=128)
    candidate_policy: PlannerRerankPolicyRule
    rationale_json: Optional[dict[str, Any]] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @field_validator("candidate_key", "workspace_id", mode="before")
    @classmethod
    def _clean_candidate_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip()
        return token or None

    @field_validator("source_type", mode="before")
    @classmethod
    def _normalize_candidate_source_type(cls, value: Any) -> str:
        token = str(value or "ai_recommendation").strip().lower()
        if token not in PLANNER_RERANK_CANDIDATE_SOURCE_TYPES:
            raise ValueError(f"Invalid source_type: {value}")
        return token


class PlannerRerankPolicyCandidateSuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=4000)
    expected_base_domain_id: int = Field(ge=1)
    observed_base_domain_id: Optional[int] = Field(default=None, ge=1)
    candidate_key: Optional[str] = Field(default=None, max_length=150)
    notes: Optional[str] = None
    llm_id: Optional[int] = Field(default=None, ge=1)

    @field_validator("prompt", "candidate_key", "notes", mode="before")
    @classmethod
    def _clean_suggest_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip()
        return token or None


class PlannerRerankPolicyCandidateSuggestionLLMResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    candidate_key: Optional[str] = Field(default=None, max_length=150)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    candidate_policy: PlannerRerankPolicyRule
    rationale: dict[str, Any] = Field(default_factory=dict)

    @field_validator("candidate_key", mode="before")
    @classmethod
    def _clean_suggestion_candidate_key(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip()
        return token or None

    @model_validator(mode="before")
    @classmethod
    def _normalize_rationale_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if "rationale" not in payload and isinstance(payload.get("rationale_json"), dict):
            payload["rationale"] = payload.get("rationale_json")
        return payload


class PlannerRerankPolicyCandidateApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    scope_type: str = Field(min_length=1, max_length=32)
    scope_workspace_id: Optional[str] = Field(default=None, max_length=128)
    scope_base_domain_id: Optional[int] = Field(default=None, ge=1)
    priority: int = Field(default=100)
    is_active: bool = True
    stop_on_match: bool = False
    policy_key: Optional[str] = Field(default=None, max_length=150)

    @field_validator("name", "description", "scope_workspace_id", "policy_key", mode="before")
    @classmethod
    def _clean_approval_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip()
        return token or None

    @field_validator("scope_type", mode="before")
    @classmethod
    def _normalize_approval_scope_type(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if token not in PLANNER_RERANK_SCOPE_TYPES:
            raise ValueError(f"Invalid scope_type: {value}")
        return token


class PlannerDomainCapabilityRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    capability_key: str
    support_level: str = "direct"
    source_type: str = "semantic_concept"
    source_ref: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    scope_type: Optional[str] = None

    @field_validator("capability_key", mode="before")
    @classmethod
    def _normalize_capability_key(cls, value: Any) -> str:
        token = str(value or "").strip().upper()
        if token not in PLANNER_RERANK_CAPABILITY_KEYS:
            raise ValueError(f"Unknown planner rerank capability: {token}")
        return token

    @field_validator("support_level", mode="before")
    @classmethod
    def _normalize_support_level(cls, value: Any) -> str:
        token = str(value or "direct").strip().lower()
        if token not in PLANNER_DOMAIN_CAPABILITY_SUPPORT_LEVELS:
            raise ValueError(f"Invalid support_level: {value}")
        return token

    @field_validator("source_type", mode="before")
    @classmethod
    def _normalize_source_type(cls, value: Any) -> str:
        token = str(value or "semantic_concept").strip().lower()
        if token not in PLANNER_DOMAIN_CAPABILITY_SOURCE_TYPES:
            raise ValueError(f"Invalid source_type: {value}")
        return token


class PlannerDomainCapability(SemanticBase):
    __tablename__ = "planner_domain_capability"
    __table_args__ = (
        UniqueConstraint(
            "base_domain_id",
            "capability_key",
            "scope_workspace_id",
            "source_ref",
            name="uidx_domain_capability_scope",
        ),
        Index("idx_pdc_domain", "base_domain_id"),
        Index("idx_pdc_capability", "capability_key"),
        Index("idx_pdc_scope", "scope_workspace_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_workspace_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    base_domain_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    capability_key: Mapped[str] = mapped_column(String(100), nullable=False)
    support_level: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'direct'"))
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'semantic_concept'"))
    source_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(DECIMAL(5, 4), nullable=False, server_default=text("1.0000"))
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )


class PlannerRerankPolicy(SemanticBase):
    __tablename__ = "planner_rerank_policy"
    __table_args__ = (
        UniqueConstraint(
            "policy_key",
            "scope_workspace_id",
            "scope_base_domain_id",
            name="uidx_rerank_policy_scope",
        ),
        Index("idx_prp_scope", "scope_workspace_id", "scope_base_domain_id"),
        Index("idx_prp_priority", "priority"),
        Index("idx_prp_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    policy_key: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_workspace_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    scope_base_domain_id: Mapped[Optional[int]] = mapped_column(BIGINT(unsigned=True), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    stop_on_match: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )


class PlannerRerankPolicyAudit(SemanticBase):
    __tablename__ = "planner_rerank_policy_audit"
    __table_args__ = (
        Index("idx_prpa_policy", "policy_id"),
        Index("idx_prpa_actor", "actor_user_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    policy_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_policy_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    new_policy_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    actor_user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class PlannerRerankPolicyCandidate(SemanticBase):
    __tablename__ = "planner_rerank_policy_candidate"
    __table_args__ = (
        Index("idx_prpc_status", "review_status"),
        Index("idx_prpc_scope", "workspace_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    candidate_key: Mapped[str] = mapped_column(String(150), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    candidate_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rationale_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    confidence: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(5, 4), nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'pending'"))
    approved_policy_id: Mapped[Optional[int]] = mapped_column(BIGINT(unsigned=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )


__all__ = [
    "PLANNER_DOMAIN_CAPABILITY_SOURCE_TYPES",
    "PLANNER_DOMAIN_CAPABILITY_SUPPORT_LEVELS",
    "PLANNER_RERANK_CAPABILITY_KEYS",
    "PLANNER_RERANK_CANDIDATE_REVIEW_STATUSES",
    "PLANNER_RERANK_CANDIDATE_SOURCE_TYPES",
    "PLANNER_RERANK_SCOPE_TYPES",
    "PLANNER_RERANK_SIGNAL_KEYS",
    "PlannerDomainCapability",
    "PlannerDomainCapabilityRecord",
    "PlannerDomainCapabilityUpsertRequest",
    "PlannerRerankPolicy",
    "PlannerRerankPolicyAudit",
    "PlannerRerankPolicyCandidate",
    "PlannerRerankPolicyCandidateApproveRequest",
    "PlannerRerankPolicyCandidateCreateRequest",
    "PlannerRerankPolicyCandidateSuggestRequest",
    "PlannerRerankPolicyCandidateSuggestionLLMResponse",
    "PlannerRerankPolicyRule",
    "PlannerRerankPolicyUpsertRequest",
]
