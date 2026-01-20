-- V008__crosswalk_user_share.sql
-- Add user_id + is_shared to crosswalk list tables (MySQL). Idempotent.

-- ------------------------------------------------------------
-- custom_regions_lists
-- ------------------------------------------------------------
SET @tbl := 'custom_regions_lists';
SET @tbl_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
);

-- user_id
SET @col := 'user_id';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND column_name = @col
);
SET @sql := IF(@tbl_exists = 0,
  'SELECT 1',
  IF(@exists = 0,
    'ALTER TABLE `custom_regions_lists` ADD COLUMN `user_id` varchar(255) NULL AFTER `user_name`',
    'SELECT 1'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- is_shared
SET @col := 'is_shared';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND column_name = @col
);
SET @sql := IF(@tbl_exists = 0,
  'SELECT 1',
  IF(@exists = 0,
    'ALTER TABLE `custom_regions_lists` ADD COLUMN `is_shared` tinyint(1) NOT NULL DEFAULT 0 AFTER `user_id`',
    'SELECT 1'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- index (workspace_id, user_id)
SET @idx := 'ix_regions_ws_user';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND index_name = @idx
);
SET @sql := IF(@tbl_exists = 0,
  'SELECT 1',
  IF(@exists = 0,
    'CREATE INDEX `ix_regions_ws_user` ON `custom_regions_lists` (`workspace_id`, `user_id`)',
    'SELECT 1'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- index (workspace_id, is_shared)
SET @idx := 'ix_regions_ws_shared';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND index_name = @idx
);
SET @sql := IF(@tbl_exists = 0,
  'SELECT 1',
  IF(@exists = 0,
    'CREATE INDEX `ix_regions_ws_shared` ON `custom_regions_lists` (`workspace_id`, `is_shared`)',
    'SELECT 1'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- custom_npi_categories_lists
-- ------------------------------------------------------------
SET @tbl := 'custom_npi_categories_lists';
SET @tbl_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
);

-- user_id
SET @col := 'user_id';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND column_name = @col
);
SET @sql := IF(@tbl_exists = 0,
  'SELECT 1',
  IF(@exists = 0,
    'ALTER TABLE `custom_npi_categories_lists` ADD COLUMN `user_id` varchar(255) NULL AFTER `user_name`',
    'SELECT 1'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- is_shared
SET @col := 'is_shared';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND column_name = @col
);
SET @sql := IF(@tbl_exists = 0,
  'SELECT 1',
  IF(@exists = 0,
    'ALTER TABLE `custom_npi_categories_lists` ADD COLUMN `is_shared` tinyint(1) NOT NULL DEFAULT 0 AFTER `user_id`',
    'SELECT 1'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- index (workspace_id, user_id)
SET @idx := 'ix_npi_ws_user';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND index_name = @idx
);
SET @sql := IF(@tbl_exists = 0,
  'SELECT 1',
  IF(@exists = 0,
    'CREATE INDEX `ix_npi_ws_user` ON `custom_npi_categories_lists` (`workspace_id`, `user_id`)',
    'SELECT 1'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- index (workspace_id, is_shared)
SET @idx := 'ix_npi_ws_shared';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND index_name = @idx
);
SET @sql := IF(@tbl_exists = 0,
  'SELECT 1',
  IF(@exists = 0,
    'CREATE INDEX `ix_npi_ws_shared` ON `custom_npi_categories_lists` (`workspace_id`, `is_shared`)',
    'SELECT 1'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- custom_service_lines_lists
-- ------------------------------------------------------------
SET @tbl := 'custom_service_lines_lists';
SET @tbl_exists := (
  SELECT COUNT(*)
  FROM information_schema.tables
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
);

-- user_id
SET @col := 'user_id';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND column_name = @col
);
SET @sql := IF(@tbl_exists = 0,
  'SELECT 1',
  IF(@exists = 0,
    'ALTER TABLE `custom_service_lines_lists` ADD COLUMN `user_id` varchar(255) NULL AFTER `user_name`',
    'SELECT 1'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- is_shared
SET @col := 'is_shared';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND column_name = @col
);
SET @sql := IF(@tbl_exists = 0,
  'SELECT 1',
  IF(@exists = 0,
    'ALTER TABLE `custom_service_lines_lists` ADD COLUMN `is_shared` tinyint(1) NOT NULL DEFAULT 0 AFTER `user_id`',
    'SELECT 1'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- index (workspace_id, user_id)
SET @idx := 'ix_svc_ws_user';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND index_name = @idx
);
SET @sql := IF(@tbl_exists = 0,
  'SELECT 1',
  IF(@exists = 0,
    'CREATE INDEX `ix_svc_ws_user` ON `custom_service_lines_lists` (`workspace_id`, `user_id`)',
    'SELECT 1'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- index (workspace_id, is_shared)
SET @idx := 'ix_svc_ws_shared';
SET @exists := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = @tbl
    AND index_name = @idx
);
SET @sql := IF(@tbl_exists = 0,
  'SELECT 1',
  IF(@exists = 0,
    'CREATE INDEX `ix_svc_ws_shared` ON `custom_service_lines_lists` (`workspace_id`, `is_shared`)',
    'SELECT 1'
  )
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
