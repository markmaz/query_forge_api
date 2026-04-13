from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort

from app.services.planner.semantic_retrieval_helpers import (
    build_in_clause,
)
from app.services.semantic.vertical_norm import normalize_semantic_vertical


class SemanticCatalogLookupRepository:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._relationship_fk_target_cache: Optional[str] = None

    def load_concepts(self, *, vertical_norm: str) -> List[Dict[str, Any]]:
        vertical = normalize_semantic_vertical(vertical_norm)
        return self._sql.execute_query_mappings(
            """
            SELECT
              id,
              concept_key,
              name,
              COALESCE(description, '') AS description,
              LOWER(COALESCE(semantic_type, 'other')) AS semantic_type,
              LOWER(COALESCE(vertical_norm, 'generic')) AS vertical_norm,
              LOWER(COALESCE(`status`, 'active')) AS `status`
            FROM semantic_concept
            WHERE LOWER(COALESCE(vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
            ORDER BY
              CASE WHEN LOWER(COALESCE(vertical_norm, 'generic')) = :vertical_norm THEN 0 ELSE 1 END,
              id ASC
            """,
            {"vertical_norm": vertical},
        )

    def load_aliases(self, *, vertical_norm: str) -> List[Dict[str, Any]]:
        params = {"vertical_norm": normalize_semantic_vertical(vertical_norm)}
        try:
            return self._sql.execute_query_mappings(
                """
                SELECT
                  UPPER(TRIM(concept_key)) AS concept_key,
                  alias_key,
                  COALESCE(weight, 1.0) AS weight,
                  LOWER(COALESCE(match_kind, 'contains')) AS match_kind
                FROM semantic_concept_alias
                WHERE LOWER(COALESCE(vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
                ORDER BY id ASC
                """,
                params,
            )
        except (OSError, RuntimeError, ValueError, SQLAlchemyError) as exc:
            if not _is_schema_compatibility_error(exc, "match_kind"):
                raise
            return self._sql.execute_query_mappings(
                """
                SELECT
                  UPPER(TRIM(concept_key)) AS concept_key,
                  alias_key,
                  COALESCE(weight, 1.0) AS weight,
                  'contains' AS match_kind
                FROM semantic_concept_alias
                WHERE LOWER(COALESCE(vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
                ORDER BY id ASC
                """,
                params,
            )

    def load_relationships(self, *, vertical_norm: str) -> List[Dict[str, Any]]:
        params = {"vertical_norm": normalize_semantic_vertical(vertical_norm)}
        fk_target = self._get_relationship_fk_target()
        if fk_target == "semantic_registry":
            return self._sql.execute_query_mappings(
                """
                SELECT
                  UPPER(TRIM(parent.concept_key)) AS parent_key,
                  UPPER(TRIM(child.concept_key)) AS child_key,
                  LOWER(TRIM(sr.relationship_type)) AS relationship_type
                FROM semantic_relationship sr
                JOIN semantic_registry parent ON parent.id = sr.parent_concept_id
                JOIN semantic_registry child ON child.id = sr.child_concept_id
                WHERE LOWER(COALESCE(parent.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
                  AND LOWER(COALESCE(child.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
                ORDER BY sr.id ASC
                """,
                params,
            )
        return self._sql.execute_query_mappings(
            """
            SELECT
              UPPER(TRIM(parent.concept_key)) AS parent_key,
              UPPER(TRIM(child.concept_key)) AS child_key,
              LOWER(TRIM(sr.relationship_type)) AS relationship_type
            FROM semantic_relationship sr
            JOIN semantic_concept parent ON parent.id = sr.parent_concept_id
            JOIN semantic_concept child ON child.id = sr.child_concept_id
            WHERE LOWER(COALESCE(parent.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
              AND LOWER(COALESCE(child.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
            ORDER BY sr.id ASC
            """,
            params,
        )

    def load_concept_column_maps(self, *, vertical_norm: str) -> List[Dict[str, Any]]:
        params = {"vertical_norm": normalize_semantic_vertical(vertical_norm)}
        try:
            return self._sql.execute_query_mappings(
                """
                SELECT
                  m.semantic_concept_id,
                  UPPER(TRIM(sc.concept_key)) AS concept_key,
                  m.workspace_column_id,
                  m.model_column_id,
                  LOWER(COALESCE(m.relationship_kind, 'primary')) AS relationship_kind,
                  COALESCE(m.weight, 1.0) AS weight
                FROM workspace_column_semantic_concept_map m
                JOIN semantic_concept sc ON sc.id = m.semantic_concept_id
                WHERE LOWER(COALESCE(m.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
                ORDER BY
                  CASE WHEN LOWER(COALESCE(m.relationship_kind, 'primary')) = 'primary' THEN 0 ELSE 1 END,
                  m.weight DESC,
                  m.id ASC
                """,
                params,
            )
        except (OSError, RuntimeError, ValueError, SQLAlchemyError) as exc:
            if not _is_schema_compatibility_error(exc, "model_column_id"):
                raise
            return self._sql.execute_query_mappings(
                """
                SELECT
                  m.semantic_concept_id,
                  UPPER(TRIM(sc.concept_key)) AS concept_key,
                  m.workspace_column_id,
                  NULL AS model_column_id,
                  LOWER(COALESCE(m.relationship_kind, 'primary')) AS relationship_kind,
                  COALESCE(m.weight, 1.0) AS weight
                FROM workspace_column_semantic_concept_map m
                JOIN semantic_concept sc ON sc.id = m.semantic_concept_id
                WHERE LOWER(COALESCE(m.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
                ORDER BY
                  CASE WHEN LOWER(COALESCE(m.relationship_kind, 'primary')) = 'primary' THEN 0 ELSE 1 END,
                  m.weight DESC,
                  m.id ASC
                """,
                params,
            )

    def search_value_aliases(
        self,
        *,
        vertical_norm: str,
        ngrams: Sequence[str],
        semantic_concept_ids: Sequence[int],
    ) -> List[Dict[str, Any]]:
        if not ngrams or not semantic_concept_ids:
            return []

        rows: List[Dict[str, Any]] = []
        in_sql, in_params = build_in_clause("cid_", semantic_concept_ids)
        vertical = normalize_semantic_vertical(vertical_norm)
        for ngram in ngrams:
            params = {
                "vertical_norm": vertical,
                "ngram": str(ngram or "").strip().lower(),
                **in_params,
            }
            if params["ngram"] == "":
                continue
            rows.extend(
                self._sql.execute_query_mappings(
                    f"""
                    SELECT
                      va.semantic_concept_id,
                      LOWER(TRIM(va.alias_value)) AS alias_value,
                      va.canonical_value,
                      LOWER(COALESCE(va.match_kind, 'contains')) AS match_kind,
                      COALESCE(va.weight, 1.0) AS weight
                    FROM semantic_value_alias va
                    WHERE LOWER(COALESCE(va.vertical_norm, 'generic')) IN (:vertical_norm, 'generic')
                      AND va.semantic_concept_id IN ({in_sql})
                      AND (
                        (LOWER(COALESCE(va.match_kind, 'contains')) = 'exact' AND LOWER(va.alias_value) = :ngram)
                        OR
                        (LOWER(COALESCE(va.match_kind, 'contains')) = 'contains' AND :ngram LIKE CONCAT('%', LOWER(va.alias_value), '%'))
                        OR
                        (LOWER(COALESCE(va.match_kind, 'contains')) = 'prefix' AND :ngram LIKE CONCAT(LOWER(va.alias_value), '%'))
                      )
                    ORDER BY
                      CASE WHEN LOWER(COALESCE(va.vertical_norm, 'generic')) = :vertical_norm THEN 0 ELSE 1 END,
                      va.weight DESC,
                      va.id ASC
                    """,
                    params,
                )
            )
        return rows

    def load_suggestion_scores(self) -> Dict[str, int]:
        try:
            rows = self._sql.execute_query_mappings(
                """
                SELECT
                  UPPER(TRIM(proposed_concept_key)) AS concept_key,
                  COUNT(*) AS usage_count
                FROM semantic_suggestion_item
                WHERE proposed_concept_key IS NOT NULL
                  AND proposed_concept_key <> ''
                  AND decision_status IN ('auto_approved', 'approved', 'applied')
                GROUP BY UPPER(TRIM(proposed_concept_key))
                """,
                {},
            )
        except (OSError, RuntimeError, ValueError, SQLAlchemyError) as exc:
            if not _is_schema_compatibility_error(exc, "semantic_suggestion_item"):
                raise
            return {}
        out: Dict[str, int] = {}
        for row in rows:
            key = str(row.get("concept_key") or "").strip().upper()
            if key == "":
                continue
            out[key] = int(row.get("usage_count") or 0)
        return out

    def _get_relationship_fk_target(self) -> str:
        if self._relationship_fk_target_cache:
            return self._relationship_fk_target_cache
        try:
            rows = self._sql.execute_query_mappings(
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
            target = str(
                (rows[0].get("referenced_table_name") if rows else "") or ""
            ).strip().lower()
            if target in {"semantic_registry", "semantic_concept"}:
                self._relationship_fk_target_cache = target
                return target
        except (OSError, RuntimeError, ValueError, SQLAlchemyError):
            pass
        self._relationship_fk_target_cache = "semantic_concept"
        return self._relationship_fk_target_cache


def _is_schema_compatibility_error(exc: Exception, *needles: str) -> bool:
    message = str(exc or "").strip().lower()
    if not message:
        return False
    schema_markers = (
        "unknown column",
        "undefined column",
        "no such column",
        "doesn't exist",
        "does not exist",
        "no such table",
        "undefined table",
    )
    if not any(marker in message for marker in schema_markers):
        return False
    return all(str(needle or "").strip().lower() in message for needle in needles)
