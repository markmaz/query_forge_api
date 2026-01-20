from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

UnionKind = Literal["UNION_ALL"]  # keep tight for v1
DataType = Literal["STRING", "INT", "BIGINT", "DOUBLE", "DECIMAL", "DATE", "TIMESTAMP", "BOOLEAN"]
CastType = DataType

class UnionOutputColumn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: DataType
    nullable: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v):
            raise ValueError(f"Invalid output column name: {v}")
        return v

class UnionOutput(BaseModel):
    columns: List[UnionOutputColumn] = Field(min_length=1)

class UnionSelectMap(BaseModel):
    out: str = Field(min_length=1, max_length=255)  # must match an output column name
    expr: str = Field(min_length=1, max_length=4000)  # SQL expression using alias "from"
    cast: Optional[CastType] = None

class UnionWherePredicate(BaseModel):
    sql: str = Field(min_length=1, max_length=2000)

class UnionMember(BaseModel):
    workspace_table_id: int
    select: List[UnionSelectMap] = Field(min_length=1)
    where: Optional[List[UnionWherePredicate]] = None

class UnionSpecV1(BaseModel):
    version: Literal[1] = 1
    kind: UnionKind = "UNION_ALL"
    output: UnionOutput
    members: List[UnionMember] = Field(min_length=1)

    @model_validator(mode="after")
    def validate(self) -> "UnionSpecV1":
        output_names = [c.name for c in self.output.columns]
        output_set = set(output_names)

        # Ensure no duplicate output names
        if len(output_names) != len(output_set):
            raise ValueError("output.columns contains duplicate names")

        # Ensure each member provides mappings for every output col (exactly once)
        for m in self.members:
            outs = [s.out for s in m.select]
            if set(outs) != output_set:
                missing = output_set - set(outs)
                extra = set(outs) - output_set
                raise ValueError(
                    f"Member workspace_table_id={m.workspace_table_id} must map exactly all output columns. "
                    f"Missing={sorted(missing)} Extra={sorted(extra)}"
                )
            if len(outs) != len(set(outs)):
                raise ValueError(f"Member workspace_table_id={m.workspace_table_id} has duplicate 'out' mappings")

        return self