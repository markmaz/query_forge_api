from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.semantic.catalog.catalog_models import (
    AliasUpsert,
    ColumnEnrichment,
    ConceptUpsert,
    EnrichedColumnProfile,
    RelationshipUpsert,
    SemanticCatalogBuildResult,
    ValueAliasUpsert,
)
from app.services.semantic.catalog.column_profile_builder import ColumnProfileBuilder
from app.services.semantic.catalog.semantic_catalog_repository import SemanticCatalogRepository
from app.services.semantic.catalog.semantic_enrichment_service import SemanticEnrichmentService
from app.services.semantic.catalog.semantic_index_builder import SemanticIndexBuilder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DerivedMetricSpec:
    concept_key: str
    name: str
    description: str
    formula_kind: str
    depends_on: Tuple[str, ...]


class SemanticCatalogBuilder:
    """
    End-to-end semantic catalog builder.

    Planner integration notes:
    - The planner should use these semantic concepts for domain/metric/dimension/filter retrieval.
    - `source_column_for` relationships provide lineage to physical columns.
    - derived metric concepts are strictly grammar-based (ratio/average/percentage/growth only).
    """

    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        profile_builder: Optional[ColumnProfileBuilder] = None,
        enrichment_service: Optional[SemanticEnrichmentService] = None,
        repository: Optional[SemanticCatalogRepository] = None,
        index_builder: Optional[SemanticIndexBuilder] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._profile_builder = profile_builder or ColumnProfileBuilder(sql=self._sql)
        self._enrichment = enrichment_service or SemanticEnrichmentService()
        self._repo = repository or SemanticCatalogRepository(sql=self._sql)
        self._index = index_builder or SemanticIndexBuilder()

    def build_catalog(
        self,
        *,
        workspace_id: str,
        domain_id: int,
        vertical_norm: str = "generic",
        domain_name: Optional[str] = None,
        dry_run: bool = False,
        table_limit: int = 5000,
        llm_id: Optional[int] = None,
    ) -> SemanticCatalogBuildResult:
        normalized_vertical = _normalize_vertical(vertical_norm)
        resolved_domain_name = domain_name or self._load_domain_name(workspace_id=workspace_id, domain_id=domain_id)

        profiles = self._profile_builder.build_profiles(
            workspace_id=workspace_id,
            domain_id=domain_id,
            limit=table_limit,
        )
        enriched = self._enrichment.enrich_profiles(
            profiles=profiles,
            workspace_id=workspace_id,
            vertical_norm=normalized_vertical,
            domain_name=resolved_domain_name,
            llm_id=llm_id,
        )
        if _looks_like_sales_domain(resolved_domain_name):
            enriched = _apply_sales_performance_overrides(enriched)

        concepts, aliases, source_map = self._build_core_concepts(
            vertical_norm=normalized_vertical,
            domain_name=resolved_domain_name,
            enriched=enriched,
        )
        derived_specs = _build_derived_metric_specs(
            domain_name=resolved_domain_name,
            concepts=concepts,
        )
        derived_concepts, derived_aliases = _concepts_for_derived_metrics(
            vertical_norm=normalized_vertical,
            specs=derived_specs,
        )
        concepts.extend(derived_concepts)
        aliases.extend(derived_aliases)

        if dry_run:
            preview_concepts = [c.model_dump(mode="json") for c in concepts[:50]]
            preview_aliases = [a.model_dump(mode="json") for a in aliases[:80]]
            preview_relationships = _preview_relationships_for_dry_run(
                concepts=concepts,
                derived_specs=derived_specs,
                domain_name=resolved_domain_name,
            )
            pseudo_rows = _pseudo_concept_rows(preview_concepts)
            alias_map = _aliases_by_key(preview_aliases)
            domain_map = _domain_key_map_for_rows(rows=pseudo_rows, domain_name=resolved_domain_name)
            index_items = self._index.build_items(
                concept_rows=pseudo_rows,
                aliases_by_key=alias_map,
                domain_key_by_concept=domain_map,
                source_column_by_concept=source_map,
            )
            return SemanticCatalogBuildResult(
                workspace_id=workspace_id,
                domain_id=int(domain_id),
                domain_name=resolved_domain_name,
                vertical_norm=normalized_vertical,
                profile_count=len(profiles),
                enriched_count=len(enriched),
                concepts_upserted=len(preview_concepts),
                aliases_upserted=len(preview_aliases),
                relationships_upserted=len(preview_relationships),
                value_aliases_upserted=0,
                derived_metrics_created=len(derived_specs),
                index_items_count=len(index_items),
                dry_run=True,
                concept_preview=preview_concepts,
                alias_preview=preview_aliases,
                relationship_preview=preview_relationships,
                index_preview=[item.model_dump(mode="json") for item in index_items[:40]],
            )

        write_result = self._repo.apply_catalog_writes(
            concepts=concepts,
            aliases=aliases,
            relationships=[],
            value_aliases=[],
        )

        concept_id_by_key = dict(write_result.get("concept_id_by_key") or {})
        relationships = _build_relationships(
            concept_id_by_key=concept_id_by_key,
            concepts=concepts,
            derived_specs=derived_specs,
            domain_name=resolved_domain_name,
            source_map=source_map,
        )
        value_aliases = _build_value_aliases(
            vertical_norm=normalized_vertical,
            concept_id_by_key=concept_id_by_key,
            enriched=enriched,
        )

        write_result_2 = self._repo.apply_catalog_writes(
            concepts=[],
            aliases=[],
            relationships=relationships,
            value_aliases=value_aliases,
        )

        all_keys = [c.concept_key for c in concepts]
        concept_rows = self._repo.get_concepts(vertical_norm=normalized_vertical, concept_keys=all_keys)
        alias_map = self._repo.get_aliases_by_concept_keys(vertical_norm=normalized_vertical, concept_keys=all_keys)
        domain_key_map = _domain_key_map_for_rows(rows=concept_rows, domain_name=resolved_domain_name)
        index_items = self._index.build_items(
            concept_rows=concept_rows,
            aliases_by_key=alias_map,
            domain_key_by_concept=domain_key_map,
            source_column_by_concept=source_map,
        )

        return SemanticCatalogBuildResult(
            workspace_id=workspace_id,
            domain_id=int(domain_id),
            domain_name=resolved_domain_name,
            vertical_norm=normalized_vertical,
            profile_count=len(profiles),
            enriched_count=len(enriched),
            concepts_upserted=int(write_result.get("concept_count") or 0),
            aliases_upserted=int(write_result.get("alias_count") or 0),
            relationships_upserted=int(write_result_2.get("relationship_count") or 0),
            value_aliases_upserted=int(write_result_2.get("value_alias_count") or 0),
            derived_metrics_created=len(derived_specs),
            index_items_count=len(index_items),
            dry_run=False,
            concept_preview=[row for row in concept_rows[:40]],
            alias_preview=[
                {
                    "concept_key": key,
                    "aliases": vals,
                }
                for key, vals in list(alias_map.items())[:40]
            ],
            relationship_preview=[r.model_dump(mode="json") for r in relationships[:60]],
            index_preview=[item.model_dump(mode="json") for item in index_items[:40]],
        )

    def run_sales_performance_example(
        self,
        *,
        workspace_id: str,
        domain_id: int,
        vertical_norm: str = "generic",
        dry_run: bool = True,
        llm_id: Optional[int] = None,
    ) -> SemanticCatalogBuildResult:
        """
        Example entrypoint requested for Sales Performance domain bootstrap.
        """
        return self.build_catalog(
            workspace_id=workspace_id,
            domain_id=domain_id,
            vertical_norm=vertical_norm,
            domain_name="Sales Performance",
            dry_run=dry_run,
            llm_id=llm_id,
        )

    def _load_domain_name(self, *, workspace_id: str, domain_id: int) -> str:
        rows = self._sql.execute_query_mappings(
            """
            SELECT name
            FROM domain
            WHERE workspace_id = :workspace_id
              AND id = :domain_id
            LIMIT 1
            """,
            {"workspace_id": workspace_id, "domain_id": int(domain_id)},
        )
        if not rows:
            return f"domain_{int(domain_id)}"
        return str(rows[0].get("name") or f"domain_{int(domain_id)}").strip()

    def _build_core_concepts(
        self,
        *,
        vertical_norm: str,
        domain_name: str,
        enriched: Sequence[EnrichedColumnProfile],
    ) -> Tuple[List[ConceptUpsert], List[AliasUpsert], Dict[str, str]]:
        concepts: Dict[str, ConceptUpsert] = {}
        aliases: List[AliasUpsert] = []
        source_column_by_concept: Dict[str, str] = {}

        domain_key = _domain_concept_key(domain_name)
        concepts[domain_key] = ConceptUpsert(
            vertical_norm=vertical_norm,
            concept_key=domain_key,
            name=domain_name,
            description=f"Semantic domain for {domain_name}.",
            semantic_type="domain",
            sub_type="domain",
            entity="domain",
            granularity_rank=0,
            filter_allowed=False,
            group_by_allowed=False,
            aggregation_allowed=False,
            is_identifier=False,
            is_metric=False,
            display_priority=200,
            sensitive=False,
            status="active",
        )

        for item in enriched:
            profile = item.profile
            info = item.enrichment
            concept_key = _concept_key_for_profile(profile=profile, enrichment=info)
            semantic_type = _normalize_semantic_type(info.semantic_type)
            is_metric = semantic_type in {"measure", "metric"}
            concept = ConceptUpsert(
                vertical_norm=vertical_norm,
                concept_key=concept_key,
                name=info.business_label or _humanize(profile.column_name),
                description=info.description,
                semantic_type=semantic_type,
                sub_type=info.planner_role,
                entity=_entity_hint_from_column(profile.column_name),
                granularity_rank=1 if semantic_type in {"dimension", "filter", "time_field", "identifier"} else 2,
                filter_allowed=bool(info.filterable),
                group_by_allowed=bool(info.groupable),
                aggregation_allowed=bool(is_metric),
                is_identifier=bool(semantic_type == "identifier" or profile.is_identifier),
                is_metric=bool(is_metric),
                display_priority=100,
                sensitive=False,
                status="active",
            )
            concepts[concept_key] = concept
            source_column_by_concept[concept_key] = f"{profile.table_name}.{profile.column_name}"

            for alias in _dedupe_aliases(info.aliases + [_humanize(profile.column_name)]):
                aliases.append(
                    AliasUpsert(
                        vertical_norm=vertical_norm,
                        alias_key=alias,
                        concept_key=concept_key,
                        match_kind="exact",
                        weight=max(0.6, float(info.confidence)),
                    )
                )

        return list(concepts.values()), aliases, source_column_by_concept


