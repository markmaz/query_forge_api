-- Preflight audit queries. Run before the DML if you need to inspect legacy
-- direct-semantic rows before collapsing them into the generic compatibility set.
--
-- SELECT 'semantic_concept' AS table_name, COUNT(*) AS legacy_rows
--   FROM semantic_concept
--  WHERE LOWER(TRIM(COALESCE(vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
-- UNION ALL
-- SELECT 'semantic_concept_alias', COUNT(*)
--   FROM semantic_concept_alias
--  WHERE LOWER(TRIM(COALESCE(vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
-- UNION ALL
-- SELECT 'workspace_column_semantic_concept_map', COUNT(*)
--   FROM workspace_column_semantic_concept_map
--  WHERE LOWER(TRIM(COALESCE(vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
-- UNION ALL
-- SELECT 'semantic_value_alias', COUNT(*)
--   FROM semantic_value_alias
--  WHERE LOWER(TRIM(COALESCE(vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null');

DELETE dup
FROM semantic_concept dup
JOIN semantic_concept keep
  ON dup.id > keep.id
 AND dup.concept_key = keep.concept_key
 AND LOWER(TRIM(COALESCE(dup.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
 AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null');

DELETE old
FROM semantic_concept old
JOIN semantic_concept keep
  ON keep.concept_key = old.concept_key
 AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) = 'generic'
WHERE LOWER(TRIM(COALESCE(old.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
  AND old.id <> keep.id;

UPDATE semantic_concept
   SET vertical_norm = 'generic'
 WHERE LOWER(TRIM(COALESCE(vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null');

DELETE dup
FROM semantic_concept_alias dup
JOIN semantic_concept_alias keep
  ON dup.id > keep.id
 AND dup.alias_key = keep.alias_key
 AND dup.match_kind = keep.match_kind
 AND LOWER(TRIM(COALESCE(dup.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
 AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null');

DELETE old
FROM semantic_concept_alias old
JOIN semantic_concept_alias keep
  ON keep.alias_key = old.alias_key
 AND keep.match_kind = old.match_kind
 AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) = 'generic'
WHERE LOWER(TRIM(COALESCE(old.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
  AND old.id <> keep.id;

UPDATE semantic_concept_alias
   SET vertical_norm = 'generic'
 WHERE LOWER(TRIM(COALESCE(vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null');

DELETE dup
FROM workspace_column_semantic_concept_map dup
JOIN workspace_column_semantic_concept_map keep
  ON dup.id > keep.id
 AND dup.semantic_concept_id = keep.semantic_concept_id
 AND dup.workspace_column_id = keep.workspace_column_id
 AND dup.relationship_kind = keep.relationship_kind
 AND LOWER(TRIM(COALESCE(dup.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
 AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null');

DELETE old
FROM workspace_column_semantic_concept_map old
JOIN workspace_column_semantic_concept_map keep
  ON keep.semantic_concept_id = old.semantic_concept_id
 AND keep.workspace_column_id = old.workspace_column_id
 AND keep.relationship_kind = old.relationship_kind
 AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) = 'generic'
WHERE LOWER(TRIM(COALESCE(old.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
  AND old.id <> keep.id;

UPDATE workspace_column_semantic_concept_map
   SET vertical_norm = 'generic'
 WHERE LOWER(TRIM(COALESCE(vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null');

DELETE dup
FROM semantic_value_alias dup
JOIN semantic_value_alias keep
  ON dup.id > keep.id
 AND dup.semantic_concept_id = keep.semantic_concept_id
 AND dup.alias_value = keep.alias_value
 AND dup.match_kind = keep.match_kind
 AND LOWER(TRIM(COALESCE(dup.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
 AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null');

DELETE old
FROM semantic_value_alias old
JOIN semantic_value_alias keep
  ON keep.semantic_concept_id = old.semantic_concept_id
 AND keep.alias_value = old.alias_value
 AND keep.match_kind = old.match_kind
 AND LOWER(TRIM(COALESCE(keep.vertical_norm, ''))) = 'generic'
WHERE LOWER(TRIM(COALESCE(old.vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null')
  AND old.id <> keep.id;

UPDATE semantic_value_alias
   SET vertical_norm = 'generic'
 WHERE LOWER(TRIM(COALESCE(vertical_norm, ''))) IN ('education', 'global', '__global__', '', 'none', 'null');
