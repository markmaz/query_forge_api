use query_forge_demo;
-- PR-01 metadata consolidation prep
-- Expand workspace_* tables to hold metadata currently sourced from model_* tables.
-- Safe to run multiple times (uses IF NOT EXISTS).

ALTER TABLE workspace_table
  ADD COLUMN source_table_name VARCHAR(255) NULL,
  ADD COLUMN description TEXT NULL,
  ADD COLUMN origin VARCHAR(32) NULL,
  ADD COLUMN is_missing_in_source TINYINT(1) NOT NULL DEFAULT 0,
  ADD COLUMN metadata_synced_at DATETIME NULL,
  ADD COLUMN metadata_updated_at DATETIME NULL;

ALTER TABLE workspace_column
  ADD COLUMN description TEXT NULL,
  ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1,
  ADD COLUMN origin VARCHAR(32) NULL,
  ADD COLUMN is_missing_in_source TINYINT(1) NOT NULL DEFAULT 0,
  ADD COLUMN semantic_type VARCHAR(100) NULL,
  ADD COLUMN semantic_entity VARCHAR(100) NULL,
  ADD COLUMN semantic_sub_type VARCHAR(200) NULL,
  ADD COLUMN semantic_source VARCHAR(20) NULL,
  ADD COLUMN semantic_confidence DECIMAL(6,5) NULL,
  ADD COLUMN semantic_concept_key VARCHAR(128) NULL,
  ADD COLUMN semantic_concept_id BIGINT UNSIGNED NULL,
  ADD COLUMN semantic_assigned_at DATETIME NULL,
  ADD COLUMN semantic_reasons_json JSON NULL,
  ADD COLUMN sample_values_json JSON NULL,
  ADD COLUMN sample_stats_json JSON NULL,
  ADD COLUMN sample_ran_at DATETIME NULL,
  ADD COLUMN sample_error TEXT NULL,
  ADD COLUMN metadata_updated_at DATETIME NULL;