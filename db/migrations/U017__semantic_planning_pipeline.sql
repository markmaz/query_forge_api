DROP TABLE IF EXISTS semantic_value_alias;
DROP TABLE IF EXISTS model_column_semantic_concept_map;

ALTER TABLE model_column
  DROP FOREIGN KEY fk_model_column_semantic_concept;

ALTER TABLE model_column
  DROP KEY idx_model_column_table_semantic_key,
  DROP KEY idx_model_column_semantic_concept_key,
  DROP KEY idx_model_column_semantic_concept_id;

ALTER TABLE model_column
  DROP COLUMN semantic_updated_at,
  DROP COLUMN semantic_warnings_json,
  DROP COLUMN semantic_reasons_json,
  DROP COLUMN semantic_confidence,
  DROP COLUMN semantic_source,
  DROP COLUMN semantic_granularity_rank,
  DROP COLUMN semantic_sub_type,
  DROP COLUMN semantic_entity,
  DROP COLUMN semantic_concept_key,
  DROP COLUMN semantic_concept_id;
