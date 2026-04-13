from __future__ import annotations

from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort

_LEGACY_VERTICAL_PREDICATE = (
    "LOWER(TRIM(COALESCE(vertical_norm, ''))) IN "
    "('education', 'global', '__global__', '', 'none', 'null')"
)

_COUNT_TABLES = (
    "semantic_concept",
    "semantic_concept_alias",
    "workspace_column_semantic_concept_map",
    "semantic_value_alias",
)

_NORMALIZATION_WRITES = (
    """
    DELETE dup
    FROM semantic_concept dup
    JOIN semantic_concept keep
      ON dup.id > keep.id
     AND dup.concept_key = keep.concept_key
     AND LOWER(TRIM(COALESCE(dup.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
     AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
    """,
    """
    DELETE old
    FROM semantic_concept old
    JOIN semantic_concept keep
      ON keep.concept_key = old.concept_key
     AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) = 'generic'
    WHERE LOWER(TRIM(COALESCE(old.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
      AND old.id <> keep.id
    """,
    """
    UPDATE semantic_concept
       SET vertical_norm = 'generic'
     WHERE LOWER(TRIM(COALESCE(vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
    """,
    """
    DELETE dup
    FROM semantic_concept_alias dup
    JOIN semantic_concept_alias keep
      ON dup.id > keep.id
     AND dup.alias_key = keep.alias_key
     AND dup.match_kind = keep.match_kind
     AND LOWER(TRIM(COALESCE(dup.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
     AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
    """,
    """
    DELETE old
    FROM semantic_concept_alias old
    JOIN semantic_concept_alias keep
      ON keep.alias_key = old.alias_key
     AND keep.match_kind = old.match_kind
     AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) = 'generic'
    WHERE LOWER(TRIM(COALESCE(old.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
      AND old.id <> keep.id
    """,
    """
    UPDATE semantic_concept_alias
       SET vertical_norm = 'generic'
     WHERE LOWER(TRIM(COALESCE(vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
    """,
    """
    DELETE dup
    FROM workspace_column_semantic_concept_map dup
    JOIN workspace_column_semantic_concept_map keep
      ON dup.id > keep.id
     AND dup.semantic_concept_id = keep.semantic_concept_id
     AND dup.workspace_column_id = keep.workspace_column_id
     AND dup.relationship_kind = keep.relationship_kind
     AND LOWER(TRIM(COALESCE(dup.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
     AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
    """,
    """
    DELETE old
    FROM workspace_column_semantic_concept_map old
    JOIN workspace_column_semantic_concept_map keep
      ON keep.semantic_concept_id = old.semantic_concept_id
     AND keep.workspace_column_id = old.workspace_column_id
     AND keep.relationship_kind = old.relationship_kind
     AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) = 'generic'
    WHERE LOWER(TRIM(COALESCE(old.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
      AND old.id <> keep.id
    """,
    """
    UPDATE workspace_column_semantic_concept_map
       SET vertical_norm = 'generic'
     WHERE LOWER(TRIM(COALESCE(vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
    """,
    """
    DELETE dup
    FROM semantic_value_alias dup
    JOIN semantic_value_alias keep
      ON dup.id > keep.id
     AND dup.semantic_concept_id = keep.semantic_concept_id
     AND dup.alias_value = keep.alias_value
     AND dup.match_kind = keep.match_kind
     AND LOWER(TRIM(COALESCE(dup.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
     AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
    """,
    """
    DELETE old
    FROM semantic_value_alias old
    JOIN semantic_value_alias keep
      ON keep.semantic_concept_id = old.semantic_concept_id
     AND keep.alias_value = old.alias_value
     AND keep.match_kind = old.match_kind
     AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) = 'generic'
    WHERE LOWER(TRIM(COALESCE(old.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
      AND old.id <> keep.id
    """,
    """
    UPDATE semantic_value_alias
       SET vertical_norm = 'generic'
     WHERE LOWER(TRIM(COALESCE(vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
    """,
)


class SemanticStorageNormalizationService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def audit_legacy_vertical_rows(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for table_name in _COUNT_TABLES:
            rows = self._sql.execute_query_mappings(
                f"""
                SELECT COUNT(*) AS count
                FROM {table_name}
                WHERE {_LEGACY_VERTICAL_PREDICATE}
                """
            )
            out[table_name] = _read_count(rows)
        return out

    def normalize_legacy_vertical_rows(self, *, dry_run: bool = True) -> Dict[str, Any]:
        before = self.audit_legacy_vertical_rows()
        if dry_run:
            return {
                "dry_run": True,
                "legacy_counts_before": before,
                "write_steps_executed": 0,
            }

        for query in _NORMALIZATION_WRITES:
            self._sql.execute_write(query)

        after = self.audit_legacy_vertical_rows()
        return {
            "dry_run": False,
            "legacy_counts_before": before,
            "legacy_counts_after": after,
            "write_steps_executed": len(_NORMALIZATION_WRITES),
        }


def _read_count(rows: Any) -> int:
    if not rows:
        return 0
    return int(rows[0].get("count") or 0)


__all__ = ["SemanticStorageNormalizationService"]
