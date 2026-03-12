from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


PlannerIntent = Literal["aggregate", "list", "trend"]
PlannerFilterOperator = Literal["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "between", "contains"]
PlannerTimeGrain = Literal["day", "week", "month", "quarter", "year"]


class SemanticConceptCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_key: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=255)
    score: float = 0.0
    description: Optional[str] = None
    semantic_type: Optional[str] = None
    source_column_key: Optional[str] = None
    metric_ref: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    domain_key: Optional[str] = None

    @field_validator("concept_key", "label", mode="before")
    @classmethod
    def _normalize_required_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("description", "semantic_type", "source_column_key", "metric_ref", "domain_key", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> Optional[str]:
        text = str(value or "").strip()
        return text or None

    @field_validator("aliases", mode="before")
    @classmethod
    def _normalize_aliases(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        out: List[str] = []
        seen: set[str] = set()
        for raw in value:
            token = str(raw or "").strip()
            if token == "":
                continue
            key = token.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(token)
        return out

    @field_validator("score", mode="before")
    @classmethod
    def _clamp_score(cls, value: Any) -> float:
        try:
            number = float(value)
        except Exception:
            return 0.0
        return max(0.0, min(1.0, number))


class SemanticValueCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_concept_key: str = Field(min_length=1, max_length=160)
    alias_value: str = Field(min_length=1, max_length=255)
    canonical_value: Any = None
    score: float = 0.0

    @field_validator("field_concept_key", "alias_value", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("score", mode="before")
    @classmethod
    def _clamp_score(cls, value: Any) -> float:
        try:
            number = float(value)
        except Exception:
            return 0.0
        return max(0.0, min(1.0, number))


class SemanticRelationshipExpansion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_concept: str = Field(min_length=1, max_length=160)
    relationship_type: str = Field(min_length=1, max_length=100)
    to_concept: str = Field(min_length=1, max_length=160)

    @field_validator("from_concept", "relationship_type", "to_concept", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return str(value or "").strip()


class SemanticCandidatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    normalized_prompt: Optional[str] = None
    workspace_id: str
    vertical_norm: str = "generic"
    base_domain_id: int
    base_domain_key: Optional[str] = None
    domain: Optional[SemanticConceptCandidate] = None
    domain_candidates: List[SemanticConceptCandidate] = Field(default_factory=list)
    metric_candidates: List[SemanticConceptCandidate] = Field(default_factory=list)
    dimension_candidates: List[SemanticConceptCandidate] = Field(default_factory=list)
    filter_candidates: List[SemanticConceptCandidate] = Field(default_factory=list)
    time_candidates: List[SemanticConceptCandidate] = Field(default_factory=list)
    value_candidates: List[SemanticValueCandidate] = Field(default_factory=list)
    lexical_hints: Dict[str, List[str]] = Field(default_factory=dict)
    planning_rules: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("prompt", "normalized_prompt", "workspace_id", "base_domain_key", "vertical_norm", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("lexical_hints", mode="before")
    @classmethod
    def _normalize_lexical_hints(cls, value: Any) -> Dict[str, List[str]]:
        if not isinstance(value, dict):
            return {}
        out: Dict[str, List[str]] = {}
        for raw_key, raw_values in value.items():
            key = str(raw_key or "").strip().lower()
            if key == "":
                continue
            values: List[str] = []
            seen: set[str] = set()
            if isinstance(raw_values, list):
                for raw in raw_values:
                    token = str(raw or "").strip().upper()
                    if token == "" or token in seen:
                        continue
                    seen.add(token)
                    values.append(token)
            if values:
                out[key] = values
        return out

    @field_validator("planning_rules", mode="before")
    @classmethod
    def _normalize_planning_rules(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        out: List[str] = []
        seen: set[str] = set()
        for raw in value:
            token = str(raw or "").strip()
            if token == "":
                continue
            k = token.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(token)
        return out


class CompactSemanticFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_concept_key: str = Field(min_length=1, max_length=160)
    operator: PlannerFilterOperator
    value: Any = None

    @field_validator("field_concept_key", mode="before")
    @classmethod
    def _normalize_field_key(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("operator", mode="before")
    @classmethod
    def _normalize_operator(cls, value: Any) -> str:
        token = str(value or "").strip().lower()
        if token in {"=", "==", "equals"}:
            return "eq"
        if token in {"!=", "<>", "not_equals"}:
            return "neq"
        if token == "like":
            return "contains"
        return token


class CompactSemanticTime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_concept_key: Optional[str] = None
    time_range: Optional[str] = None
    time_grain: Optional[PlannerTimeGrain] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    @field_validator("time_concept_key", "time_range", "time_grain", "start_date", "end_date", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> Optional[str]:
        text = str(value or "").strip()
        return text or None


class CompactSemanticPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_domain_key: Optional[str] = None
    intent: PlannerIntent = "list"
    metrics: List[str] = Field(default_factory=list)
    dimensions: List[str] = Field(default_factory=list)
    filters: List[CompactSemanticFilter] = Field(default_factory=list)
    time: CompactSemanticTime = Field(default_factory=CompactSemanticTime)
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("base_domain_key", "clarification_question", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> Optional[str]:
        text = str(value or "").strip()
        return text or None

    @field_validator("metrics", "dimensions", mode="before")
    @classmethod
    def _normalize_keys(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            token = str(value or "").strip()
            return [token] if token else []
        out: List[str] = []
        seen: set[str] = set()
        for raw in value:
            token = str(raw or "").strip()
            if token == "":
                continue
            key = token.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(token)
        return out

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: Any) -> float:
        try:
            number = float(value)
        except Exception:
            return 0.0
        return max(0.0, min(1.0, number))
