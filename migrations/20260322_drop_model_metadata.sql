ALTER TABLE domain
  DROP FOREIGN KEY fk_domain_model_table,
  DROP INDEX ix_domain_model_table_id,
  DROP COLUMN model_table_id;

ALTER TABLE workspace_table
  DROP FOREIGN KEY fk_ws_table_model,
  DROP INDEX ix_ws_model,
  DROP INDEX ix_ws_unmapped,
  DROP INDEX fk_ws_table_model,
  DROP COLUMN model_table_id,
  ADD KEY ix_ws_unmapped (workspace_id, schema_name, table_name);

DROP TABLE IF EXISTS model_column_semantic_concept_map;
DROP TABLE IF EXISTS model_column;
DROP TABLE IF EXISTS model_table;
