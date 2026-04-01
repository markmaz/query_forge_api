from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase

PLANNER_PROMPT_INTENT_ACTION_KEYS = frozenset(
    {
        "list_students",
        "aggregate_students",
        "list_schools",
        "aggregate_schools",
        "mention_students",
        "mention_schools",
        "district_terms",
        "subgroup_terms",
        "nativity_terms",
        "calendar_days_off_terms",
        "age_extreme_terms",
        "birth_month_terms",
        "name_constraint_terms",
        "explicit_preferred_name_terms",
        "staff_work_hint",
        "student_attend_hint",
        "adm_hint",
        "city_state_abbr",
        "month_names",
        "time_phrases",
    }
)


def _normalize_text_list(values: list[str], *, lower: bool = False) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip()
        if not token:
            continue
        if lower:
            token = token.lower()
        if token not in out:
            out.append(token)
    return out


class PlannerPromptIntentPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    action_key: str = Field(min_length=1, max_length=128)
    regex_patterns: list[str] = Field(default_factory=list)
    substring_patterns: list[str] = Field(default_factory=list)
    state_codes: list[str] = Field(default_factory=list)

    @field_validator("action_key", mode="before")
    @classmethod
    def _normalize_action_key(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if token not in PLANNER_PROMPT_INTENT_ACTION_KEYS:
            raise ValueError(f"Unknown planner prompt-intent action: {value}")
        return token

    @field_validator("regex_patterns", "substring_patterns", "state_codes", mode="before")
    @classmethod
    def _normalize_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Prompt-intent rule fields must be lists")
        return _normalize_text_list([str(item) for item in value], lower=False)


class PlannerPromptIntentPolicyUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = Field(default=None, ge=1)
    policy_key: str = Field(min_length=1, max_length=150)
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    scope_type: str = Field(min_length=1, max_length=32)
    scope_workspace_id: Optional[str] = Field(default=None, max_length=128)
    scope_vertical_norm: Optional[str] = Field(default=None, max_length=64)
    priority: int = Field(default=100)
    is_active: bool = True
    stop_on_match: bool = False
    policy_json: PlannerPromptIntentPolicyRule

    @field_validator("policy_key", "name", "description", "scope_workspace_id", "scope_vertical_norm", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip()
        return token or None

    @field_validator("scope_type", mode="before")
    @classmethod
    def _normalize_scope_type(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if token not in {"global", "workspace"}:
            raise ValueError(f"Invalid scope_type: {value}")
        return token


class PlannerPromptIntentPolicy(SemanticBase):
    __tablename__ = "planner_prompt_intent_policy"
    __table_args__ = (
        UniqueConstraint("policy_key", "scope_workspace_id", "scope_vertical_norm", name="uidx_prompt_intent_policy_scope"),
        Index("idx_ppip_scope", "scope_workspace_id", "scope_vertical_norm"),
        Index("idx_ppip_priority", "priority"),
        Index("idx_ppip_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    policy_key: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_workspace_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    scope_vertical_norm: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    stop_on_match: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[Any] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
