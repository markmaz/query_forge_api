from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.domain.planner_rerank_policy import PLANNER_RERANK_SCOPE_TYPES
from app.models.semantic.semantic_registry import SemanticBase

PLANNER_SEMANTIC_TIME_ACTION_KEYS = frozenset({"time_column_preference"})


def _normalize_list(values: list[str], *, upper: bool = False) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip()
        if not token:
            continue
        normalized = token.upper() if upper else token.lower()
        if normalized not in out:
            out.append(normalized)
    return out


class PlannerSemanticTimePolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    action_key: str = Field(min_length=1, max_length=128)
    when_domain_hint: str = Field(min_length=1, max_length=64)
    preferred_time_concept_key: str = Field(min_length=1, max_length=128)
    preferred_column_names: list[str] = Field(default_factory=list)

    @field_validator("action_key", mode="before")
    @classmethod
    def _normalize_action_key(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if token not in PLANNER_SEMANTIC_TIME_ACTION_KEYS:
            raise ValueError(f"Unknown planner semantic time action: {value}")
        return token

    @field_validator("when_domain_hint", mode="before")
    @classmethod
    def _normalize_domain_hint(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if not token:
            raise ValueError("when_domain_hint is required")
        return token

    @field_validator("preferred_time_concept_key", mode="before")
    @classmethod
    def _normalize_concept_key(cls, value: Any) -> str:
        token = str(value or "").strip().upper()
        if not token:
            raise ValueError("preferred_time_concept_key is required")
        return token

    @field_validator("preferred_column_names", mode="before")
    @classmethod
    def _normalize_column_names(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("preferred_column_names must be a list")
        return _normalize_list([str(item) for item in value])

    @model_validator(mode="after")
    def _validate_shape(self) -> "PlannerSemanticTimePolicyRule":
        if self.action_key == "time_column_preference" and not self.preferred_column_names:
            raise ValueError("Time column preference rules require preferred_column_names")
        return self


class PlannerSemanticTimePolicyUpsertRequest(BaseModel):
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
    policy_json: PlannerSemanticTimePolicyRule

    @field_validator("policy_key", "name", "description", "scope_workspace_id", "scope_vertical_norm", mode="before")
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


class PlannerSemanticTimePolicy(SemanticBase):
    __tablename__ = "planner_semantic_time_policy"
    __table_args__ = (
        UniqueConstraint("policy_key", "scope_workspace_id", "scope_vertical_norm", name="uidx_semantic_time_policy_scope"),
        Index("idx_pstp_scope", "scope_workspace_id", "scope_vertical_norm"),
        Index("idx_pstp_priority", "priority"),
        Index("idx_pstp_active", "is_active"),
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
