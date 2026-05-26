from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import WorkspaceScopedRequest


class FlowForgeListRunsRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    status: Optional[str] = None
    mode: Optional[str] = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class FlowForgeRunRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    run_id: int = Field(ge=1)


class FlowForgeLimitedRunRequest(FlowForgeRunRequest):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=100, ge=1, le=500)


class FlowForgeNeedsAttentionRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class FlowForgeResourceProfileRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    resource_set_id: int = Field(ge=1)
    snapshot_batch_id: int = Field(ge=1)
    source_record_key: str = Field(min_length=1)


class FlowForgeReportSummaryRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    mode: Optional[str] = None


class FlowForgeAddOperatorNoteRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    run_id: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=4000)
    idempotency_key: Optional[str] = None


class FlowForgeRunListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    status: Optional[str] = None
    mode: Optional[str] = None
    limit: int
    offset: int
    runs: List[Dict[str, Any]] = Field(default_factory=list)


class FlowForgeRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    run: Dict[str, Any]


class FlowForgeRunTimelineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    run_id: int
    limit: int
    events: List[Dict[str, Any]] = Field(default_factory=list)


class FlowForgeHumanTaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    run_id: int
    limit: int
    tasks: List[Dict[str, Any]] = Field(default_factory=list)


class FlowForgeResourceProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    resource_set_id: int
    snapshot_batch_id: int
    source_record_key: str
    record: Dict[str, Any]


class FlowForgeMatchingSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    policies: List[Dict[str, Any]] = Field(default_factory=list)


class FlowForgeReportSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    mode: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)


class FlowForgeOperatorNoteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    run_id: int
    event: Dict[str, Any]
