from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

JoinOp = Literal["="]  # keep tight for now; expand later if needed
CastType = Literal[
    "STRING", "INT", "BIGINT", "DOUBLE", "DECIMAL", "DATE", "TIMESTAMP", "BOOLEAN"
]

class JoinSide(BaseModel):
    col: str = Field(min_length=1, max_length=255)
    cast: Optional[CastType] = None

    @field_validator("col")
    @classmethod
    def validate_col(cls, v: str) -> str:
        # Conservative: allow letters/numbers/underscore; reject funky SQL injection-ish stuff.
        # If you have columns with dots or spaces, loosen this.
        import re
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v):
            raise ValueError(f"Invalid column name: {v}")
        return v

class JoinClause(BaseModel):
    left: JoinSide
    right: JoinSide
    op: JoinOp = "="

class ExtraPredicate(BaseModel):
    sql: str = Field(min_length=1, max_length=2000)

class JoinSpecV1(BaseModel):
    version: Literal[1] = 1
    on: List[JoinClause] = Field(min_length=1)
    extra: Optional[List[ExtraPredicate]] = None

    @model_validator(mode="after")
    def validate(self) -> "JoinSpecV1":
        # Ensure no duplicate left/right pairs, etc. (optional)
        seen = set()
        for c in self.on:
            k = (c.left.col, c.right.col, c.op)
            if k in seen:
                raise ValueError(f"Duplicate join clause: {k}")
            seen.add(k)
        return self