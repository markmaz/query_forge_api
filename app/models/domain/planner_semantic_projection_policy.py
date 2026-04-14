from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase
from app.services.domain.policy_scope_service import GLOBAL_WORKSPACE_SCOPE_TYPES

PLANNER_SEMANTIC_PROJECTION_ACTION_KEYS = frozenset({"default_projection", "name_filter_concepts", "concept_family"})


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


class PlannerSemanticProjectionPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    action_key: str = Field(min_length=1, max_length=128)
    when_entity: Optional[str] = None
    when_concept_key: Optional[str] = None
    projection_concept_keys: list[str] = Field(default_factory=list)
    preferred_table_names: list[str] = Field(default_factory=list)
    concept_family: list[str] = Field(default_factory=list)

    @field_validator("action_key", mode="before")
    @classmethod
    def _normalize_action_key(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if token not in PLANNER_SEMANTIC_PROJECTION_ACTION_KEYS:
            raise ValueError(f"Unknown planner semantic projection action: {value}")
        return token

    @field_validator("when_entity", mode="before")
    @classmethod
    def _normalize_entity(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip().lower()
        return token or None

    @field_validator("when_concept_key", mode="before")
    @classmethod
    def _normalize_concept_key(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip().upper()
        return token or None

    @field_validator("projection_concept_keys", "concept_family", mode="before")
    @classmethod
    def _normalize_concept_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Concept lists must be lists")
        return _normalize_list([str(item) for item in value], upper=True)

    @field_validator("preferred_table_names", mode="before")
    @classmethod
    def _normalize_table_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Table lists must be lists")
        return _normalize_list([str(item) for item in value])

    @model_validator(mode="after")
    def _validate_shape(self) -> "PlannerSemanticProjectionPolicyRule":
        if self.action_key in {"default_projection", "name_filter_concepts"}:
            if not self.when_entity:
                raise ValueError("Entity-scoped projection rules require when_entity")
            if not self.projection_concept_keys:
                raise ValueError("Entity-scoped projection rules require projection_concept_keys")
        elif self.action_key == "concept_family":
            if not self.when_concept_key:
                raise ValueError("Concept-family rules require when_concept_key")
            if not self.concept_family:
                raise ValueError("Concept-family rules require concept_family")
        return self


class PlannerSemanticProjectionPolicyUpsertRequest(BaseModel):
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
    policy_json: PlannerSemanticProjectionPolicyRule

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


class PlannerSemanticProjectionPolicy(SemanticBase):
    __tablename__ = "planner_semantic_projection_policy"
    __table_args__ = (
        UniqueConstraint("policy_key", "scope_workspace_id", name="uidx_semantic_projection_policy_scope"),
        Index("idx_pspp_scope", "scope_workspace_id"),
        Index("idx_pspp_priority", "priority"),
        Index("idx_pspp_active", "is_active"),
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
    created_at: Mapped[Any] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[Any] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
