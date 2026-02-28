ALTER TABLE model_column
  ADD COLUMN semantic_concept_id BIGINT UNSIGNED NULL,
  ADD COLUMN semantic_concept_key VARCHAR(150) NULL,
  ADD COLUMN semantic_entity VARCHAR(100) NULL,
  ADD COLUMN semantic_sub_type VARCHAR(200) NULL,
  ADD COLUMN semantic_granularity_rank INT NOT NULL DEFAULT 0,
  ADD COLUMN semantic_source VARCHAR(20) NULL,
  ADD COLUMN semantic_confidence DECIMAL(4,3) NULL,
  ADD COLUMN semantic_reasons_json LONGTEXT NULL,
  ADD COLUMN semantic_warnings_json LONGTEXT NULL,
  ADD COLUMN semantic_updated_at DATETIME NULL;

ALTER TABLE model_column
  ADD KEY idx_model_column_semantic_concept_id (semantic_concept_id),
  ADD KEY idx_model_column_semantic_concept_key (semantic_concept_key),
  ADD KEY idx_model_column_table_semantic_key (model_table_id, semantic_concept_key);

ALTER TABLE model_column
  ADD CONSTRAINT fk_model_column_semantic_concept
  FOREIGN KEY (semantic_concept_id) REFERENCES semantic_concept(id)
  ON DELETE SET NULL;

CREATE TABLE model_column_semantic_concept_map (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  vertical_norm VARCHAR(50) NOT NULL DEFAULT 'generic',
  semantic_concept_id BIGINT UNSIGNED NOT NULL,
  model_column_id BIGINT UNSIGNED NOT NULL,
  relationship_kind VARCHAR(30) NOT NULL DEFAULT 'primary',
  weight DECIMAL(4,3) NOT NULL DEFAULT 1.000,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_map (vertical_norm, semantic_concept_id, model_column_id, relationship_kind),
  KEY idx_map_concept (vertical_norm, semantic_concept_id),
  KEY idx_map_column (model_column_id),
  CONSTRAINT fk_map_concept FOREIGN KEY (semantic_concept_id) REFERENCES semantic_concept(id) ON DELETE CASCADE,
  CONSTRAINT fk_map_column FOREIGN KEY (model_column_id) REFERENCES model_column(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE semantic_value_alias (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  vertical_norm VARCHAR(50) NOT NULL DEFAULT 'generic',
  semantic_concept_id BIGINT UNSIGNED NOT NULL,
  canonical_value VARCHAR(300) NOT NULL,
  alias_value VARCHAR(300) NOT NULL,
  match_kind VARCHAR(20) NOT NULL DEFAULT 'contains',
  weight DECIMAL(4,3) NOT NULL DEFAULT 1.000,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_val_alias (vertical_norm, semantic_concept_id, alias_value, match_kind),
  KEY idx_val_alias_concept (vertical_norm, semantic_concept_id),
  CONSTRAINT fk_val_alias_concept FOREIGN KEY (semantic_concept_id) REFERENCES semantic_concept(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
