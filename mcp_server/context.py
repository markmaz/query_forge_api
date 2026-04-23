from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field


class RequestContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    allowed_domain_keys: List[str] = Field(default_factory=list)
    can_preview: bool = False
    can_run_saved_queries: bool = False
    trace_id: str = Field(min_length=1)
    effective_roles: List[str] = Field(default_factory=list)
    is_admin: bool = False
