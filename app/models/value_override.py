from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ForgeSectionKey = Literal["regions", "npiCategories", "serviceLines"]


class ColumnSpec(BaseModel):
    name: str
    type: str  
    comment: Optional[str] = None


class ValueOverrideMeta(BaseModel):
    list_id: str
    list_name: str
    owner: str
    user_id: Optional[str] = None
    is_shared: bool = False
    created_at: datetime
    updated_at: datetime
    row_count: int = Field(ge=0)
    expires_at: Optional[date] = None


class ValueOverrideListIndex(BaseModel):
    regions: List[ValueOverrideMeta] = []
    npiCategories: List[ValueOverrideMeta] = []
    serviceLines: List[ValueOverrideMeta] = []


class ValueOverrideDetails(BaseModel):
    list_id: str
    list_name: str
    list_type: ForgeSectionKey
    columns: List[ColumnSpec]
    rows: List[Dict[str, Any]]
    total_rows: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
