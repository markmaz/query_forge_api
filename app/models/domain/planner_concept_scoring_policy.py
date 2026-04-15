from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase
from app.services.domain.policy_scope_service import GLOBAL_WORKSPACE_SCOPE_TYPES

PLANNER_CONCEPT_SCORING_ACTION_KEYS = frozenset(
    {
        "entity_exact_match_multiplier",
        "entity_mismatch_multiplier",
        "student_entity_name_exact_multiplier",
        "student_entity_generic_name_multiplier",
        "student_cross_entity_name_multiplier",
        "student_subject_staff_name_multiplier",
        "student_subject_parent_name_multiplier",
        "staff_or_parent_subject_student_name_multiplier",
        "name_slot_student_name_multiplier",
        "name_slot_generic_name_multiplier",
        "school_slot_multiplier",
        "district_slot_multiplier",
        "grade_slot_multiplier",
        "race_slot_multiplier",
        "identifier_penalty_default",
        "identifier_penalty_subgroup",
        "identifier_limit",
    }
)


def _normalize_list(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip().lower()
        if token and token not in out:
            out.append(token)
    return out


class PlannerConceptScoringPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    when_context_all: list[str] = Field(default_factory=list)
    when_context_any: list[str] = Field(default_factory=list)
    exclude_context_any: list[str] = Field(default_factory=list)
    action_key: str = Field(min_length=1, max_length=128)
    factor_value: Optional[float] = Field(default=None, gt=0.0, le=5.0)
    penalty_value: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    integer_value: Optional[int] = Field(default=None, ge=0, le=10)

    @field_validator("when_context_all", "when_context_any", "exclude_context_any", mode="before")
    @classmethod
    def _normalize_context_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Context matchers must be lists")
        return _normalize_list([str(item) for item in value])

    @field_validator("action_key", mode="before")
    @classmethod
    def _normalize_action_key(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if token not in PLANNER_CONCEPT_SCORING_ACTION_KEYS:
            raise ValueError(f"Unknown planner concept scoring action: {value}")
        return token

    @model_validator(mode="after")
    def _validate_shape(self) -> "PlannerConceptScoringPolicyRule":
        if not self.when_context_all and not self.when_context_any:
            raise ValueError("At least one context matcher is required")
        if self.factor_value is None and self.penalty_value is None and self.integer_value is None:
            raise ValueError("Policy must define a factor, penalty, or integer value")
        return self


class PlannerConceptScoringPolicyUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = Field(default=None, ge=1)
    policy_key: str = Field(min_length=1, max_length=150)
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    scope_type: str = Field(min_length=1, max_length=32)
    scope_workspace_id: Optional[str] = Field(default=None, max_length=128)
    priority: int = Field(default=100)
    is_active: bool = True
    stop_on_match: bool = False
    policy_json: PlannerConceptScoringPolicyRule

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
        if token not in GLOBAL_WORKSPACE_SCOPE_TYPES:
            raise ValueError(f"Invalid scope_type: {value}")
        return token


class PlannerConceptScoringPolicy(SemanticBase):
    __tablename__ = "planner_concept_scoring_policy"
    __table_args__ = (
        UniqueConstraint(
            "policy_key",
            "scope_workspace_id",
            name="uidx_concept_scoring_policy_scope",
        ),
        Index("idx_pcsp_scope", "scope_workspace_id"),
        Index("idx_pcsp_priority", "priority"),
        Index("idx_pcsp_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    policy_key: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_workspace_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    stop_on_match: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    factor_value: Mapped[Optional[float]] = mapped_column(DECIMAL(6, 4), nullable=True)
    penalty_value: Mapped[Optional[float]] = mapped_column(DECIMAL(6, 4), nullable=True)
    integer_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[Any] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[Any] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
