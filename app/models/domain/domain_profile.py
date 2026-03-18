from __future__ import annotations

import hashlib
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DomainProfileBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    summary: Optional[str] = None
    keywords: Optional[List[Any]] = None
    entities: Optional[List[Any]] = None
    metrics: Optional[List[Any]] = None
    attributes: Optional[List[Any]] = None
    synonyms: Optional[List[Any]] = None
    acronyms: Optional[List[Any]] = None
    notes: Optional[str] = None
    embedding_text: Optional[str] = None


class DomainProfileCreateRequest(DomainProfileBase):
    workspace_id: str = Field(..., min_length=1)
    domain_id: int = Field(..., gt=0)

    @model_validator(mode="after")
    def ensure_embedding_text(self) -> "DomainProfileCreateRequest":
        if not self.embedding_text:
            self.embedding_text = _build_embedding_text(self)
        return self


class DomainProfileUpdateRequest(DomainProfileBase):
    pass


class DomainProfileResponse(DomainProfileBase):
    id: int
    workspace_id: str
    domain_id: int
    content_hash: Optional[str] = None
    embedding_model: Optional[str] = None
    embedded_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    domain_name: Optional[str] = None

    @field_validator(
        "created_at", "updated_at", "embedded_at", mode="before"
    )
    @classmethod
    def stringify_datetime(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return str(v)


def compute_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _item_to_str(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("label") or item.get("name") or item.get("term") or str(item)
    return str(item)


def _build_embedding_text(profile: DomainProfileBase) -> str:
    parts: List[str] = []
    if profile.summary:
        parts.append(f"Description: {profile.summary}")
    if profile.keywords:
        parts.append(f"Keywords: {', '.join(_item_to_str(k) for k in profile.keywords)}")
    if profile.entities:
        parts.append(f"Entities: {', '.join(_item_to_str(e) for e in profile.entities)}")
    if profile.attributes:
        parts.append(f"Attributes: {', '.join(_item_to_str(a) for a in profile.attributes)}")
    if profile.metrics:
        parts.append(f"Metrics: {', '.join(_item_to_str(m) for m in profile.metrics)}")
    if profile.synonyms:
        syns = "; ".join(
            f"{s.get('term', '')} = {', '.join(s.get('means', []))}"
            if isinstance(s, dict) else str(s)
            for s in profile.synonyms
        )
        parts.append(f"Synonyms: {syns}")
    if profile.acronyms:
        acrs = "; ".join(
            f"{a.get('abbr', '')} = {a.get('expansion', '')}"
            if isinstance(a, dict) else str(a)
            for a in profile.acronyms
        )
        parts.append(f"Acronyms: {acrs}")
    if profile.notes:
        parts.append(f"Notes: {profile.notes}")
    return "\n".join(parts) or "domain profile"
