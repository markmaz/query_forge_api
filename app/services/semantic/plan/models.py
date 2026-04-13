from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.semantic.vertical_norm import normalize_semantic_vertical


class PlanningRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    vertical_norm: str = "generic"
    prompt: str
    domain_id: Optional[int] = None
    max_concepts: int = 12
    max_columns: int = 60
    debug: bool = False
    llm_id: Optional[int] = None

    @field_validator("vertical_norm", mode="before")
    @classmethod
    def _normalize_vertical_norm(cls, value: Any) -> str:
        return normalize_semantic_vertical(value)


class LLMSelectedColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_key: str
    model_column_id: int


class LLMFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_key: str
    op: str
    value: Any


class LLMPlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql_json: Dict[str, Any]
    selected_columns: List[LLMSelectedColumn] = Field(default_factory=list)
    filters: List[LLMFilter] = Field(default_factory=list)
    join_plan: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    notes: List[str] = Field(default_factory=list)


@dataclass
class SlotDrivenIntent:
    metric_terms: List[str] = field(default_factory=list)
    dimension_terms: List[str] = field(default_factory=list)
    subgroup_terms: List[str] = field(default_factory=list)
    time_terms: List[str] = field(default_factory=list)
    org_school_terms: List[str] = field(default_factory=list)
    org_district_terms: List[str] = field(default_factory=list)
    normalized_time: List[Any] = field(default_factory=list)

    def implies_count_metric(self, prompt: str) -> bool:
        text = str(prompt or "").strip().lower()
        explicit_count_patterns = (
            r"\bhow many\b",
            r"\bcount\b",
            r"\bnumber of\b",
            r"\btotal\b",
            r"\bdistinct\b",
            r"\bunique\b",
        )
        has_explicit_count_intent = any(re.search(pattern, text) is not None for pattern in explicit_count_patterns)
        is_row_listing_prompt = (
            re.search(r"\b(show|list|give|display|return)\b", text) is not None
            and re.search(r"\ball\b", text) is not None
            and re.search(r"\bby\b", text) is None
            and not has_explicit_count_intent
        )
        if is_row_listing_prompt:
            return False
        metric_blob = " ".join(self.metric_terms).lower()
        return (
            has_explicit_count_intent
            or "enrollment" in metric_blob
            or "student enrollment" in metric_blob
        )

    def allows_identifier_projection(self, prompt: str) -> bool:
        text = str(prompt or "").strip().lower()
        if re.search(r"\blist\b", text) is None:
            return False
        return re.search(r"\b(ids?|identifiers?|k_student|student id|student ids)\b", text) is not None
