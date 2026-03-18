from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class SqlColumnKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modelColumnId: Optional[int] = None
    columnName: str
    workspaceTableId: Optional[int] = None
    exprId: Optional[str] = None
    alias: Optional[str] = None


class SqlColumnRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: SqlColumnKey
    alias: Optional[str] = None


class DomainCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domainId: int
    name: str = ""
    description: str = ""
    domainName: Optional[str] = None
    domainKind: Optional[str] = None
    score: Optional[float] = None


class DomainContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selectedDomainId: Optional[int] = None
    domainCandidates: List[DomainCandidate] = Field(default_factory=list)


class TableCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tableId: Optional[int] = None
    tableName: str
    modelTableId: Optional[int] = None
    score: float
    reasons: List[str] = Field(default_factory=list)


class ColumnCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modelColumnId: Optional[int] = None
    columnName: str
    workspaceTableId: Optional[int] = None
    modelTableId: Optional[int] = None
    modelTableName: Optional[str] = None
    label: str
    description: str
    dataType: Optional[str] = None
    score: float
    reasons: List[str] = Field(default_factory=list)


class Candidates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tables: List[TableCandidate] = Field(default_factory=list)
    columns: List[ColumnCandidate] = Field(default_factory=list)


class SuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["ai_first", "domains", "columns", "filters", "aggregation", "data_prep"]
    prompt: str = Field(min_length=1)
    workspaceId: str = Field(min_length=1)
    currentSqlJson: Optional[Dict[str, Any]] = None
    domainContext: Optional[DomainContext] = None
    candidates: Optional[Candidates] = None


class SetDomainEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["setDomain"]
    domainId: int


class AddSelectEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["addSelect"]
    col: SqlColumnKey
    alias: Optional[str] = None


class AddFilterEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["addFilter"]
    col: SqlColumnKey
    operator: Literal[
        "equals",
        "not_equals",
        "contains",
        "starts_with",
        "in",
        "not_in",
        "gt",
        "gte",
        "lt",
        "lte",
        "between",
        "is_null",
        "is_not_null",
    ]
    value: Any


class AddGroupByEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["addGroupBy"]
    col: SqlColumnKey


class AddAggregateEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["addAggregate"]
    func: Literal["count_distinct", "count", "sum", "avg"]
    col: Optional[SqlColumnKey] = None
    alias: str


class AddSortEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["addSort"]
    col: SqlColumnKey
    dir: Literal["asc", "desc"]


EditOperation = Annotated[
    Union[SetDomainEdit, AddSelectEdit, AddFilterEdit, AddGroupByEdit, AddAggregateEdit, AddSortEdit],
    Field(discriminator="op"),
]


class SuggestModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edits: List[EditOperation] = Field(default_factory=list)
    explanation: str
    confidence: float = Field(ge=0.0, le=1.0)


class SuggestDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    attempts: int = Field(ge=1, le=2)


class SuggestAPIResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edits: List[EditOperation] = Field(default_factory=list)
    explanation: str
    confidence: float = Field(ge=0.0, le=1.0)
    sqlJson: Dict[str, Any]
    debug: SuggestDebug


def column_candidate_to_sql_column_key(candidate: ColumnCandidate) -> SqlColumnKey:
    return SqlColumnKey(
        modelColumnId=candidate.modelColumnId,
        columnName=candidate.columnName,
        workspaceTableId=candidate.workspaceTableId,
        exprId=None,
        alias=None,
    )


def column_candidate_to_sql_column_ref(
    candidate: ColumnCandidate,
    *,
    alias: Optional[str] = None,
) -> SqlColumnRef:
    return SqlColumnRef(
        field=column_candidate_to_sql_column_key(candidate),
        alias=alias,
    )
