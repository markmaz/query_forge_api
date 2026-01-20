-- V004__domain_filter_mode.sql
-- Adds filter_mode to domain_workspace_table for EXISTS-aware filtering.
-- Idempotent.

SET @tbl := 'domain_workspace_table';

-- ------------------------------------------------------------
-- 1) filter_mode: AUTO | WHERE | EXISTS
-- ------------------------------------------------------------
SET @col := 'filter_mode';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND column_name = @col
);

SET @sql := IF(@exists = 0,
  "ALTER TABLE `domain_workspace_table`
     ADD COLUMN `filter_mode` enum('AUTO','WHERE','EXISTS') NOT NULL DEFAULT 'AUTO'
     AFTER `table_alias`",
  "SELECT 1"
);

PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Helpful index for reads (domain editor + resolver)
SET @idx := 'ix_dwt_domain_filter_mode';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND index_name = @idx
);

SET @sql := IF(@exists = 0,
  "CREATE INDEX `ix_dwt_domain_filter_mode`
     ON `domain_workspace_table` (`domain_id`, `filter_mode`)",
  "SELECT 1"
);

PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 2) cardinality: ONE | MANY (relative to the primary/root)
-- ------------------------------------------------------------
SET @col := 'cardinality';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND column_name = @col
);

SET @sql := IF(@exists = 0,
  "ALTER TABLE `domain_workspace_table`
     ADD COLUMN `cardinality` enum('ONE','MANY') NOT NULL DEFAULT 'ONE'
     AFTER `filter_mode`",
  "SELECT 1"
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
  "CREATE INDEX `ix_dwt_domain_cardinality`
     ON `domain_workspace_table` (`domain_id`, `cardinality`)",
  "SELECT 1"
);

PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;