from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import ColumnSchema, WorkspaceScopedRequest

OwnerScope = Literal["user", "workspace", "global"]


class ListSavedQueriesRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    folder_id: Optional[str] = None


class SavedQueryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str
    name: str
    owner_scope: OwnerScope
    domain_key: Optional[str] = None
    updated_at: Optional[str] = None


class ListSavedQueriesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: List[SavedQueryItem] = Field(default_factory=list)


class RunSavedQueryRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1)
    limit: int = Field(default=100, ge=1, le=500)


class RunSavedQueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str
    columns: List[ColumnSchema] = Field(default_factory=list)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
