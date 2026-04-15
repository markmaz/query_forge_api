-- Preflight audit queries. Run before the DML if you need to inspect legacy
-- semantic registry graph rows before collapsing them into the generic set.
--
-- SELECT 'semantic_registry' AS table_name, COUNT(*) AS legacy_rows
--   FROM semantic_registry sr
--  WHERE LOWER(TRIM(COALESCE(sr.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
-- UNION ALL
-- SELECT 'semantic_column_map', COUNT(*)
--   FROM semantic_column_map scm
--   JOIN semantic_registry sr ON sr.id = scm.semantic_registry_id
--  WHERE LOWER(TRIM(COALESCE(sr.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
-- UNION ALL
-- SELECT 'semantic_relationship', COUNT(*)
--   FROM semantic_relationship rel
--   JOIN semantic_registry parent ON parent.id = rel.parent_concept_id
--   JOIN semantic_registry child ON child.id = rel.child_concept_id
--  WHERE LOWER(TRIM(COALESCE(parent.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
--     OR LOWER(TRIM(COALESCE(child.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null');

DROP TABLE IF EXISTS _semantic_registry_vertical_remap;

CREATE TABLE _semantic_registry_vertical_remap (
  old_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  new_id BIGINT UNSIGNED NOT NULL
);

INSERT INTO _semantic_registry_vertical_remap (old_id, new_id)
SELECT legacy.id AS old_id, generic.id AS new_id
FROM semantic_registry legacy
JOIN semantic_registry generic
  ON generic.concept_key = legacy.concept_key
 AND LOWER(TRIM(COALESCE(generic.vertical_norm, ''))) = 'generic'
WHERE LOWER(TRIM(COALESCE(legacy.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
  AND legacy.id <> generic.id;

INSERT IGNORE INTO _semantic_registry_vertical_remap (old_id, new_id)
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
;

UPDATE semantic_registry sr
JOIN _semantic_registry_vertical_remap remap
  ON remap.old_id = sr.id
 AND remap.old_id = remap.new_id
SET sr.vertical = 'generic'
WHERE LOWER(TRIM(COALESCE(sr.vertical, ''))) <> 'generic';

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
 );

UPDATE semantic_column_map scm
JOIN _semantic_registry_vertical_remap remap
  ON remap.old_id = scm.semantic_registry_id
SET scm.semantic_registry_id = remap.new_id
WHERE remap.old_id <> remap.new_id;

DELETE rel
FROM semantic_relationship rel
LEFT JOIN _semantic_registry_vertical_remap parent_map
  ON parent_map.old_id = rel.parent_concept_id
LEFT JOIN _semantic_registry_vertical_remap child_map
  ON child_map.old_id = rel.child_concept_id
WHERE COALESCE(parent_map.new_id, rel.parent_concept_id) = COALESCE(child_map.new_id, rel.child_concept_id);

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
  AND COALESCE(dup_child_map.new_id, dup.child_concept_id) = COALESCE(keep_child_map.new_id, keep.child_concept_id);

UPDATE semantic_relationship rel
LEFT JOIN _semantic_registry_vertical_remap parent_map
  ON parent_map.old_id = rel.parent_concept_id
LEFT JOIN _semantic_registry_vertical_remap child_map
  ON child_map.old_id = rel.child_concept_id
SET rel.parent_concept_id = COALESCE(parent_map.new_id, rel.parent_concept_id),
    rel.child_concept_id = COALESCE(child_map.new_id, rel.child_concept_id)
WHERE parent_map.old_id IS NOT NULL
   OR child_map.old_id IS NOT NULL;

DELETE sr
FROM semantic_registry sr
JOIN _semantic_registry_vertical_remap remap
  ON remap.old_id = sr.id
WHERE remap.old_id <> remap.new_id;

DROP TABLE IF EXISTS _semantic_registry_vertical_remap;
