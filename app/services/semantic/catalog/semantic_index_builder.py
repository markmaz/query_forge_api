from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from app.services.semantic.catalog.catalog_models import SemanticIndexItem


class SemanticIndexBuilder:
    """
    Stage 4: build vector-ready text blocks per concept for embedding/index pipelines.
    """

    def build_items(
        self,
        *,
        concept_rows: Iterable[Mapping[str, Any]],
        aliases_by_key: Mapping[str, List[str]],
        domain_key_by_concept: Mapping[str, str],
        source_column_by_concept: Mapping[str, str],
    ) -> List[SemanticIndexItem]:
        items: List[SemanticIndexItem] = []
        for row in concept_rows:
            concept_id = int(row.get("id") or 0)
            concept_key = str(row.get("concept_key") or "").strip()
            if concept_id <= 0 or concept_key == "":
                continue

            name = str(row.get("name") or concept_key).strip()
            description = str(row.get("description") or "").strip()
            semantic_type = str(row.get("semantic_type") or "other").strip()
            sub_type = str(row.get("sub_type") or "").strip()
            entity = str(row.get("entity") or "").strip()
            aliases = aliases_by_key.get(concept_key, [])
            domain_key = str(domain_key_by_concept.get(concept_key) or "").strip()
            source_column = str(source_column_by_concept.get(concept_key) or "").strip()

            parts = [
                f"concept_key: {concept_key}",
                f"name: {name}",
                f"semantic_type: {semantic_type}",
            ]
            if sub_type:
                parts.append(f"sub_type: {sub_type}")
            if entity:
                parts.append(f"entity: {entity}")
            if description:
                parts.append(f"description: {description}")
            if aliases:
                parts.append(f"aliases: {', '.join(aliases)}")
            if domain_key:
                parts.append(f"domain: {domain_key}")
            if source_column:
                parts.append(f"source_column: {source_column}")

            vector_text = "\n".join(parts)
            items.append(
                SemanticIndexItem(
                    concept_id=concept_id,
                    concept_key=concept_key,
                    vector_text=vector_text,
                    metadata={
                        "name": name,
                        "semantic_type": semantic_type,
                        "sub_type": sub_type or None,
                        "entity": entity or None,
                        "aliases": aliases,
                        "domain_key": domain_key or None,
                        "source_column": source_column or None,
                    },
                )
            )
        return items
