from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


ReviewStatus = Literal["suggested", "accepted", "rejected", "needs_review", "manually_mapped"]
MatchDecision = Literal["matched", "ambiguous", "no_confident_match"]
ReviewAction = Literal["accept", "reject", "needs_review", "remap", "edit_notes"]


class ForgeMatchAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    top_n: int = Field(default=8, ge=3, le=20)
    domain_id: Optional[int] = Field(default=None, ge=1)
    force: bool = False
    llm_id: Optional[int] = Field(default=None, ge=1)


class ForgeMatchPatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping_id: str = Field(min_length=1, max_length=36)
    action: Optional[ReviewAction] = None
    status: Optional[ReviewStatus] = None
    manually_selected_workspace_column_id: Optional[int] = Field(default=None, ge=1)
    review_notes: Optional[str] = None


class ForgeMatchPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updates: List[ForgeMatchPatchItem] = Field(min_length=1)


class ForgeMatchCreateDraftRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = Field(default=None, max_length=255)
    include_notes: bool = False


class ForgeMatchExecuteDraftSqlRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sql: str = Field(min_length=1)
    catalog_name: Optional[str] = Field(default=None, max_length=255)
    schema_name: Optional[str] = Field(default=None, max_length=255)


class ForgeMatchUploadResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str
    workspace_id: str
    uploaded_filename: str
    file_type: str
    status: str
    sheet_count: int
    source_record_count: int
    source_preview: List[Dict[str, Any]]


class ForgeMatchAnalyzeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str
    workspace_id: str
    status: str
    result_count: int
    summary: Dict[str, Any]
    mappings: List[Dict[str, Any]]


class ForgeMatchSessionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    session: Dict[str, Any]
    source_records: List[Dict[str, Any]]
    mappings: List[Dict[str, Any]]
    summary: Dict[str, Any]
