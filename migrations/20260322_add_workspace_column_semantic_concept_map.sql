CREATE TABLE IF NOT EXISTS workspace_column_semantic_concept_map (
  id bigint unsigned NOT NULL AUTO_INCREMENT,
  vertical_norm varchar(50) NOT NULL DEFAULT 'generic',
  semantic_concept_id bigint unsigned NOT NULL,
  workspace_column_id bigint unsigned NOT NULL,
  relationship_kind varchar(30) NOT NULL DEFAULT 'primary',
  weight decimal(4,3) NOT NULL DEFAULT 1.000,
  created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_ws_map (vertical_norm, semantic_concept_id, workspace_column_id, relationship_kind),
  KEY idx_ws_map_concept (vertical_norm, semantic_concept_id),
  KEY idx_ws_map_column (workspace_column_id),
  CONSTRAINT fk_ws_map_concept FOREIGN KEY (semantic_concept_id) REFERENCES semantic_concept (id) ON DELETE CASCADE,
  CONSTRAINT fk_ws_map_column FOREIGN KEY (workspace_column_id) REFERENCES workspace_column (id) ON DELETE CASCADE
);
