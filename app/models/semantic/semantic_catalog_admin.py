from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SemanticCatalogBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    domain_id: int = Field(gt=0)
    domain_name: Optional[str] = Field(default=None, max_length=255)
    dry_run: bool = True
    table_limit: int = Field(default=5000, ge=1, le=50000)
    llm_id: Optional[int] = Field(default=None, ge=1)

    @field_validator("workspace_id", mode="before")
    @classmethod
    def _normalize_workspace_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("domain_name", mode="before")
    @classmethod
    def _normalize_domain_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
