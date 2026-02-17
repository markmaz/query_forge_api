-- V012__add_model_column_semantic_type.sql
-- Add semantic_type to model_column for semantic-aware ranking.
-- Idempotent: adds column only if it does not already exist.

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'model_column'
    AND column_name = 'semantic_type'
);

SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE `model_column` ADD COLUMN `semantic_type` VARCHAR(100) NULL AFTER `description`',
  'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