def _build_derived_metric_specs(*, domain_name: str, concepts: Sequence[ConceptUpsert]) -> List[_DerivedMetricSpec]:
    measure_keys = [
        c.concept_key
        for c in concepts
        if c.semantic_type in {"measure", "metric"}
    ]
    has_time = any(c.semantic_type == "time_field" for c in concepts)

    specs: List[_DerivedMetricSpec] = []

    sales_key = _find_key(measure_keys, tokens=("SALES_AMOUNT", "REVENUE", "ACTUAL_SALES"))
    quota_key = _find_key(measure_keys, tokens=("QUOTA_AMOUNT", "TARGET"))
    order_count_key = _find_key(measure_keys, tokens=("ORDER_COUNT", "ORDERS", "COUNT"))
    discount_key = _find_key(measure_keys, tokens=("DISCOUNT_AMOUNT", "DISCOUNT"))

    if sales_key and quota_key:
        specs.append(
            _DerivedMetricSpec(
                concept_key="QUOTA_ATTAINMENT_PCT",
                name="Quota Attainment %",
                description="Percentage of achieved sales amount divided by quota amount.",
                formula_kind="percentage",
                depends_on=(sales_key, quota_key),
            )
        )
    if sales_key and order_count_key:
        specs.append(
            _DerivedMetricSpec(
                concept_key="AVERAGE_ORDER_VALUE",
                name="Average Order Value",
                description="Average sales amount per order.",
                formula_kind="average",
                depends_on=(sales_key, order_count_key),
            )
        )
    if discount_key and sales_key:
        specs.append(
            _DerivedMetricSpec(
                concept_key="DISCOUNT_RATE",
                name="Discount Rate",
                description="Discount amount divided by sales amount.",
                formula_kind="ratio",
                depends_on=(discount_key, sales_key),
            )
        )

    if has_time and sales_key:
        specs.append(
            _DerivedMetricSpec(
                concept_key="SALES_GROWTH_RATE",
                name="Sales Growth Rate",
                description="Period-over-period growth percentage for sales amount.",
                formula_kind="growth",
                depends_on=(sales_key,),
            )
        )

    # Ensure we never emit duplicate derived metrics.
    dedup: Dict[str, _DerivedMetricSpec] = {}
    for item in specs:
        dedup[item.concept_key] = item

    # Keep sales domain defaults even if column names are sparse.
    if _looks_like_sales_domain(domain_name):
        for required_key, required_name, required_desc, required_kind in (
            ("QUOTA_ATTAINMENT_PCT", "Quota Attainment %", "Quota attainment percentage.", "percentage"),
            ("AVERAGE_ORDER_VALUE", "Average Order Value", "Average revenue per order.", "average"),
            ("DISCOUNT_RATE", "Discount Rate", "Discount amount divided by sales amount.", "ratio"),
        ):
            if required_key not in dedup:
                deps = tuple(k for k in (sales_key, quota_key, order_count_key, discount_key) if k)
                dedup[required_key] = _DerivedMetricSpec(
                    concept_key=required_key,
                    name=required_name,
                    description=required_desc,
                    formula_kind=required_kind,
                    depends_on=deps[:2],
                )

    return list(dedup.values())


