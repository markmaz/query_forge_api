from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.nlp.tier2_spacy.training.dataset import DatasetEntity, DatasetExample, write_jsonl
from app.ports.sql_executor import ForgeQueryPort


@dataclass
class SeedBuildResult:
    examples: int
    output_path: str


class RegistrySeedBuilder:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def build(self, *, output_path: str, vertical_norm: str = "generic", limit: int = 500) -> SeedBuildResult:
        concepts = self._load_concepts(vertical_norm=vertical_norm, limit=limit)
        aliases = self._load_aliases(vertical_norm=vertical_norm, limit=limit)
        values = self._load_value_aliases(vertical_norm=vertical_norm, limit=limit)

        rows: List[DatasetExample] = []
        rows.extend(self._build_from_aliases(aliases))
        rows.extend(self._build_from_values(values))
        rows.extend(self._build_from_concepts(concepts))

        dedup: Dict[str, DatasetExample] = {}
        for row in rows:
            dedup.setdefault(row.text.lower(), row)

        write_jsonl(output_path, dedup.values())
        return SeedBuildResult(examples=len(dedup), output_path=output_path)

    def _load_concepts(self, *, vertical_norm: str, limit: int) -> List[Dict[str, Any]]:
        return self._sql.execute_query_mappings(
            """
            SELECT concept_key, name, entity, semantic_type
            FROM semantic_concept
            WHERE vertical_norm IN (:vertical_norm, 'generic')
              AND status = 'active'
            ORDER BY CASE WHEN vertical_norm = :vertical_norm THEN 0 ELSE 1 END, id ASC
            LIMIT :limit
            """,
            {"vertical_norm": vertical_norm, "limit": int(limit)},
        )

    def _load_aliases(self, *, vertical_norm: str, limit: int) -> List[Dict[str, Any]]:
        return self._sql.execute_query_mappings(
            """
            SELECT concept_key, alias_key
            FROM semantic_concept_alias
            WHERE vertical_norm IN (:vertical_norm, 'generic')
            ORDER BY CASE WHEN vertical_norm = :vertical_norm THEN 0 ELSE 1 END, weight DESC, id ASC
            LIMIT :limit
            """,
            {"vertical_norm": vertical_norm, "limit": int(limit)},
        )

    def _load_value_aliases(self, *, vertical_norm: str, limit: int) -> List[Dict[str, Any]]:
        return self._sql.execute_query_mappings(
            """
            SELECT sc.concept_key, va.alias_value, va.canonical_value
            FROM semantic_value_alias va
            JOIN semantic_concept sc ON sc.id = va.semantic_concept_id
            WHERE va.vertical_norm IN (:vertical_norm, 'generic')
            ORDER BY CASE WHEN va.vertical_norm = :vertical_norm THEN 0 ELSE 1 END, va.weight DESC, va.id ASC
            LIMIT :limit
            """,
            {"vertical_norm": vertical_norm, "limit": int(limit)},
        )

    def _build_from_aliases(self, aliases: List[Dict[str, Any]]) -> List[DatasetExample]:
        rows: List[DatasetExample] = []
        for row in aliases:
            alias = str(row.get("alias_key") or "").strip()
            concept_key = str(row.get("concept_key") or "").strip().upper()
            if alias == "" or concept_key == "":
                continue

            if concept_key.endswith("_NAME"):
                text = f"Find students with {alias} Holden"
                entities = self._entities_for_phrase(text, alias, "COURSE_TEXT")
                literal = self._entities_for_phrase(text, "Holden", "VALUE_LITERAL")
                entities.extend(literal)
                rows.append(
                    DatasetExample(
                        text=text,
                        entities=entities,
                        cats={"intent_lookup_by_name": 1.0, "intent_filter": 1.0},
                        meta={"source": "alias_seed", "concept_key": concept_key},
                    )
                )
            elif "SCHOOL" in concept_key:
                text = f"Show students at the Clarksville Elementary School by {alias}"
                entities = self._entities_for_phrase(text, "Clarksville Elementary School", "SLOT_SCHOOL_NAME")
                rows.append(
                    DatasetExample(
                        text=text,
                        entities=entities,
                        cats={"intent_filter": 1.0},
                        meta={"source": "alias_seed", "concept_key": concept_key},
                    )
                )
        return rows

    def _build_from_values(self, values: List[Dict[str, Any]]) -> List[DatasetExample]:
        rows: List[DatasetExample] = []
        for row in values:
            concept_key = str(row.get("concept_key") or "").strip().upper()
            alias_value = str(row.get("alias_value") or "").strip()
            canonical = str(row.get("canonical_value") or "").strip()
            if concept_key == "" or alias_value == "" or canonical == "":
                continue

            if "DISTRICT" in concept_key:
                text = f"Show students in {alias_value}"
                entities = self._entities_for_phrase(text, alias_value, "SLOT_DISTRICT_NAME")
            elif "SCHOOL" in concept_key:
                text = f"Show students at {alias_value}"
                entities = self._entities_for_phrase(text, alias_value, "SLOT_SCHOOL_NAME")
            else:
                text = f"Show students with {concept_key.lower()} {alias_value}"
                entities = self._entities_for_phrase(text, alias_value, "VALUE_LITERAL")

            rows.append(
                DatasetExample(
                    text=text,
                    entities=entities,
                    cats={"intent_filter": 1.0},
                    meta={"source": "value_alias_seed", "concept_key": concept_key, "canonical": canonical},
                )
            )
        return rows

    def _build_from_concepts(self, concepts: List[Dict[str, Any]]) -> List[DatasetExample]:
        rows: List[DatasetExample] = []
        for row in concepts:
            concept_key = str(row.get("concept_key") or "").strip().upper()
            name = str(row.get("name") or "").strip()
            entity = str(row.get("entity") or "").strip().lower()
            semantic_type = str(row.get("semantic_type") or "").strip().lower()
            if concept_key == "" or name == "":
                continue

            if "RACE" in concept_key:
                text = "Show black students"
                entities = self._entities_for_phrase(text, "black", "SLOT_RACE")
                cats = {"intent_demographic_slice": 1.0, "intent_filter": 1.0}
            elif "GRADE" in concept_key:
                text = "Show students in grade 3"
                entities = self._entities_for_phrase(text, "grade 3", "SLOT_GRADE")
                cats = {"intent_filter": 1.0}
            elif entity == "student" and "NAME" in concept_key:
                text = "Find all the students named Holden"
                entities = self._entities_for_phrase(text, "Holden", "VALUE_LITERAL")
                cats = {"intent_lookup_by_name": 1.0, "intent_filter": 1.0}
            elif semantic_type in {"flag", "attribute"}:
                text = f"Show students where {name} is true"
                entities = self._entities_for_phrase(text, name, "VALUE_LITERAL")
                cats = {"intent_filter": 1.0}
            else:
                continue

            rows.append(
                DatasetExample(
                    text=text,
                    entities=entities,
                    cats=cats,
                    meta={"source": "concept_seed", "concept_key": concept_key},
                )
            )
        return rows

    @staticmethod
    def _entities_for_phrase(text: str, phrase: str, label: str) -> List[DatasetEntity]:
        phrase_text = str(phrase or "").strip()
        if phrase_text == "":
            return []
        match = re.search(re.escape(phrase_text), text, flags=re.IGNORECASE)
        if not match:
            return []
        return [DatasetEntity(start=match.start(), end=match.end(), label=label)]


def generate_seed_jsonl(*, output_path: str, vertical_norm: str = "generic", limit: int = 500) -> SeedBuildResult:
    return RegistrySeedBuilder().build(output_path=output_path, vertical_norm=vertical_norm, limit=limit)
