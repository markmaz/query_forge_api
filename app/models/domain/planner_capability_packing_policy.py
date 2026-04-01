from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.domain.planner_rerank_policy import PLANNER_RERANK_SCOPE_TYPES, PLANNER_RERANK_SIGNAL_KEYS
from app.models.semantic.semantic_registry import SemanticBase

PLANNER_CAPABILITY_PACKING_FEATURE_KEYS = frozenset(
    {
        "HAS_PREFERRED_STATE_COLUMN",
        "HAS_CANONICAL_NAME_COLUMNS",
    }
)


def _validate_known_signal_keys(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip()
        if token == "":
            continue
        if token not in PLANNER_RERANK_SIGNAL_KEYS:
            raise ValueError(f"Unknown planner capability packing signal: {token}")
        if token not in out:
            out.append(token)
    return out


def _validate_known_feature_keys(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip().upper()
        if token == "":
            continue
        if token not in PLANNER_CAPABILITY_PACKING_FEATURE_KEYS:
            raise ValueError(f"Unknown planner capability packing feature: {token}")
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


class PlannerCapabilityPackingPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    when_signals_all: list[str] = Field(default_factory=list)
    when_signals_any: list[str] = Field(default_factory=list)
    exclude_signals_any: list[str] = Field(default_factory=list)
    required_capability_features: list[str] = Field(default_factory=list)
    prepend_column_names: list[str] = Field(default_factory=list)
    append_column_names: list[str] = Field(default_factory=list)
    append_first_match_column_names: list[str] = Field(default_factory=list)
    excluded_column_names: list[str] = Field(default_factory=list)
    required_filter_column_names: list[str] = Field(default_factory=list)
    prefer_canonical_name_columns: bool = False
    include_name_constraint_columns: bool = False

    @field_validator("when_signals_all", "when_signals_any", "exclude_signals_any", mode="before")
    @classmethod
    def _normalize_signal_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Signal fields must be lists")
        return _validate_known_signal_keys([str(item) for item in value])

    @field_validator("required_capability_features", mode="before")
    @classmethod
    def _normalize_feature_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("required_capability_features must be a list")
        return _validate_known_feature_keys([str(item) for item in value])

    @field_validator(
        "prepend_column_names",
        "append_column_names",
        "append_first_match_column_names",
        "excluded_column_names",
        "required_filter_column_names",
        mode="before",
    )
    @classmethod
    def _normalize_column_name_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Column name fields must be lists")
        return _validate_column_names([str(item) for item in value])

    @model_validator(mode="after")
    def _validate_rule_shape(self) -> "PlannerCapabilityPackingPolicyRule":
        if not self.when_signals_all and not self.when_signals_any:
            raise ValueError("At least one signal matcher is required")
        if not any(
            (
                self.prepend_column_names,
                self.append_column_names,
                self.append_first_match_column_names,
                self.excluded_column_names,
                self.required_filter_column_names,
                self.prefer_canonical_name_columns,
                self.include_name_constraint_columns,
            )
        ):
            raise ValueError("At least one capability packing action is required")
        return self


class PlannerCapabilityPackingPolicyUpsertRequest(BaseModel):
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
    policy_json: PlannerCapabilityPackingPolicyRule

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


class PlannerCapabilityPackingPolicy(SemanticBase):
    __tablename__ = "planner_capability_packing_policy"
    __table_args__ = (
        UniqueConstraint(
            "policy_key",
            "scope_workspace_id",
            "scope_vertical_norm",
            name="uidx_capability_packing_policy_scope",
        ),
        Index("idx_pcpp_scope", "scope_workspace_id", "scope_vertical_norm"),
        Index("idx_pcpp_priority", "priority"),
        Index("idx_pcpp_active", "is_active"),
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