def _concepts_for_derived_metrics(
    *,
    vertical_norm: str,
    specs: Sequence[_DerivedMetricSpec],
) -> Tuple[List[ConceptUpsert], List[AliasUpsert]]:
    concepts: List[ConceptUpsert] = []
    aliases: List[AliasUpsert] = []
    for spec in specs:
        concepts.append(
            ConceptUpsert(
                vertical_norm=vertical_norm,
                concept_key=spec.concept_key,
                name=spec.name,
                description=f"{spec.description} Derived metric using controlled grammar ({spec.formula_kind}).",
                semantic_type="metric",
                sub_type=f"derived_{spec.formula_kind}",
                entity="metric",
                granularity_rank=2,
                filter_allowed=False,
                group_by_allowed=False,
                aggregation_allowed=True,
                is_identifier=False,
                is_metric=True,
                display_priority=140,
                sensitive=False,
                status="active",
            )
        )
        for alias in _dedupe_aliases([spec.name, spec.concept_key.replace("_", " ").title()]):
            aliases.append(
                AliasUpsert(
                    vertical_norm=vertical_norm,
                    alias_key=alias,
                    concept_key=spec.concept_key,
                    match_kind="exact",
                    weight=0.95,
                )
            )
    return concepts, aliases


def _build_relationships(
    *,
    concept_id_by_key: Mapping[str, int],
    concepts: Sequence[ConceptUpsert],
    derived_specs: Sequence[_DerivedMetricSpec],
    domain_name: str,
    source_map: Mapping[str, str],
) -> List[RelationshipUpsert]:
    domain_key = _domain_concept_key(domain_name)
    domain_id = int(concept_id_by_key.get(domain_key) or 0)
    time_ids = [
        int(concept_id_by_key.get(c.concept_key) or 0)
        for c in concepts
        if c.semantic_type == "time_field"
    ]
    default_time_id = time_ids[0] if time_ids else 0

    rels: List[RelationshipUpsert] = []
    seen: set[Tuple[int, int, str]] = set()

    for concept in concepts:
        cid = int(concept_id_by_key.get(concept.concept_key) or 0)
        if cid <= 0:
            continue
        if domain_id > 0 and cid != domain_id:
            _append_rel(rels, seen, parent_id=domain_id, child_id=cid, rel_type="belongs_to_domain")

        if default_time_id > 0 and concept.semantic_type in {"measure", "metric"} and cid != default_time_id:
            _append_rel(rels, seen, parent_id=cid, child_id=default_time_id, rel_type="default_time_field_for")

        if concept.concept_key in source_map and domain_id > 0 and cid != domain_id:
            _append_rel(rels, seen, parent_id=cid, child_id=domain_id, rel_type="source_column_for")

    for spec in derived_specs:
        derived_id = int(concept_id_by_key.get(spec.concept_key) or 0)
        if derived_id <= 0:
            continue
        for dep_key in spec.depends_on:
            dep_id = int(concept_id_by_key.get(dep_key) or 0)
            if dep_id <= 0 or dep_id == derived_id:
                continue
            _append_rel(rels, seen, parent_id=derived_id, child_id=dep_id, rel_type="depends_on")

    return rels


