from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _optional_text(value: Any, *, max_len: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    if len(text) > max_len:
        raise ValueError(f"must be {max_len} characters or fewer")
    return text


class ForgeInsightsProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, value: Any) -> str:
        out = _optional_text(value, max_len=255)
        if out is None:
            raise ValueError("name is required")
        return out

    @field_validator("description", mode="before")
    @classmethod
    def _validate_description(cls, value: Any) -> Optional[str]:
        return _optional_text(value, max_len=10_000)


class ForgeInsightsProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    description: Optional[str] = None
    is_archived: Optional[bool] = None

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, value: Any) -> Optional[str]:
        return _optional_text(value, max_len=255)

    @field_validator("description", mode="before")
    @classmethod
    def _validate_description(cls, value: Any) -> Optional[str]:
        return _optional_text(value, max_len=10_000)


class ForgeInsightsThreadCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: Optional[int] = None
    conversation_id: Optional[str] = None
    title: Optional[str] = None
    preview_text: Optional[str] = None
    is_pinned: bool = False
    is_archived: bool = False

    @field_validator("conversation_id", mode="before")
    @classmethod
    def _validate_conversation_id(cls, value: Any) -> Optional[str]:
        return _optional_text(value, max_len=128)

    @field_validator("title", mode="before")
    @classmethod
    def _validate_title(cls, value: Any) -> Optional[str]:
        return _optional_text(value, max_len=255)

    @field_validator("preview_text", mode="before")
    @classmethod
    def _validate_preview_text(cls, value: Any) -> Optional[str]:
        return _optional_text(value, max_len=20_000)


class ForgeInsightsThreadUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: Optional[int] = None
    title: Optional[str] = None
    preview_text: Optional[str] = None
    is_pinned: Optional[bool] = None
    is_archived: Optional[bool] = None
    last_message_at: Optional[datetime] = None

    @field_validator("title", mode="before")
    @classmethod
    def _validate_title(cls, value: Any) -> Optional[str]:
        return _optional_text(value, max_len=255)

    @field_validator("preview_text", mode="before")
    @classmethod
    def _validate_preview_text(cls, value: Any) -> Optional[str]:
        return _optional_text(value, max_len=20_000)


class ForgeInsightsProjectResponse(BaseModel):
    id: int
    workspace_id: str
    user_id: str
    name: str
    description: Optional[str] = None
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class ForgeInsightsThreadResponse(BaseModel):
    id: int
    workspace_id: str
    user_id: str
    project_id: Optional[int] = None
    conversation_id: str
    title: Optional[str] = None
    preview_text: Optional[str] = None
    is_pinned: bool
    is_archived: bool
    last_message_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
