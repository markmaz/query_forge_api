ALTER TABLE semantic_column_map
  CHANGE COLUMN model_column_id workspace_column_id BIGINT UNSIGNED NULL;

ALTER TABLE semantic_column_map
  DROP INDEX uq_map_semreg_workspace_modelcol,
  DROP INDEX idx_map_workspace_modelcol,
  ADD UNIQUE KEY uq_map_semreg_workspace_column (semantic_registry_id, workspace_norm, workspace_column_id),
  ADD KEY idx_map_workspace_column (workspace_norm, workspace_column_id);

ALTER TABLE semantic_suggestion_item
  CHANGE COLUMN model_column_id workspace_column_id BIGINT UNSIGNED NOT NULL,
  CHANGE COLUMN model_table_id workspace_table_id BIGINT UNSIGNED NULL;

ALTER TABLE semantic_suggestion_item
  DROP INDEX uq_sem_suggestion_item_run_column,
  ADD UNIQUE KEY uq_sem_suggestion_item_run_column (run_id, workspace_column_id);