def _build_value_aliases(
    *,
    vertical_norm: str,
    concept_id_by_key: Mapping[str, int],
    enriched: Sequence[EnrichedColumnProfile],
) -> List[ValueAliasUpsert]:
    rows: List[ValueAliasUpsert] = []
    seen: set[Tuple[int, str]] = set()
    for item in enriched:
        concept_key = _concept_key_for_profile(profile=item.profile, enrichment=item.enrichment)
        concept_id = int(concept_id_by_key.get(concept_key) or 0)
        if concept_id <= 0:
            continue
        if item.enrichment.semantic_type not in {"filter", "dimension"}:
            continue
        for raw in item.profile.sample_values[:15]:
            token = str(raw or "").strip()
            if token == "" or len(token) > 120:
                continue
            key = (concept_id, token.lower())
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                ValueAliasUpsert(
                    vertical_norm=vertical_norm,
                    semantic_concept_id=concept_id,
                    canonical_value=token,
                    alias_value=token,
                    match_kind="exact",
                    weight=0.8,
                )
            )
    return rows


def _preview_relationships_for_dry_run(
    *,
    concepts: Sequence[ConceptUpsert],
    derived_specs: Sequence[_DerivedMetricSpec],
    domain_name: str,
) -> List[Dict[str, Any]]:
    keys = [c.concept_key for c in concepts]
    concept_id_by_key = {k: i + 1 for i, k in enumerate(keys)}
    rels = _build_relationships(
        concept_id_by_key=concept_id_by_key,
        concepts=concepts,
        derived_specs=derived_specs,
        domain_name=domain_name,
        source_map={c.concept_key: c.name for c in concepts},
    )
    return [r.model_dump(mode="json") for r in rels]


