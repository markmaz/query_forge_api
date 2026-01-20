-- V006__add_filter_mode.sql
-- Add filter_mode to domain_workspace_table to control WHERE vs EXISTS filters

SET @tbl := 'domain_workspace_table';
SET @col := 'filter_mode';

SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND column_name = @col
);

SET @sql := IF(@exists = 0,
  'ALTER TABLE `domain_workspace_table` ADD COLUMN `filter_mode` enum(''AUTO'',''WHERE'',''EXISTS'') NOT NULL DEFAULT ''AUTO''',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx := 'ix_dwt_domain_filter_mode';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND index_name = @idx
);

SET @sql := IF(@exists = 0,
  'CREATE INDEX `ix_dwt_domain_filter_mode` ON `domain_workspace_table` (`domain_id`,`filter_mode`)',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col := 'cardinality';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND column_name = @col
);

SET @sql := IF(@exists = 0,
  'ALTER TABLE `domain_workspace_table` ADD COLUMN `cardinality` enum(''ONE'',''MANY'') NOT NULL DEFAULT ''ONE''',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx := 'ix_dwt_domain_cardinality';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND index_name = @idx
);

SET @sql := IF(@exists = 0,
  'CREATE INDEX `ix_dwt_domain_cardinality` ON `domain_workspace_table` (`domain_id`,`cardinality`)',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
