from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DomainProfileGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    domain_ids: List[int] = Field(..., min_length=1)
    force: bool = False
    llm_id: int | None = Field(default=None, ge=1)

    @field_validator("domain_ids", mode="before")
    @classmethod
    def _coerce_domain_ids(cls, value):
        if value is None:
            return value
        if isinstance(value, (int, str)):
            return [value]
        return value


class DomainProfileGenerateAllRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    force: bool = False
    include_inactive: bool = False
    llm_id: int | None = Field(default=None, ge=1)


class DomainProfileGenerateOneRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    force: bool = False
    llm_id: int | None = Field(default=None, ge=1)