def _pseudo_concept_rows(preview_concepts: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, row in enumerate(preview_concepts):
        rows.append(
            {
                "id": idx + 1,
                "vertical_norm": row.get("vertical_norm"),
                "concept_key": row.get("concept_key"),
                "name": row.get("name"),
                "description": row.get("description"),
                "semantic_type": row.get("semantic_type"),
                "sub_type": row.get("sub_type"),
                "entity": row.get("entity"),
            }
        )
    return rows


def _aliases_by_key(alias_rows: Sequence[Mapping[str, Any]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for row in alias_rows:
        concept_key = str(row.get("concept_key") or "").strip()
        alias = str(row.get("alias_key") or "").strip()
        if concept_key == "" or alias == "":
            continue
        out.setdefault(concept_key, [])
        if alias.lower() not in {x.lower() for x in out[concept_key]}:
            out[concept_key].append(alias)
    return out


def _domain_key_map_for_rows(*, rows: Sequence[Mapping[str, Any]], domain_name: str) -> Dict[str, str]:
    domain_key = _domain_concept_key(domain_name)
    out: Dict[str, str] = {}
    for row in rows:
        key = str(row.get("concept_key") or "").strip()
        if key == "":
            continue
        out[key] = domain_key
    return out


def _append_rel(
    rels: List[RelationshipUpsert],
    seen: set[Tuple[int, int, str]],
    *,
    parent_id: int,
    child_id: int,
    rel_type: str,
) -> None:
    if parent_id <= 0 or child_id <= 0 or parent_id == child_id:
        return
    key = (parent_id, child_id, rel_type)
    if key in seen:
        return
    seen.add(key)
    rels.append(
        RelationshipUpsert(
            parent_concept_id=parent_id,
            child_concept_id=child_id,
            relationship_type=rel_type,
        )
    )


def _concept_key_for_profile(*, profile: Any, enrichment: ColumnEnrichment) -> str:
    seed = f"{profile.table_name}_{profile.column_name}"
    semantic = enrichment.semantic_type
    if semantic in {"measure", "metric", "time_field", "dimension", "filter", "identifier"}:
        seed = profile.column_name
    return _to_concept_key(seed)


def _domain_concept_key(domain_name: str) -> str:
    return f"DOMAIN_{_to_concept_key(domain_name)}"


def _normalize_semantic_type(value: str) -> str:
    token = str(value or "other").strip().lower()
    if token in {"domain", "measure", "metric", "dimension", "filter", "time_field", "identifier"}:
        return token
    if token == "attribute":
        return "dimension"
    return "other"


def _to_concept_key(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip()).strip("_")
    token = re.sub(r"_+", "_", token)
    token = token.upper()
    return token[:150] if token else "UNKNOWN"


def _humanize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("_", " ").strip()).title()


def _normalize_vertical(value: str) -> str:
    token = str(value or "generic").strip().lower()
    return token or "generic"


def _entity_hint_from_column(column_name: str) -> Optional[str]:
    name = str(column_name or "").strip().lower()
    for entity in ("sales", "territory", "region", "account", "customer", "product", "rep", "order", "quota"):
        if entity in name:
            return entity
    return None


def _dedupe_aliases(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in values:
        token = str(item or "").strip()
        if token == "":
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out[:8]


def _find_key(keys: Sequence[str], *, tokens: Sequence[str]) -> str:
    for token in tokens:
        for key in keys:
            if token in key:
                return key
    return ""


def _looks_like_sales_domain(domain_name: Optional[str]) -> bool:
    token = str(domain_name or "").strip().lower()
    return "sales" in token and ("performance" in token or token == "sales")


def _apply_sales_performance_overrides(items: Sequence[EnrichedColumnProfile]) -> List[EnrichedColumnProfile]:
    overrides: List[EnrichedColumnProfile] = []
    for row in items:
        name = row.profile.column_name.lower()
        enrichment = row.enrichment

        if name in {"sales_amount", "quota_amount", "discount_amount", "order_count"}:
            enrichment = enrichment.model_copy(
                update={
                    "semantic_type": "measure" if name != "order_count" else "metric",
                    "planner_role": "measure" if name != "order_count" else "metric",
                    "measure_candidate": True,
                    "groupable": False,
                    "default_aggregations": ["sum"] if name == "order_count" else ["sum", "avg", "min", "max"],
                    "confidence": max(0.9, float(enrichment.confidence)),
                }
            )

        if name in {"account_name", "territory_name", "region_name", "sales_rep_name"}:
            enrichment = enrichment.model_copy(
                update={
                    "semantic_type": "dimension",
                    "planner_role": "dimension",
                    "groupable": True,
                    "filterable": True,
                    "confidence": max(0.9, float(enrichment.confidence)),
                }
            )

        overrides.append(EnrichedColumnProfile(profile=row.profile, enrichment=enrichment))
    return overrides
