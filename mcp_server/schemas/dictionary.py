from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import WorkspaceScopedRequest

DictionaryItemType = Literal["column", "metric", "dimension", "filter"]


class SearchDictionaryRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    domain_key: Optional[str] = None
    types: List[DictionaryItemType] = Field(default_factory=lambda: ["column", "metric", "dimension", "filter"])
    limit: int = Field(default=20, ge=1, le=50)


class DictionarySearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: DictionaryItemType
    key: str
    label: str
    description: Optional[str] = None
    table: Optional[str] = None
    domain_key: Optional[str] = None
    confidence: float = 0.0
    aliases: List[str] = Field(default_factory=list)


class SearchDictionaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: List[DictionarySearchResult] = Field(default_factory=list)
