-- PR-01 metadata consolidation prep
-- Expand workspace_* tables to hold metadata currently sourced from model_* tables.
-- Safe to run multiple times (uses IF NOT EXISTS).

ALTER TABLE workspace_table
  ADD COLUMN IF NOT EXISTS source_table_name VARCHAR(255) NULL,
  ADD COLUMN IF NOT EXISTS description TEXT NULL,
  ADD COLUMN IF NOT EXISTS origin VARCHAR(32) NULL,
  ADD COLUMN IF NOT EXISTS is_missing_in_source TINYINT(1) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS metadata_synced_at DATETIME NULL,
  ADD COLUMN IF NOT EXISTS metadata_updated_at DATETIME NULL;

ALTER TABLE workspace_column
  ADD COLUMN IF NOT EXISTS description TEXT NULL,
  ADD COLUMN IF NOT EXISTS is_active TINYINT(1) NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS origin VARCHAR(32) NULL,
  ADD COLUMN IF NOT EXISTS is_missing_in_source TINYINT(1) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS semantic_type VARCHAR(100) NULL,
  ADD COLUMN IF NOT EXISTS semantic_entity VARCHAR(100) NULL,
  ADD COLUMN IF NOT EXISTS semantic_sub_type VARCHAR(200) NULL,
  ADD COLUMN IF NOT EXISTS semantic_source VARCHAR(20) NULL,
  ADD COLUMN IF NOT EXISTS semantic_confidence DECIMAL(6,5) NULL,
  ADD COLUMN IF NOT EXISTS semantic_concept_key VARCHAR(128) NULL,
  ADD COLUMN IF NOT EXISTS semantic_concept_id BIGINT UNSIGNED NULL,
  ADD COLUMN IF NOT EXISTS semantic_assigned_at DATETIME NULL,
  ADD COLUMN IF NOT EXISTS semantic_reasons_json JSON NULL,
  ADD COLUMN IF NOT EXISTS sample_values_json JSON NULL,
  ADD COLUMN IF NOT EXISTS sample_stats_json JSON NULL,
  ADD COLUMN IF NOT EXISTS sample_ran_at DATETIME NULL,
  ADD COLUMN IF NOT EXISTS sample_error TEXT NULL,
  ADD COLUMN IF NOT EXISTS metadata_updated_at DATETIME NULL;
