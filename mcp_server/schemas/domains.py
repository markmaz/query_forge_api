from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import CapabilityFlags, WorkspaceScopedRequest


class SearchDomainsRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=25)


class DomainSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_key: str
    name: str
    description: Optional[str] = None
    confidence: float = 0.0
    reasons: List[str] = Field(default_factory=list)
    capabilities: CapabilityFlags = Field(default_factory=CapabilityFlags)


class SearchDomainsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domains: List[DomainSearchResult] = Field(default_factory=list)


class GetDomainProfileRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    domain_key: str = Field(min_length=1)


class DomainLabelValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str


class DomainProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_key: str
    name: str
    description: Optional[str] = None
    grain_notes: List[str] = Field(default_factory=list)
    supported_intents: List[str] = Field(default_factory=list)
    primary_entities: List[str] = Field(default_factory=list)
    time_fields: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    recommended_metrics: List[DomainLabelValue] = Field(default_factory=list)
    recommended_dimensions: List[DomainLabelValue] = Field(default_factory=list)
