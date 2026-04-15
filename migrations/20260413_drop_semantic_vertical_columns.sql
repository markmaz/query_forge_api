ALTER TABLE semantic_concept
  DROP INDEX uq_concept_vertical_key,
  DROP INDEX idx_concept_vertical_type,
  ADD CONSTRAINT uq_concept_key UNIQUE (concept_key),
  ADD INDEX idx_concept_type (semantic_type),
  DROP COLUMN vertical_norm;

ALTER TABLE semantic_concept_alias
  DROP INDEX uq_alias,
  DROP INDEX idx_alias_vertical,
  DROP INDEX idx_alias_concept,
  ADD CONSTRAINT uq_alias UNIQUE (alias_key, match_kind),
  ADD INDEX idx_alias_concept (concept_key),
  DROP COLUMN vertical_norm;

ALTER TABLE workspace_column_semantic_concept_map
  DROP INDEX uq_ws_map,
  DROP INDEX idx_ws_map_concept,
  ADD CONSTRAINT uq_ws_map UNIQUE (semantic_concept_id, workspace_column_id, relationship_kind),
  ADD INDEX idx_ws_map_concept (semantic_concept_id),
  DROP COLUMN vertical_norm;

ALTER TABLE semantic_value_alias
  DROP INDEX uq_val_alias,
  DROP INDEX idx_val_alias_concept,
  ADD CONSTRAINT uq_val_alias UNIQUE (semantic_concept_id, alias_value, match_kind),
  ADD INDEX idx_val_alias_concept (semantic_concept_id),
  DROP COLUMN vertical_norm;

ALTER TABLE semantic_registry
  DROP INDEX uq_semantic_registry_vertical_concept,
  DROP INDEX idx_semantic_registry_vertical_type,
  DROP INDEX idx_semantic_registry_vertical_entity,
  ADD CONSTRAINT uq_semantic_registry_concept UNIQUE (concept_key),
  ADD INDEX idx_semantic_registry_type (semantic_type),
  ADD INDEX idx_semantic_registry_entity (entity),
  DROP COLUMN vertical_norm,
  DROP COLUMN vertical;
