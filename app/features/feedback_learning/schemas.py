from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator


class CandidateRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str

    @field_validator("reason", mode="before")
    @classmethod
    def _validate_reason(cls, value):
        text = str(value or "").strip()
        if text == "":
            raise ValueError("reason is required")
        return text


class CandidateBulkDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ids: List[int]
    reason: Optional[str] = None

    @field_validator("candidate_ids")
    @classmethod
    def _validate_candidate_ids(cls, value):
        if not isinstance(value, list) or not value:
            raise ValueError("candidate_ids must be a non-empty list")
        return [int(item) for item in value]

    @field_validator("reason", mode="before")
    @classmethod
    def _validate_reason(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        return text or None


__all__ = ["CandidateBulkDecisionRequest", "CandidateRejectRequest"]
