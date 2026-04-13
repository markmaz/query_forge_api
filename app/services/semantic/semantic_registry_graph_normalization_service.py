from __future__ import annotations

from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort

_LEGACY_VERTICAL_PREDICATE = (
    "LOWER(TRIM(COALESCE(sr.vertical_norm, ''))) IN "
    "('education', 'global', '__global__', '', 'none', 'null')"
)

_AUDIT_QUERIES = (
    (
        "semantic_registry",
        f"""
        SELECT COUNT(*) AS count
        FROM semantic_registry sr
        WHERE {_LEGACY_VERTICAL_PREDICATE}
        """,
    ),
    (
        "semantic_column_map",
        f"""
        SELECT COUNT(*) AS count
        FROM semantic_column_map scm
        JOIN semantic_registry sr
          ON sr.id = scm.semantic_registry_id
        WHERE {_LEGACY_VERTICAL_PREDICATE}
        """,
    ),
    (
        "semantic_relationship",
        f"""
        SELECT COUNT(*) AS count
        FROM semantic_relationship rel
        JOIN semantic_registry parent
          ON parent.id = rel.parent_concept_id
        JOIN semantic_registry child
          ON child.id = rel.child_concept_id
        WHERE LOWER(TRIM(COALESCE(parent.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
           OR LOWER(TRIM(COALESCE(child.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
        """,
    ),
)

_NORMALIZATION_WRITES = (
    "DROP TEMPORARY TABLE IF EXISTS _semantic_registry_vertical_remap",
    """
    CREATE TEMPORARY TABLE _semantic_registry_vertical_remap (
      old_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
      new_id BIGINT UNSIGNED NOT NULL
    )
    """,
    """
    INSERT INTO _semantic_registry_vertical_remap (old_id, new_id)
    SELECT legacy.id AS old_id, generic.id AS new_id
    FROM semantic_registry legacy
    JOIN semantic_registry generic
      ON generic.concept_key = legacy.concept_key
     AND LOWER(TRIM(COALESCE(generic.vertical_norm, ''))) = 'generic'
    WHERE LOWER(TRIM(COALESCE(legacy.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
      AND legacy.id <> generic.id
    """,
    """
    INSERT INTO _semantic_registry_vertical_remap (old_id, new_id)
    SELECT legacy.id AS old_id, keeper.keep_id AS new_id
    FROM semantic_registry legacy
    JOIN (
        SELECT concept_key, MIN(id) AS keep_id
        FROM semantic_registry
        WHERE LOWER(TRIM(COALESCE(vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
        GROUP BY concept_key
    ) keeper
      ON keeper.concept_key = legacy.concept_key
    WHERE LOWER(TRIM(COALESCE(legacy.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
      AND NOT EXISTS (
        SELECT 1
        FROM _semantic_registry_vertical_remap existing
        WHERE existing.old_id = legacy.id
      )
    """,
    """
    UPDATE semantic_registry sr
    JOIN _semantic_registry_vertical_remap remap
      ON remap.old_id = sr.id
     AND remap.old_id = remap.new_id
    SET sr.vertical = 'generic'
    WHERE LOWER(TRIM(COALESCE(sr.vertical, ''))) <> 'generic'
    """,
    """
    DELETE dup
    FROM semantic_column_map dup
    JOIN _semantic_registry_vertical_remap remap
      ON remap.old_id = dup.semantic_registry_id
     AND remap.old_id <> remap.new_id
    JOIN semantic_column_map keep
      ON keep.semantic_registry_id = remap.new_id
     AND keep.workspace_norm = dup.workspace_norm
     AND (
       (keep.workspace_column_id <=> dup.workspace_column_id)
       OR (
         keep.table_name <=> dup.table_name
         AND keep.column_name <=> dup.column_name
       )
     )
    """,
    """
    UPDATE semantic_column_map scm
    JOIN _semantic_registry_vertical_remap remap
      ON remap.old_id = scm.semantic_registry_id
    SET scm.semantic_registry_id = remap.new_id
    WHERE remap.old_id <> remap.new_id
    """,
    """
    DELETE rel
    FROM semantic_relationship rel
    LEFT JOIN _semantic_registry_vertical_remap parent_map
      ON parent_map.old_id = rel.parent_concept_id
    LEFT JOIN _semantic_registry_vertical_remap child_map
      ON child_map.old_id = rel.child_concept_id
    WHERE COALESCE(parent_map.new_id, rel.parent_concept_id) = COALESCE(child_map.new_id, rel.child_concept_id)
    """,
    """
    DELETE dup
    FROM semantic_relationship dup
    LEFT JOIN _semantic_registry_vertical_remap dup_parent_map
      ON dup_parent_map.old_id = dup.parent_concept_id
    LEFT JOIN _semantic_registry_vertical_remap dup_child_map
      ON dup_child_map.old_id = dup.child_concept_id
    JOIN semantic_relationship keep
      ON dup.id > keep.id
     AND dup.relationship_type = keep.relationship_type
    LEFT JOIN _semantic_registry_vertical_remap keep_parent_map
      ON keep_parent_map.old_id = keep.parent_concept_id
    LEFT JOIN _semantic_registry_vertical_remap keep_child_map
      ON keep_child_map.old_id = keep.child_concept_id
    WHERE COALESCE(dup_parent_map.new_id, dup.parent_concept_id) = COALESCE(keep_parent_map.new_id, keep.parent_concept_id)
      AND COALESCE(dup_child_map.new_id, dup.child_concept_id) = COALESCE(keep_child_map.new_id, keep.child_concept_id)
    """,
    """
    UPDATE semantic_relationship rel
    LEFT JOIN _semantic_registry_vertical_remap parent_map
      ON parent_map.old_id = rel.parent_concept_id
    LEFT JOIN _semantic_registry_vertical_remap child_map
      ON child_map.old_id = rel.child_concept_id
    SET rel.parent_concept_id = COALESCE(parent_map.new_id, rel.parent_concept_id),
        rel.child_concept_id = COALESCE(child_map.new_id, rel.child_concept_id)
    WHERE parent_map.old_id IS NOT NULL
       OR child_map.old_id IS NOT NULL
    """,
    """
    DELETE sr
    FROM semantic_registry sr
    JOIN _semantic_registry_vertical_remap remap
      ON remap.old_id = sr.id
    WHERE remap.old_id <> remap.new_id
    """,
    "DROP TEMPORARY TABLE IF EXISTS _semantic_registry_vertical_remap",
)


class SemanticRegistryGraphNormalizationService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def audit_legacy_registry_graph_rows(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for label, query in _AUDIT_QUERIES:
            rows = self._sql.execute_query_mappings(query)
            out[label] = _read_count(rows)
        return out

    def normalize_legacy_registry_graph(self, *, dry_run: bool = True) -> Dict[str, Any]:
        before = self.audit_legacy_registry_graph_rows()
        if dry_run:
            return {
                "dry_run": True,
                "legacy_counts_before": before,
                "write_steps_executed": 0,
            }

        for query in _NORMALIZATION_WRITES:
            self._sql.execute_write(query)

        after = self.audit_legacy_registry_graph_rows()
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


__all__ = ["SemanticRegistryGraphNormalizationService"]
