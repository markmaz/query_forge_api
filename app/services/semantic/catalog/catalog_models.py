from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


PlannerRole = Literal["dimension", "measure", "metric", "filter", "time_field", "identifier", "other"]
SemanticType = Literal[
    "domain",
    "measure",
    "metric",
    "dimension",
    "filter",
    "time_field",
    "identifier",
    "attribute",
    "other",
]


class ColumnProfile(BaseModel):
    workspace_table_id: int
    workspace_column_id: int
    table_name: str
    column_name: str
    data_type: str
    nullable: bool = True
    distinct_count: Optional[int] = None
    row_count: Optional[int] = None
    sample_values: List[Any] = Field(default_factory=list)
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None

    is_identifier: bool = False
    is_numeric: bool = False
    is_date_like: bool = False
    is_enum_like: bool = False
    is_dimension_candidate: bool = False
    is_measure_candidate: bool = False

    @field_validator("table_name", "column_name", "data_type", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("sample_values", mode="before")
    @classmethod
    def _normalize_sample_values(cls, value: Any) -> List[Any]:
        if isinstance(value, list):
            return value[:30]
        return []


class ColumnEnrichment(BaseModel):
    business_label: str
    semantic_type: SemanticType
    planner_role: PlannerRole
    description: str
    aliases: List[str] = Field(default_factory=list)
    groupable: bool = True
    filterable: bool = True
    time_candidate: bool = False
    measure_candidate: bool = False
    default_aggregations: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    domain_hint: Optional[str] = None

    @field_validator("business_label", "description", mode="before")
    @classmethod
    def _normalize_required_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        return text

    @field_validator("domain_hint", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> Optional[str]:
        text = str(value or "").strip()
        return text or None

    @field_validator("aliases", mode="before")
    @classmethod
    def _normalize_aliases(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        seen: set[str] = set()
        out: List[str] = []
        for item in value:
            token = str(item or "").strip()
            key = token.lower()
            if token == "" or key in seen:
                continue
            seen.add(key)
            out.append(token)
        return out

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, number))


class EnrichedColumnProfile(BaseModel):
    profile: ColumnProfile
    enrichment: ColumnEnrichment


class ConceptUpsert(BaseModel):
    concept_key: str
    name: str
    description: str
    semantic_type: str
    sub_type: Optional[str] = None
    entity: Optional[str] = None
    granularity_rank: int = 0
    filter_allowed: bool = True
    group_by_allowed: bool = True
    aggregation_allowed: bool = False
    is_identifier: bool = False
    is_metric: bool = False
    display_priority: int = 0
    sensitive: bool = False
    status: str = "active"

class AliasUpsert(BaseModel):
    alias_key: str
    concept_key: str
    match_kind: str = "exact"
    weight: float = 1.0


class RelationshipUpsert(BaseModel):
    parent_concept_id: int
    child_concept_id: int
    relationship_type: str


class ValueAliasUpsert(BaseModel):
    semantic_concept_id: int
    canonical_value: str
    alias_value: str
    match_kind: str = "exact"
    weight: float = 1.0


class SemanticIndexItem(BaseModel):
    concept_id: int
    concept_key: str
    vector_text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SemanticCatalogBuildResult(BaseModel):
    workspace_id: str
    domain_id: Optional[int] = None
    domain_name: Optional[str] = None
    profile_count: int = 0
    enriched_count: int = 0
    concepts_upserted: int = 0
    aliases_upserted: int = 0
    relationships_upserted: int = 0
    value_aliases_upserted: int = 0
    derived_metrics_created: int = 0
    index_items_count: int = 0
    dry_run: bool = False
    concept_preview: List[Dict[str, Any]] = Field(default_factory=list)
    alias_preview: List[Dict[str, Any]] = Field(default_factory=list)
    relationship_preview: List[Dict[str, Any]] = Field(default_factory=list)
    index_preview: List[Dict[str, Any]] = Field(default_factory=list)

class SemanticEnrichmentBatchResponse(BaseModel):
    items: List[ColumnEnrichment]
