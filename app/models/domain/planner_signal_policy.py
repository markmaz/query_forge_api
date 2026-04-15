from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.domain.planner_rerank_policy import PLANNER_RERANK_SIGNAL_KEYS
from app.models.semantic.semantic_registry import SemanticBase

PLANNER_SIGNAL_MATCH_TYPES = frozenset({"regex", "regex_all", "substring_any", "helper", "school_literal"})
PLANNER_SIGNAL_HELPER_NAMES = frozenset(
    {
        "prompt_implies_staff_work_context",
        "prompt_implies_student_school_context",
        "prompt_has_adm_intent",
        "prompt_mentions_school_or_district",
        "prompt_has_city_state_pattern",
        "prompt_has_nativity",
        "prompt_has_name_constraint",
        "prompt_prefers_canonical_name_columns",
        "prompt_explicitly_requests_preferred_name",
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


def _validate_signal_keys(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip()
        if not token:
            continue
        if token not in PLANNER_RERANK_SIGNAL_KEYS:
            raise ValueError(f"Unknown planner signal key: {token}")
        if token not in out:
            out.append(token)
    return out


class PlannerSignalPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    signal_keys: list[str] = Field(default_factory=list)
    match_type: Literal["regex", "regex_all", "substring_any", "helper", "school_literal"]
    patterns: list[str] = Field(default_factory=list)
    helper_name: Optional[str] = None
    suffixes: list[str] = Field(default_factory=list)
    stopwords: list[str] = Field(default_factory=list)
    case_sensitive: bool = False

    @field_validator("signal_keys", mode="before")
    @classmethod
    def _normalize_signal_keys(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("signal_keys must be a list")
        return _validate_signal_keys([str(item) for item in value])

    @field_validator("patterns", "suffixes", "stopwords", mode="before")
    @classmethod
    def _normalize_patterns(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Pattern fields must be lists")
        return _normalize_text_list([str(item) for item in value], lower=False)

    @field_validator("helper_name", mode="before")
    @classmethod
    def _normalize_helper_name(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        token = str(value).strip()
        return token or None

    @field_validator("match_type", mode="before")
    @classmethod
    def _normalize_match_type(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if token not in PLANNER_SIGNAL_MATCH_TYPES:
            raise ValueError(f"Unknown planner signal match_type: {value}")
        return token

    @model_validator(mode="after")
    def _validate_shape(self) -> "PlannerSignalPolicyRule":
        if not self.signal_keys:
            raise ValueError("At least one signal key is required")
        if self.match_type in {"regex", "regex_all", "substring_any"} and not self.patterns:
            raise ValueError(f"{self.match_type} rules require patterns")
        if self.match_type == "helper":
            if not self.helper_name:
                raise ValueError("helper rules require helper_name")
            if self.helper_name not in PLANNER_SIGNAL_HELPER_NAMES:
                raise ValueError(f"Unknown signal helper: {self.helper_name}")
        if self.match_type == "school_literal" and not self.suffixes:
            raise ValueError("school_literal rules require suffixes")
        return self


class PlannerSignalPolicyUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = Field(default=None, ge=1)
    policy_key: str = Field(min_length=1, max_length=150)
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    scope_type: str = Field(min_length=1, max_length=32)
    scope_workspace_id: Optional[str] = Field(default=None, max_length=128)
    priority: int = Field(default=100)
    is_active: bool = True
    stop_on_match: bool = False
    policy_json: PlannerSignalPolicyRule

    @field_validator("policy_key", "name", "description", "scope_workspace_id", mode="before")
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


class PlannerSignalPolicy(SemanticBase):
    __tablename__ = "planner_signal_policy"
    __table_args__ = (
        UniqueConstraint("policy_key", "scope_workspace_id", name="uidx_signal_policy_scope"),
        Index("idx_psp_scope", "scope_workspace_id"),
        Index("idx_psp_priority", "priority"),
        Index("idx_psp_active", "is_active"),
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
