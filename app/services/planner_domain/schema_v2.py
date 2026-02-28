from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


VerticalNorm = Literal["education", "healthcare", "generic"]
PlanIntent = Literal["aggregate", "list", "trend"]
TimeRange = Literal["last_7_days", "last_30_days", "last_year", "ytd", "custom"]
TimeGrain = Literal["day", "week", "month", "term", "school_year"]
SortDir = Literal["asc", "desc"]


class PlanV2Dimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_key: str = Field(min_length=1)
    label: Optional[str] = None


class PlanV2MetricSelect(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    metric_ref: str = Field(min_length=1, alias="metricRef")
    label: Optional[str] = None


class PlanV2Selects(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimensions: List[PlanV2Dimension] = Field(default_factory=list)
    metrics: List[PlanV2MetricSelect] = Field(default_factory=list)


class PlanV2Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_key: str = Field(min_length=1)
    op: str = Field(min_length=1)
    value: Any = None


class PlanV2Time(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_range: Optional[TimeRange] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    time_grain: Optional[TimeGrain] = None
    time_column_key: Optional[str] = None


class PlanV2OrderBy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by: str = Field(min_length=1)
    dir: SortDir = "asc"


class PlanV2Grouping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_by: List[str] = Field(default_factory=list)
    limit: Optional[int] = None
    order_by: List[PlanV2OrderBy] = Field(default_factory=list)


class PlanV2DebugReasons(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: List[str] = Field(default_factory=list)
    metrics: List[str] = Field(default_factory=list)
    filters: List[str] = Field(default_factory=list)


class PlanV2DebugCandidates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domains: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: List[Dict[str, Any]] = Field(default_factory=list)
    dimensions: List[Dict[str, Any]] = Field(default_factory=list)


class PlanV2Debug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasons: PlanV2DebugReasons = Field(default_factory=PlanV2DebugReasons)
    candidates: PlanV2DebugCandidates = Field(default_factory=PlanV2DebugCandidates)


class PlanV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    trace_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    vertical_norm: VerticalNorm = "generic"
    base_domain_id: int = Field(gt=0)
    domain_name: Optional[str] = None
    intent: PlanIntent
    selects: PlanV2Selects
    filters: List[PlanV2Filter] = Field(default_factory=list)
    time: PlanV2Time = Field(default_factory=PlanV2Time)
    grouping: PlanV2Grouping = Field(default_factory=PlanV2Grouping)
    debug: Optional[PlanV2Debug] = None


def plan_v2_json_schema() -> Dict[str, Any]:
    schema = PlanV2.model_json_schema()
    if "title" in schema:
        schema.pop("title", None)
    return schema


__all__ = [
    "PlanV2",
    "PlanV2Dimension",
    "PlanV2Filter",
    "PlanV2Grouping",
    "PlanV2MetricSelect",
    "plan_v2_json_schema",
]
