-- V007__domain_column_policy.sql
-- Add column_name_policy to domain for column de-dupe behavior

SET @tbl := 'domain';
SET @col := 'column_name_policy';

SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND column_name = @col
);

SET @sql := IF(@exists = 0,
  'ALTER TABLE `domain` ADD COLUMN `column_name_policy` enum(''DEDUP_PRIMARY_FIRST'',''SHOW_ALL_QUALIFIED'') NOT NULL DEFAULT ''DEDUP_PRIMARY_FIRST''',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx := 'ix_domain_column_name_policy';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND index_name = @idx
);

SET @sql := IF(@exists = 0,
  'CREATE INDEX `ix_domain_column_name_policy` ON `domain` (`column_name_policy`)',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
