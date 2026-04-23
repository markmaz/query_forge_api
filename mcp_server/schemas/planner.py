from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import ColumnSchema, ExecutionMetadata, WorkspaceScopedRequest

PlanIntent = Literal["listing", "aggregate", "trend"]
FieldRole = Literal["dimension", "metric"]
SortDirection = Literal["asc", "desc"]


class PlanContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: Optional[str] = None
    max_candidate_fields: int = Field(default=50, ge=1, le=200)


class PlanField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    role: FieldRole
    label: Optional[str] = None


class PlanFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    operator: str
    value: Any = None


class PlanSort(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    direction: SortDirection = "asc"


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_version: str = "1.0"
    status: str = "ok"
    intent: PlanIntent = "listing"
    domain_key: str
    selected_fields: List[PlanField] = Field(default_factory=list)
    filters: List[PlanFilter] = Field(default_factory=list)
    sort: List[PlanSort] = Field(default_factory=list)
    explanations: List[str] = Field(default_factory=list)
    ambiguities: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    internal: Dict[str, Any] = Field(default_factory=dict)


class PlanQueryRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1)
    domain_key: str = Field(min_length=1)
    context: PlanContext = Field(default_factory=PlanContext)


class PlanQueryResponse(QueryPlan):
    model_config = ConfigDict(extra="forbid")


class ValidateQueryPlanRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    plan: QueryPlan


class ValidateQueryPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    normalized_plan: QueryPlan


class CompileQueryRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    plan: QueryPlan
    target: str = "preview"


class CompileQueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql_json: Dict[str, Any]
    compiled: Dict[str, Any]
    execution_metadata: ExecutionMetadata


class PreviewQueryRequest(WorkspaceScopedRequest):
    model_config = ConfigDict(extra="forbid")

    plan: QueryPlan
    limit: int = Field(default=100, ge=1, le=500)


class PreviewQueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: List[ColumnSchema] = Field(default_factory=list)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
    row_count_returned: int = 0
