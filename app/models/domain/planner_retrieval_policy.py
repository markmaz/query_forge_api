from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.domain.planner_rerank_policy import PLANNER_RERANK_SIGNAL_KEYS
from app.models.semantic.semantic_registry import SemanticBase

PLANNER_RETRIEVAL_QUERY_SOURCES = frozenset({"vector", "semantic_vector"})


def _validate_known_signal_keys(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip()
        if token == "":
            continue
        if token not in PLANNER_RERANK_SIGNAL_KEYS:
            raise ValueError(f"Unknown planner retrieval signal: {token}")
        if token not in out:
            out.append(token)
    return out


def _normalize_text_list(values: list[str], *, lower: bool = False, upper: bool = False) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw or "").strip()
        if token == "":
            continue
        if lower:
            token = token.lower()
        if upper:
            token = token.upper()
        if token not in out:
            out.append(token)
    return out


class PlannerRetrievalQuerySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    score_boost: float = Field(default=0.0, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    source: Literal["vector", "semantic_vector"] = "vector"

    @field_validator("query", mode="before")
    @classmethod
    def _normalize_query(cls, value: Any) -> str:
        token = " ".join(str(value or "").strip().split())
        if token == "":
            raise ValueError("query is required")
        return token

    @field_validator("reasons", mode="before")
    @classmethod
    def _normalize_reasons(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("reasons must be a list")
        return _normalize_text_list([str(item) for item in value])

    @field_validator("source", mode="before")
    @classmethod
    def _normalize_source(cls, value: Any) -> str:
        token = str(value or "vector").strip().lower()
        if token not in PLANNER_RETRIEVAL_QUERY_SOURCES:
            raise ValueError(f"Invalid retrieval query source: {value}")
        return token


class PlannerRetrievalPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    when_signals_all: list[str] = Field(default_factory=list)
    when_signals_any: list[str] = Field(default_factory=list)
    exclude_signals_any: list[str] = Field(default_factory=list)
    when_concept_key_patterns_any: list[str] = Field(default_factory=list)
    query_specs: list[PlannerRetrievalQuerySpec] = Field(default_factory=list)
    domain_name_prefer_tokens: list[str] = Field(default_factory=list)
    domain_name_avoid_tokens: list[str] = Field(default_factory=list)
    domain_name_positive_bias: float = Field(default=0.0, ge=0.0, le=1.0)
    domain_name_negative_bias: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("when_signals_all", "when_signals_any", "exclude_signals_any", mode="before")
    @classmethod
    def _normalize_signal_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Signal fields must be lists")
        return _validate_known_signal_keys([str(item) for item in value])

    @field_validator("when_concept_key_patterns_any", mode="before")
    @classmethod
    def _normalize_concept_key_patterns(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("when_concept_key_patterns_any must be a list")
        return _normalize_text_list([str(item) for item in value], upper=True)

    @field_validator("domain_name_prefer_tokens", "domain_name_avoid_tokens", mode="before")
    @classmethod
    def _normalize_domain_name_tokens(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Domain-name token fields must be lists")
        return _normalize_text_list([str(item) for item in value], lower=True)

    @model_validator(mode="after")
    def _validate_rule_shape(self) -> "PlannerRetrievalPolicyRule":
        if not self.when_signals_all and not self.when_signals_any and not self.when_concept_key_patterns_any:
            raise ValueError("At least one retrieval matcher is required")
        if not self.query_specs and not self.domain_name_prefer_tokens and not self.domain_name_avoid_tokens:
            raise ValueError("At least one retrieval policy action is required")
        if self.domain_name_prefer_tokens and self.domain_name_positive_bias <= 0.0:
            raise ValueError("domain_name_positive_bias must be > 0 when prefer tokens are configured")
        if self.domain_name_avoid_tokens and self.domain_name_negative_bias <= 0.0:
            raise ValueError("domain_name_negative_bias must be > 0 when avoid tokens are configured")
        return self


class PlannerRetrievalPolicyUpsertRequest(BaseModel):
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
    policy_json: PlannerRetrievalPolicyRule

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
        if token not in {"global", "workspace"}:
            raise ValueError(f"Invalid scope_type: {value}")
        return token


class PlannerRetrievalPolicy(SemanticBase):
    __tablename__ = "planner_retrieval_policy"
    __table_args__ = (
        UniqueConstraint(
            "policy_key",
            "scope_workspace_id",
            name="uidx_retrieval_policy_scope",
        ),
        Index("idx_prp_scope", "scope_workspace_id"),
        Index("idx_prp_priority", "priority"),
        Index("idx_prp_active", "is_active"),
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
