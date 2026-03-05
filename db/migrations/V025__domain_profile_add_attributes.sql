-- V025__domain_profile_add_attributes.sql
-- Adds the missing `attributes` JSON column to domain_profile.
-- The column was referenced in V009 seed data and application queries
-- but accidentally omitted from the original CREATE TABLE.

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'domain_profile'
    AND column_name = 'attributes'
);

SET @ddl = IF(@col_exists = 0,
  'ALTER TABLE `domain_profile` ADD COLUMN `attributes` json NULL AFTER `metrics`',
  'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
