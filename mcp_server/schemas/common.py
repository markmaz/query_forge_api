from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceScopedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1)


class ToolErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class CapabilityFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supports_listing: bool = False
    supports_aggregate: bool = False
    supports_time_filtering: bool = False


class ExecutionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_limit: int
    timeout_seconds: int


class ColumnSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: Optional[str] = None
    label: Optional[str] = None


class ResourceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: List[Dict[str, Any]] = Field(default_factory=list)
