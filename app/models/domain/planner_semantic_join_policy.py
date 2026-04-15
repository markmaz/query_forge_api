from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase
from app.services.domain.policy_scope_service import GLOBAL_WORKSPACE_SCOPE_TYPES

PLANNER_SEMANTIC_JOIN_POLICY_ACTION_KEYS = frozenset(
    {
        "filter_column_preference",
        "required_join",
    }
)


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


class PlannerSemanticJoinPreferenceStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_names: list[str] = Field(default_factory=list)
    table_prefixes: list[str] = Field(default_factory=list)
    column_names: list[str] = Field(default_factory=list)
    column_contains: list[str] = Field(default_factory=list)

    @field_validator("table_names", "table_prefixes", "column_names", "column_contains", mode="before")
    @classmethod
    def _normalize_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Preference matchers must be lists")
        return _normalize_list([str(item) for item in value])

    @model_validator(mode="after")
    def _validate_shape(self) -> "PlannerSemanticJoinPreferenceStep":
        if not self.table_names and not self.table_prefixes and not self.column_names and not self.column_contains:
            raise ValueError("Preference step must define at least one matcher")
        return self


class PlannerSemanticJoinPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    action_key: str = Field(min_length=1, max_length=128)
    when_filter_concept_keys_any: list[str] = Field(default_factory=list)
    when_selected_tables_all: list[str] = Field(default_factory=list)
    when_required_join_tables_any: list[str] = Field(default_factory=list)
    preference_steps: list[PlannerSemanticJoinPreferenceStep] = Field(default_factory=list)
    join_table: Optional[str] = None
    join_on_concept_key: Optional[str] = None
    primary_table: Optional[str] = None

    @field_validator("action_key", mode="before")
    @classmethod
    def _normalize_action_key(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if token not in PLANNER_SEMANTIC_JOIN_POLICY_ACTION_KEYS:
            raise ValueError(f"Unknown planner semantic join action: {value}")
        return token

    @field_validator("when_filter_concept_keys_any", mode="before")
    @classmethod
    def _normalize_concept_keys(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Concept matchers must be lists")
        return _normalize_list([str(item) for item in value], upper=True)

    @field_validator("when_selected_tables_all", "when_required_join_tables_any", mode="before")
    @classmethod
    def _normalize_tables(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Table matchers must be lists")
        return _normalize_list([str(item) for item in value])

    @field_validator("join_table", "primary_table", mode="before")
    @classmethod
    def _normalize_optional_table(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip().lower()
        return token or None

    @field_validator("join_on_concept_key", mode="before")
    @classmethod
    def _normalize_optional_concept(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip().upper()
        return token or None

    @model_validator(mode="after")
    def _validate_shape(self) -> "PlannerSemanticJoinPolicyRule":
        if self.action_key == "filter_column_preference":
            if not self.when_filter_concept_keys_any:
                raise ValueError("Filter-column preference rules require filter concept keys")
            if not self.preference_steps:
                raise ValueError("Filter-column preference rules require preference steps")
        elif self.action_key == "required_join":
            if not self.when_filter_concept_keys_any:
                raise ValueError("Required-join rules require filter concept keys")
            if not self.when_selected_tables_all:
                raise ValueError("Required-join rules require selected tables")
            if not self.when_required_join_tables_any:
                raise ValueError("Required-join rules require join table matchers")
            if not self.join_table or not self.join_on_concept_key:
                raise ValueError("Required-join rules require join table and join concept")
        return self


class PlannerSemanticJoinPolicyUpsertRequest(BaseModel):
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
    policy_json: PlannerSemanticJoinPolicyRule

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


class PlannerSemanticJoinPolicy(SemanticBase):
    __tablename__ = "planner_semantic_join_policy"
    __table_args__ = (
        UniqueConstraint(
            "policy_key",
            "scope_workspace_id",
            name="uidx_semantic_join_policy_scope",
        ),
        Index("idx_psjp_scope", "scope_workspace_id"),
        Index("idx_psjp_priority", "priority"),
        Index("idx_psjp_active", "is_active"),
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
