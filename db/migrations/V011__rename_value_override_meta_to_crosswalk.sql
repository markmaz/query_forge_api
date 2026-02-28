-- V011__rename_value_override_meta_to_crosswalk.sql
-- Rename value_override metadata table back to crosswalk metadata table.
-- Idempotent: only renames when source exists and target does not.

SET @source_tbl := 'value_override_list_meta';
SET @target_tbl := 'crosswalk_list_meta';

SET @source_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = @source_tbl
);

SET @target_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = @target_tbl
);

SET @sql := IF(
  @source_exists = 1 AND @target_exists = 0,
  'RENAME TABLE `value_override_list_meta` TO `crosswalk_list_meta`',
  'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
