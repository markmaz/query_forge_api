from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.domain.planner_rerank_policy import PLANNER_RERANK_SCOPE_TYPES, PLANNER_RERANK_SIGNAL_KEYS
from app.models.semantic.semantic_registry import SemanticBase

PLANNER_PROJECTION_MODES = frozenset({"prepend", "append"})


def _validate_known_signal_keys(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip()
        if token == "":
            continue
        if token not in PLANNER_RERANK_SIGNAL_KEYS:
            raise ValueError(f"Unknown planner projection signal: {token}")
        if token not in out:
            out.append(token)
    return out


def _validate_concept_keys(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip().upper()
        if token == "":
            continue
        if token not in out:
            out.append(token)
    return out


def _validate_column_names(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip().lower()
        if token == "":
            continue
        if token not in out:
            out.append(token)
    return out


class PlannerProjectionPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    when_signals_all: list[str] = Field(default_factory=list)
    when_signals_any: list[str] = Field(default_factory=list)
    exclude_signals_any: list[str] = Field(default_factory=list)
    projection_mode: str = Field(default="prepend", min_length=1, max_length=32)
    required_concept_keys: list[str] = Field(default_factory=list)
    excluded_concept_keys: list[str] = Field(default_factory=list)
    required_column_names: list[str] = Field(default_factory=list)
    excluded_column_names: list[str] = Field(default_factory=list)
    required_filter_concept_keys: list[str] = Field(default_factory=list)
    required_join_tables: list[str] = Field(default_factory=list)

    @field_validator("when_signals_all", "when_signals_any", "exclude_signals_any", mode="before")
    @classmethod
    def _normalize_signal_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Signal fields must be lists")
        return _validate_known_signal_keys([str(item) for item in value])

    @field_validator("required_concept_keys", "excluded_concept_keys", mode="before")
    @classmethod
    def _normalize_concept_key_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Concept key fields must be lists")
        return _validate_concept_keys([str(item) for item in value])

    @field_validator("required_column_names", "excluded_column_names", mode="before")
    @classmethod
    def _normalize_column_name_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Column name fields must be lists")
        return _validate_column_names([str(item) for item in value])

    @field_validator("required_filter_concept_keys", mode="before")
    @classmethod
    def _normalize_filter_concept_key_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("required_filter_concept_keys must be a list")
        return _validate_concept_keys([str(item) for item in value])

    @field_validator("required_join_tables", mode="before")
    @classmethod
    def _normalize_join_tables(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("required_join_tables must be a list")
        out: list[str] = []
        for raw in value:
            token = str(raw or "").strip().lower()
            if token and token not in out:
                out.append(token)
        return out

    @field_validator("projection_mode", mode="before")
    @classmethod
    def _normalize_projection_mode(cls, value: Any) -> str:
        token = str(value or "prepend").strip().lower()
        if token not in PLANNER_PROJECTION_MODES:
            raise ValueError(f"Invalid projection_mode: {value}")
        return token

    @model_validator(mode="after")
    def _validate_rule_shape(self) -> "PlannerProjectionPolicyRule":
        if not self.when_signals_all and not self.when_signals_any:
            raise ValueError("At least one signal matcher is required")
        if not any(
            (
                self.required_concept_keys,
                self.excluded_concept_keys,
                self.required_column_names,
                self.excluded_column_names,
                self.required_filter_concept_keys,
                self.required_join_tables,
            )
        ):
            raise ValueError("At least one projection policy action is required")
        return self


class PlannerProjectionPolicyUpsertRequest(BaseModel):
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
    policy_json: PlannerProjectionPolicyRule

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

    @model_validator(mode="after")
    def _validate_scope_shape(self) -> "PlannerProjectionPolicyUpsertRequest":
        if self.scope_type == "global":
            if any(value is not None for value in (self.scope_workspace_id, self.scope_base_domain_id)):
                raise ValueError("Global planner projection policies cannot declare workspace or domain scope.")
        elif self.scope_type == "workspace":
            if self.scope_base_domain_id is not None:
                raise ValueError("Workspace planner projection policies cannot declare domain scope.")
        elif self.scope_type == "global_domain":
            if self.scope_workspace_id is not None:
                raise ValueError("Global-domain planner projection policies cannot declare workspace scope.")
            if self.scope_base_domain_id is None:
                raise ValueError("Global-domain planner projection policies require scope_base_domain_id.")
        elif self.scope_type == "workspace_domain":
            if self.scope_base_domain_id is None:
                raise ValueError("Workspace-domain planner projection policies require scope_base_domain_id.")
        return self


class PlannerProjectionPolicy(SemanticBase):
    __tablename__ = "planner_projection_policy"
    __table_args__ = (
        UniqueConstraint(
            "policy_key",
            "scope_workspace_id",
            "scope_base_domain_id",
            name="uidx_projection_policy_scope",
        ),
        Index("idx_ppp_scope", "scope_workspace_id", "scope_base_domain_id"),
        Index("idx_ppp_priority", "priority"),
        Index("idx_ppp_active", "is_active"),
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
