from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort, ForgeQueryTx
from app.services.semantic.catalog.catalog_models import (
    AliasUpsert,
    ConceptUpsert,
    RelationshipUpsert,
    ValueAliasUpsert,
)

logger = logging.getLogger(__name__)
RELATIONSHIP_FK_TARGET_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError)


class SemanticCatalogRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._relationship_fk_target_cache: Optional[str] = None

    def apply_catalog_writes(
        self,
        *,
        concepts: Iterable[ConceptUpsert],
        aliases: Iterable[AliasUpsert],
        relationships: Iterable[RelationshipUpsert],
        value_aliases: Iterable[ValueAliasUpsert],
    ) -> Dict[str, Any]:
        concept_rows = list(concepts)
        alias_rows = list(aliases)
        rel_rows = list(relationships)
        value_alias_rows = list(value_aliases)

        with self._sql.transaction() as tx:
            concept_id_by_key = self._upsert_concepts(tx=tx, concepts=concept_rows)
            alias_count = self._upsert_aliases(tx=tx, aliases=alias_rows)
            relationship_count = self._upsert_relationships(tx=tx, relationships=rel_rows)
            value_alias_count = self._upsert_value_aliases(tx=tx, value_aliases=value_alias_rows)

        return {
            "concept_id_by_key": concept_id_by_key,
            "concept_count": len(concept_id_by_key),
            "alias_count": alias_count,
            "relationship_count": relationship_count,
            "value_alias_count": value_alias_count,
        }

    def get_concepts(
        self,
        *,
        vertical_norm: str,
        concept_keys: Iterable[str],
    ) -> List[Dict[str, Any]]:
        keys = [str(k or "").strip() for k in concept_keys if str(k or "").strip()]
        if not keys:
            return []

        params: Dict[str, Any] = {"vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic"}
        placeholders: List[str] = []
        for idx, key in enumerate(keys):
            param_name = f"k_{idx}"
            params[param_name] = key
            placeholders.append(f":{param_name}")

        return self._sql.execute_query_mappings(
            f"""
            SELECT
              id,
              vertical_norm,
              concept_key,
              name,
              description,
              semantic_type,
              sub_type,
              entity,
              filter_allowed,
              group_by_allowed,
              aggregation_allowed,
              is_identifier,
              is_metric
            FROM semantic_concept
            WHERE vertical_norm = :vertical_norm
              AND concept_key IN ({', '.join(placeholders)})
            ORDER BY id ASC
            """,
            params,
        )

    def get_aliases_by_concept_keys(
        self,
        *,
        vertical_norm: str,
        concept_keys: Iterable[str],
    ) -> Dict[str, List[str]]:
        keys = [str(k or "").strip() for k in concept_keys if str(k or "").strip()]
        if not keys:
            return {}
        params: Dict[str, Any] = {"vertical_norm": str(vertical_norm or "generic").strip().lower() or "generic"}
        placeholders: List[str] = []
        for idx, key in enumerate(keys):
            name = f"k_{idx}"
            params[name] = key
            placeholders.append(f":{name}")

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT concept_key, alias_key
            FROM semantic_concept_alias
            WHERE vertical_norm = :vertical_norm
              AND concept_key IN ({', '.join(placeholders)})
            ORDER BY concept_key ASC, weight DESC, id ASC
            """,
            params,
        )
        out: Dict[str, List[str]] = {}
        for row in rows:
            key = str(row.get("concept_key") or "").strip()
            alias = str(row.get("alias_key") or "").strip()
            if key == "" or alias == "":
                continue
            out.setdefault(key, [])
            if alias.lower() not in {item.lower() for item in out[key]}:
                out[key].append(alias)
        return out

    def _upsert_concepts(self, *, tx: ForgeQueryTx, concepts: List[ConceptUpsert]) -> Dict[str, int]:
        concept_id_by_key: Dict[str, int] = {}
        for row in concepts:
            payload = row.model_dump(mode="json")
            tx.execute_write(
                """
                INSERT INTO semantic_concept (
                  vertical_norm,
                  concept_key,
                  name,
                  description,
                  semantic_type,
                  sub_type,
                  entity,
                  granularity_rank,
                  filter_allowed,
                  group_by_allowed,
                  aggregation_allowed,
                  is_identifier,
                  is_metric,
                  display_priority,
                  `sensitive`,
                  `status`
                ) VALUES (
                  :vertical_norm,
                  :concept_key,
                  :name,
                  :description,
                  :semantic_type,
                  :sub_type,
                  :entity,
                  :granularity_rank,
                  :filter_allowed,
                  :group_by_allowed,
                  :aggregation_allowed,
                  :is_identifier,
                  :is_metric,
                  :display_priority,
                  :sensitive,
                  :status
                )
                ON DUPLICATE KEY UPDATE
                  name = VALUES(name),
                  description = VALUES(description),
                  semantic_type = VALUES(semantic_type),
                  sub_type = VALUES(sub_type),
                  entity = VALUES(entity),
                  granularity_rank = VALUES(granularity_rank),
                  filter_allowed = VALUES(filter_allowed),
                  group_by_allowed = VALUES(group_by_allowed),
                  aggregation_allowed = VALUES(aggregation_allowed),
                  is_identifier = VALUES(is_identifier),
                  is_metric = VALUES(is_metric),
                  display_priority = VALUES(display_priority),
                  `sensitive` = VALUES(`sensitive`),
                  `status` = VALUES(`status`),
                  updated_at = CURRENT_TIMESTAMP
                """,
                payload,
            )
            result = tx.execute_query_mappings(
                """
                SELECT id
                FROM semantic_concept
                WHERE vertical_norm = :vertical_norm
                  AND concept_key = :concept_key
                LIMIT 1
                """,
                {
                    "vertical_norm": payload["vertical_norm"],
                    "concept_key": payload["concept_key"],
                },
            )
            if result:
                concept_id_by_key[str(payload["concept_key"])] = int(result[0].get("id") or 0)
        return concept_id_by_key

    def _upsert_aliases(self, *, tx: ForgeQueryTx, aliases: List[AliasUpsert]) -> int:
        written = 0
        for row in aliases:
            payload = row.model_dump(mode="json")
            tx.execute_write(
                """
                INSERT INTO semantic_concept_alias (
                  vertical_norm,
                  alias_key,
                  concept_key,
                  match_kind,
                  weight
                ) VALUES (
                  :vertical_norm,
                  :alias_key,
                  :concept_key,
                  :match_kind,
                  :weight
                )
                ON DUPLICATE KEY UPDATE
                  concept_key = VALUES(concept_key),
                  weight = VALUES(weight)
                """,
                payload,
            )
            written += 1
        return written

    def _upsert_relationships(self, *, tx: ForgeQueryTx, relationships: List[RelationshipUpsert]) -> int:
        fk_target = self._get_relationship_fk_target(tx=tx)
        payloads = self._prepare_relationship_payloads(
            tx=tx,
            relationships=relationships,
            fk_target=fk_target,
        )
        written = 0
        for payload in payloads:
            if int(payload["parent_concept_id"]) == int(payload["child_concept_id"]):
                continue
            tx.execute_write(
                """
                INSERT INTO semantic_relationship (
                  parent_concept_id,
                  child_concept_id,
                  relationship_type
                ) VALUES (
                  :parent_concept_id,
                  :child_concept_id,
                  :relationship_type
                )
                ON DUPLICATE KEY UPDATE
                  relationship_type = VALUES(relationship_type)
                """,
                payload,
            )
            written += 1
        return written

    def _prepare_relationship_payloads(
        self,
        *,
        tx: ForgeQueryTx,
        relationships: List[RelationshipUpsert],
        fk_target: str,
    ) -> List[Dict[str, Any]]:
        base_payloads: List[Dict[str, Any]] = [row.model_dump(mode="json") for row in relationships]
        if fk_target != "semantic_registry":
            return base_payloads
        concept_ids = {
            int(item["parent_concept_id"])
            for item in base_payloads
        } | {
            int(item["child_concept_id"])
            for item in base_payloads
        }
        if not concept_ids:
            return base_payloads
        mapping = self._map_semantic_concept_ids_to_registry_ids(tx=tx, semantic_concept_ids=concept_ids)
        remapped: List[Dict[str, Any]] = []
        for payload in base_payloads:
            parent_source = int(payload["parent_concept_id"])
            child_source = int(payload["child_concept_id"])
            parent_target = mapping.get(parent_source)
            child_target = mapping.get(child_source)
            if parent_target is None or child_target is None:
                logger.warning(
                    "semantic_catalog relationship dropped due to missing registry mapping parent=%s child=%s",
                    parent_source,
                    child_source,
                )
                continue
            remapped.append(
                {
                    "parent_concept_id": int(parent_target),
                    "child_concept_id": int(child_target),
                    "relationship_type": str(payload.get("relationship_type") or "").strip().lower(),
                }
            )
        return remapped

    def _map_semantic_concept_ids_to_registry_ids(
        self,
        *,
        tx: ForgeQueryTx,
        semantic_concept_ids: Iterable[int],
    ) -> Dict[int, int]:
        ids = sorted({int(item) for item in semantic_concept_ids if int(item) > 0})
        if not ids:
            return {}
        in_sql, in_params = _build_in_clause("cid_", ids)
        concept_rows = tx.execute_query_mappings(
            f"""
            SELECT
              id,
              LOWER(COALESCE(vertical_norm, 'generic')) AS vertical_norm,
              concept_key,
              semantic_type,
              sub_type,
              entity,
              description,
              COALESCE(granularity_rank, 0) AS granularity_rank,
              COALESCE(filter_allowed, 1) AS filter_allowed,
              COALESCE(group_by_allowed, 1) AS group_by_allowed,
              COALESCE(aggregation_allowed, 1) AS aggregation_allowed,
              COALESCE(is_identifier, 0) AS is_identifier,
              COALESCE(is_metric, 0) AS is_metric,
              COALESCE(display_priority, 0) AS display_priority,
              COALESCE(`sensitive`, 0) AS `sensitive`
            FROM semantic_concept
            WHERE id IN ({in_sql})
            """,
            in_params,
        )
        if not concept_rows:
            return {}

        for row in concept_rows:
            vertical = str(row.get("vertical_norm") or "generic").strip().lower() or "generic"
            tx.execute_write(
                """
                INSERT INTO semantic_registry (
                  vertical,
                  concept_key,
                  semantic_type,
                  sub_type,
                  entity,
                  description,
                  granularity_rank,
                  filter_allowed,
                  group_by_allowed,
                  aggregation_allowed,
                  is_identifier,
                  is_metric,
                  display_priority,
                  `sensitive`
                ) VALUES (
                  :vertical,
                  :concept_key,
                  :semantic_type,
                  :sub_type,
                  :entity,
                  :description,
                  :granularity_rank,
                  :filter_allowed,
                  :group_by_allowed,
                  :aggregation_allowed,
                  :is_identifier,
                  :is_metric,
                  :display_priority,
                  :sensitive
                )
                ON DUPLICATE KEY UPDATE
                  semantic_type = VALUES(semantic_type),
                  sub_type = VALUES(sub_type),
                  entity = VALUES(entity),
                  description = VALUES(description),
                  granularity_rank = VALUES(granularity_rank),
                  filter_allowed = VALUES(filter_allowed),
                  group_by_allowed = VALUES(group_by_allowed),
                  aggregation_allowed = VALUES(aggregation_allowed),
                  is_identifier = VALUES(is_identifier),
                  is_metric = VALUES(is_metric),
                  display_priority = VALUES(display_priority),
                  `sensitive` = VALUES(`sensitive`),
                  updated_at = CURRENT_TIMESTAMP
                """,
                {
                    "vertical": vertical,
                    "concept_key": str(row.get("concept_key") or "").strip(),
                    "semantic_type": str(row.get("semantic_type") or "other").strip().lower() or "other",
                    "sub_type": row.get("sub_type"),
                    "entity": row.get("entity"),
                    "description": row.get("description"),
                    "granularity_rank": int(row.get("granularity_rank") or 0),
                    "filter_allowed": int(bool(row.get("filter_allowed"))),
                    "group_by_allowed": int(bool(row.get("group_by_allowed"))),
                    "aggregation_allowed": int(bool(row.get("aggregation_allowed"))),
                    "is_identifier": int(bool(row.get("is_identifier"))),
                    "is_metric": int(bool(row.get("is_metric"))),
                    "display_priority": int(row.get("display_priority") or 0),
                    "sensitive": int(bool(row.get("sensitive"))),
                },
            )

        mapped_rows = tx.execute_query_mappings(
            f"""
            SELECT
              sc.id AS semantic_concept_id,
              sr.id AS semantic_registry_id
            FROM semantic_concept sc
            JOIN semantic_registry sr
              ON UPPER(TRIM(sr.concept_key)) = UPPER(TRIM(sc.concept_key))
             AND LOWER(COALESCE(sr.vertical_norm, 'generic')) = LOWER(COALESCE(sc.vertical_norm, 'generic'))
            WHERE sc.id IN ({in_sql})
            """,
            in_params,
        )
        out: Dict[int, int] = {}
        for row in mapped_rows:
            concept_id = int(row.get("semantic_concept_id") or 0)
            registry_id = int(row.get("semantic_registry_id") or 0)
            if concept_id > 0 and registry_id > 0:
                out[concept_id] = registry_id
        return out

    def _upsert_value_aliases(self, *, tx: ForgeQueryTx, value_aliases: List[ValueAliasUpsert]) -> int:
        written = 0
        for row in value_aliases:
            payload = row.model_dump(mode="json")
            tx.execute_write(
                """
                INSERT INTO semantic_value_alias (
                  vertical_norm,
                  semantic_concept_id,
                  canonical_value,
                  alias_value,
                  match_kind,
                  weight
                ) VALUES (
                  :vertical_norm,
                  :semantic_concept_id,
                  :canonical_value,
                  :alias_value,
                  :match_kind,
                  :weight
                )
                ON DUPLICATE KEY UPDATE
                  canonical_value = VALUES(canonical_value),
                  weight = VALUES(weight)
                """,
                payload,
            )
            written += 1
        return written

    def _get_relationship_fk_target(self, *, tx: Optional[ForgeQueryTx] = None) -> str:
        if self._relationship_fk_target_cache:
            return self._relationship_fk_target_cache
        executor = tx if tx is not None else self._sql
        try:
            rows = executor.execute_query_mappings(
                """
                SELECT LOWER(COALESCE(kcu.REFERENCED_TABLE_NAME, '')) AS referenced_table_name
                FROM information_schema.KEY_COLUMN_USAGE kcu
                WHERE kcu.TABLE_SCHEMA = DATABASE()
                  AND kcu.TABLE_NAME = 'semantic_relationship'
                  AND kcu.COLUMN_NAME = 'parent_concept_id'
                  AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
                LIMIT 1
                """,
                {},
            )
            target = str((rows[0].get("referenced_table_name") if rows else "") or "").strip().lower()
            if target in {"semantic_registry", "semantic_concept"}:
                self._relationship_fk_target_cache = target
                return target
        except RELATIONSHIP_FK_TARGET_FALLBACK_ERRORS:
            pass
        self._relationship_fk_target_cache = "semantic_concept"
        return self._relationship_fk_target_cache


def _build_in_clause(prefix: str, values: Iterable[Any]) -> tuple[str, Dict[str, Any]]:
    params: Dict[str, Any] = {}
    tokens: List[str] = []
    for idx, value in enumerate(values):
        key = f"{prefix}{idx}"
        tokens.append(f":{key}")
        params[key] = value
    if not tokens:
        return "NULL", params
    return ", ".join(tokens), params
