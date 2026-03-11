-- Add default-workspace flag to tenancy-native workspace_membership.
-- This replaces legacy user_workspace_map.is_default behavior.

SET @db_name := DATABASE();

DELIMITER $$

DROP PROCEDURE IF EXISTS qf_add_column_if_missing $$
CREATE PROCEDURE qf_add_column_if_missing(
  IN p_table_name VARCHAR(128),
  IN p_column_name VARCHAR(128),
  IN p_column_def TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
      AND column_name = p_column_name
  ) THEN
    SET @sql := CONCAT('ALTER TABLE `', p_table_name, '` ADD COLUMN ', p_column_def);
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END $$

DROP PROCEDURE IF EXISTS qf_add_index_if_missing $$
CREATE PROCEDURE qf_add_index_if_missing(
  IN p_table_name VARCHAR(128),
  IN p_index_name VARCHAR(128),
  IN p_index_sql TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = p_table_name
      AND index_name = p_index_name
  ) THEN
    SET @sql := p_index_sql;
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END $$

DELIMITER ;

CALL qf_add_column_if_missing(
  'workspace_membership',
  'is_default',
  '`is_default` tinyint(1) NOT NULL DEFAULT 0'
);

CALL qf_add_index_if_missing(
  'workspace_membership',
  'ix_workspace_membership_user_default',
  'ALTER TABLE `workspace_membership` ADD KEY `ix_workspace_membership_user_default` (`user_id`, `is_default`)'
);

DROP PROCEDURE IF EXISTS qf_add_column_if_missing;
DROP PROCEDURE IF EXISTS qf_add_index_if_missing;
