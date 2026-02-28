from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

_ALLOWED_VOTES = {"up", "down", "thumbs_up", "thumbs_down"}
_VOTE_ALIASES = {
    "up": "up",
    "thumbs_up": "up",
    "down": "down",
    "thumbs_down": "down",
}


class PromptFeedbackMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: Optional[str] = None
    timings_ms: Optional[Dict[str, Any]] = None
    domain_id: Optional[int] = None
    domain_version: Optional[int] = None
    intent: Optional[str] = None

    @field_validator("model", "intent", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("timings_ms")
    @classmethod
    def _validate_timings_ms(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("timings_ms must be an object")
        return value


class PromptFeedbackRequest(BaseModel):
    workspace_id: str
    trace_id: Optional[str] = None
    vote: str
    normalized_prompt: Optional[str] = None
    prompt_text: Optional[str] = None
    response_json: Dict[str, Any]
    meta: Optional[PromptFeedbackMeta] = None

    @field_validator("workspace_id", mode="before")
    @classmethod
    def _validate_workspace_id(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("workspace_id is required")
        return text

    @field_validator("trace_id", mode="before")
    @classmethod
    def _validate_trace_id(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if len(text) > 64:
            raise ValueError("trace_id must be 64 characters or fewer")
        return text

    @field_validator("vote", mode="before")
    @classmethod
    def _validate_vote(cls, value: Any) -> str:
        text = str(value or "").strip().lower()
        if text not in _ALLOWED_VOTES:
            raise ValueError("vote must be one of: up, down, thumbs_up, thumbs_down")
        return _VOTE_ALIASES[text]

    @field_validator("normalized_prompt", "prompt_text", mode="before")
    @classmethod
    def _validate_optional_text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("response_json")
    @classmethod
    def _validate_response_json(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("response_json must be an object")
        return value


class PromptFeedbackResponse(BaseModel):
    id: int
    vote: Literal["up", "down"]
    created_at: datetime
    updated_at: datetime
