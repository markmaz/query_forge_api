from __future__ import annotations

import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator


class SemanticType(str, Enum):
    entity = "entity"
    identifier = "identifier"
    attribute = "attribute"
    geography = "geography"
    time = "time"
    metric = "metric"
    flag = "flag"
    reference = "reference"
    other = "other"


class ConceptSource(str, Enum):
    canonical = "canonical"
    fallback = "fallback"


class SemanticLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_key: str
    concept_source: ConceptSource
    canonical_match_confidence: float = Field(ge=0.0, le=1.0)
    semantic_type: SemanticType
    sub_type: Optional[str] = None
    entity: Optional[str] = None
    granularity_rank: int = 0
    filter_allowed: bool = True
    group_by_allowed: bool = True
    aggregation_allowed: bool = True
    is_identifier: bool = False
    is_metric: bool = False
    display_priority: int = 0
    sensitive: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_concept_source_constraints(self, info: ValidationInfo) -> "SemanticLLMOutput":
        key = normalize_concept_key(self.concept_key)
        if self.concept_source == ConceptSource.canonical:
            known = set((info.context or {}).get("known_concept_keys") or [])
            if known and key not in known:
                raise ValueError("canonical concept_key not in known list")
        if self.concept_source == ConceptSource.fallback:
            if not key:
                raise ValueError("fallback concept_key cannot be empty")
            if "." in key or "/" in key:
                raise ValueError("fallback concept_key cannot include . or /")
        return self


class BatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: List[SemanticLLMOutput]


_INVALID_CHARS = re.compile(r"[^A-Za-z0-9]+")
_MULTI_US = re.compile(r"_{2,}")


def normalize_concept_key(value: str) -> str:
    text = (value or "").strip()
    if "." in text:
        text = text.split(".")[-1]
    if "/" in text:
        text = text.split("/")[-1]
    text = _INVALID_CHARS.sub("_", text)
    text = text.upper()
    text = _MULTI_US.sub("_", text)
    text = text.strip("_")
    return text
