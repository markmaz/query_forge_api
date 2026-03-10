from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MetadataTableRecord:
    table_id: int
    table_name: str
    source_table_name: Optional[str]
    description: Optional[str]
    origin: Optional[str]
    is_missing_in_source: bool


@dataclass(frozen=True)
class MetadataColumnRecord:
    column_id: int
    table_id: int
    column_name: str
    data_type: Optional[str]
    description: Optional[str]
    is_active: bool
    origin: Optional[str]
    is_missing_in_source: bool
    semantic_type: Optional[str] = None
    semantic_entity: Optional[str] = None
    semantic_sub_type: Optional[str] = None
    semantic_source: Optional[str] = None
    semantic_confidence: Optional[float] = None
    semantic_concept_key: Optional[str] = None
